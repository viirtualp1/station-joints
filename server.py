"""Бэкенд для Flutter-клиента: команды и ответы – JSON по строке через stdin/stdout.

Запрос:  {"id": 1, "cmd": "load", "path": "...", "sheets": "A3"}
Ответ:   {"id": 1, "ok": true, "result": {...}}  |  {"id": 1, "ok": false, "error": "..."}

Служебные: ping, sample, new_doc, close_doc. Команды документа (параметр doc – номер
таба из new_doc): load, restore, relayout, scene, recompute, add_joint, remove_joint,
toggle_negab, move_joint, edit_track, edit_signal, add_signal, reset_signal, explain,
undo, redo, save_project, set_project, thumb, export_png, export_pdf, export_docx.
Команды, меняющие схему, возвращают новую сцену (см. scene.py) и историю
{'undo', 'redo', 'dirty'} – есть ли несохранённые изменения, решает бэкенд."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import traceback
from typing import Callable

import edits
import explain
import project
from graph import Graph, Joint
from joints import Station, place_joints, update_negab, update_sections
from layout import build_station, snap_joints
from parser import parse_image
from render import LAYERS, layer_flags, render
from resources import resource
from scene import build_scene
from sheets import make_sheets, save_pdf
from signals import KIND_TEXT, Signal, place_signals, prune_signal_joints
from vedomost import save_docx

VERSION = 6
HISTORY = 100                            # шагов отмены


class Session:
    """Одна открытая схема (таб): распознанный граф, компоновка, ручные правки, история."""

    def __init__(self):
        self.st: Station | None = None
        self.annots: list = []
        self.sheets: str | None = None      # «Два листа» выключены по умолчанию
        self.odd_right: bool | None = None   # None – по умолчанию (joints.ODD_RIGHT)
        self.layers = dict(LAYERS)
        # распознанная схема – до компоновки (компоновка меняет граф)
        self.graph0: Graph | None = None
        self.annots0: list = []
        self.info: dict = {}
        self.src: bytes = b''
        self.src_name = ''
        self.src_image = ''                  # файл картинки для превью в интерфейсе
        self.path: str | None = None         # открытый файл: картинка или .stj
        self.project: str | None = None      # файл работы, если открыт/сохранён
        self.edited = False                  # есть ручные правки стыков
        self.sops: list[dict] = []           # ручные правки светофоров (edits.py)
        # история для отмены/повтора: снимки стыков, графа и настроек компоновки
        self.hist: list[dict] = []
        self.pos = 0
        self.saved: int | None = None        # шаг истории, совпадающий с файлом на диске

    def _need(self) -> Station:
        if self.st is None:
            raise ValueError('схема не загружена')
        return self.st

    def _joint(self, i) -> Joint:
        joints = self._need().joints
        i = int(i)
        if not 0 <= i < len(joints):
            raise ValueError('стык не найден – схема изменилась, выберите его заново')
        return joints[i]

    def _signal_obj(self, i) -> Signal:
        signals = self._need().signals
        i = int(i)
        if not 0 <= i < len(signals):
            raise ValueError('светофор не найден – схема изменилась, выберите его заново')
        return signals[i]

    def scene(self):
        return build_scene(self._need(), self.annots, self.layers)

    def _source(self):
        st = self._need()
        return {'path': self.path, 'name': self.src_name, 'image': self.src_image,
                'project': self.project, 'angle': self.info.get('angle', 0.0),
                'sheets': self.sheets, 'odd_right': st.odd_right, 'edited': self.edited}

    def _with_source(self):
        res = self.scene()
        res['source'] = self._source()
        res['history'] = self._history()
        return res

    # --- отмена / повтор -----------------------------------------------------------
    def _snap(self, label: str) -> dict:
        st = self._need()
        assert self.graph0 is not None
        return {'label': label, 'sheets': self.sheets, 'odd_right': st.odd_right,
                'edited': self.edited, 'joints': project.joints_to_json(st.joints),
                'graph': project.graph_to_json(self.graph0), 'sops': copy.deepcopy(self.sops)}

    def _reset_history(self, saved: bool):
        """Новая история; saved – состояние совпадает с файлом на диске."""
        self.hist, self.pos = [self._snap('')], 0
        self.saved = 0 if saved else None

    def _commit(self, label: str):
        if self.saved is not None and self.saved > self.pos:
            self.saved = None                # сохранённое состояние было в отменённой ветке
        del self.hist[self.pos + 1:]
        self.hist.append(self._snap(label))
        if len(self.hist) > HISTORY:
            del self.hist[0]
            if self.saved is not None:
                self.saved = self.saved - 1 if self.saved > 0 else None
        self.pos = len(self.hist) - 1

    def _history(self):
        return {'undo': self.hist[self.pos]['label'] if self.pos > 0 else None,
                'redo': self.hist[self.pos + 1]['label'] if self.pos + 1 < len(self.hist) else None,
                'dirty': self.saved != self.pos}

    def _restore(self, snap: dict):
        self.sheets, self.odd_right, self.edited = snap['sheets'], snap['odd_right'], snap['edited']
        self.graph0 = project.graph_from_json(snap['graph'])
        self.sops = copy.deepcopy(snap['sops'])
        self._build(project.joints_from_json(snap['joints']))

    def undo(self):
        if self.pos == 0:
            raise ValueError('нечего отменять')
        label = self.hist[self.pos]['label']
        self.pos -= 1
        self._restore(self.hist[self.pos])
        res = self._with_source()
        res['done'] = label
        return res

    def redo(self):
        if self.pos + 1 >= len(self.hist):
            raise ValueError('нечего повторять')
        self.pos += 1
        self._restore(self.hist[self.pos])
        res = self._with_source()
        res['done'] = self.hist[self.pos]['label']
        return res

    def _edit(self, label: str, change: Callable[[], object]) -> dict:
        """Правка документа как транзакция: change() меняет состояние; если она упала –
        документ возвращается к текущему шагу истории (а не остаётся наполовину изменённым)."""
        try:
            change()
        except Exception:
            self._restore(self.hist[self.pos])
            raise
        self._commit(label)
        return self._with_source()

    # --- компоновка ------------------------------------------------------------------
    def _settings(self, sheets, odd_right, layers):
        if sheets != 'keep':
            self.sheets = sheets or None
        if odd_right is not None:
            self.odd_right = bool(odd_right)
        if layers:
            self.layers.update(layers)

    def _build(self, joints: list | None = None):
        """Компоновка из распознанного графа; joints – сохранённые стыки (из файла работы
        или истории; пустой список – все стыки удалены вручную, это тоже состояние)."""
        self.st, self.annots = build_station(copy.deepcopy(self.graph0), copy.deepcopy(self.annots0),
                                             sheet_fmt=self.sheets, odd_right=self.odd_right)
        if joints is not None and all(j.edge in self.st.g.edges for j in joints):
            self.st.joints = joints
            self._refresh()
        elif self.sops:
            edits.apply_signal_ops(self.st, self.sops)

    def _refresh(self):
        st = self._need()
        update_sections(st)
        place_signals(st)                    # светофоры стоят на стыках – пересчитать
        edits.apply_signal_ops(st, self.sops)

    def _joint_edits(self) -> list[dict]:
        """Ручные правки стыков относительно расстановки по правилам (на этой компоновке)."""
        if not self.edited:
            return []
        rules, _ = build_station(copy.deepcopy(self.graph0), [], sheet_fmt=self.sheets,
                                 odd_right=self.odd_right)
        return edits.diff_joints(rules, self._need())

    def _rebuild_keeping_edits(self, ops: list[dict]):
        """Перекомпоновка, после которой ручные правки стыков ложатся на новые места."""
        self._build()
        if ops:
            edits.apply_joint_ops(self._need(), ops)
            self._refresh()

    def _joint_edit(self, label: str, change: Callable[[], object]) -> dict:
        def run():
            change()
            self.edited = True
            self._refresh()
        return self._edit(label, run)

    # --- команды -----------------------------------------------------------------
    def ping(self):
        return {'version': VERSION}

    def sample(self):
        return {'path': resource(os.path.join('samples', 'var96_photo.jpg'))}

    def load(self, path: str | None = None, sheets='keep', layers: dict | None = None,
             odd_right: bool | None = None):
        """Открыть картинку (распознать) или файл работы .stj.
        sheets: 'A4'|'A3'|'A2'|None|'keep'; odd_right: нечётная горловина справа."""
        path = path or self.path
        if not path:
            raise ValueError('не указан файл')
        self._settings(sheets, odd_right, layers)
        if path.lower().endswith(project.EXT):
            return self._open_project(path)
        parsed = parse_image(path)
        with open(path, 'rb') as f:
            self.src = f.read()
        self.graph0 = copy.deepcopy(parsed['graph'])
        self.annots0 = copy.deepcopy(parsed['annots'])
        self.info = parsed['info']
        self.src_name = os.path.basename(path)
        self.src_image = path
        self.path, self.project, self.edited = path, None, False
        self.sops = []
        self._build()
        self._reset_history(saved=True)      # картинка без правок – сохранять нечего
        return self._with_source()

    def _open_project(self, path: str):
        d = project.load(path)
        self.graph0, self.annots0, self.info = d['graph'], d['annots'], d['info']
        self.src, self.src_name = d['source'], d['source_name']
        s = d['settings']
        self.sheets = s.get('sheets')
        if s.get('odd_right') is not None:
            self.odd_right = bool(s['odd_right'])
        self.sops = list(s.get('signals') or [])
        # картинка-исходник – во временный файл, чтобы интерфейс мог её показать
        h = hashlib.sha1(self.src).hexdigest()[:16]
        ext = os.path.splitext(self.src_name)[1] or '.png'
        tmp = os.path.join(tempfile.gettempdir(), 'StationJoints')
        os.makedirs(tmp, exist_ok=True)
        self.src_image = os.path.join(tmp, h + ext)
        if not os.path.exists(self.src_image):
            with open(self.src_image, 'wb') as f:
                f.write(self.src)
        self.path, self.project, self.edited = path, path, d['edited']
        self._build(d['joints'])
        self._reset_history(saved=True)
        return self._with_source()

    def restore(self, path: str, project_path: str | None = None, origin: str | None = None):
        """Открыть автосохранение: схема из path, но «файл работы» – прежний
        (project_path) или ещё не сохранённый (origin – исходная картинка)."""
        res = self._open_project(path)
        self.project = project_path or None
        self.path = project_path or origin or self.src_name
        self.saved = None                    # правки из копии ещё не сохранены в файл
        res['source'] = self._source()
        res['history'] = self._history()
        return res

    def relayout(self, sheets='keep', odd_right: bool | None = None):
        """Перекомпоновать без повторного распознавания (формат листов, направление).
        Ручные правки стыков переносятся по их месту на пути."""
        if self.graph0 is None:
            raise ValueError('схема не загружена')
        ops = self._joint_edits()

        def change():
            self._settings(sheets, odd_right, None)
            self._rebuild_keeping_edits(ops)
            self.edited = bool(ops)
        res = self._edit('перекомпоновка', change)
        res['kept'] = len(ops)
        return res

    def scene_cmd(self, layers: dict | None = None):
        if layers:
            self.layers.update(layers)
        res = self.scene()
        res['history'] = self._history()
        return res

    def recompute(self):
        st = self._need()

        def change():
            place_joints(st)
            snap_joints(st)
            self.sops = []                   # и светофоры – по правилам
            self._refresh()
            prune_signal_joints(st)
            self.edited = False
        return self._edit('расстановка заново', change)

    def add_joint(self, edge: int, t: float):
        st = self._need()
        e = st.g.edges.get(int(edge))
        if e is None:
            raise ValueError('отрезок не найден – схема изменилась')
        L = st.g.length(e)
        j = Joint(e.id, min(max(float(t), 0.5), L - 0.5), 'р', why='добавлен вручную')

        def change():
            update_negab(st, [j])
            st.joints.append(j)
            st.log.append('  [р] стык добавлен вручную')
        return self._joint_edit('добавление стыка', change)

    def remove_joint(self, joint: int):
        st = self._need()
        j = self._joint(joint)

        def change():
            st.joints.remove(j)
            st.log.append(f'  [р] удалён стык ({j.rule})')
        return self._joint_edit('удаление стыка', change)

    def toggle_negab(self, joint: int):
        j = self._joint(joint)

        def change():
            j.negab = not j.negab
            j.fixed = True
        return self._joint_edit('габарит стыка', change)

    def move_joint(self, joint: int, t: float):
        """Перенести стык вдоль его отрезка (t – расстояние от начала отрезка, мм)."""
        st = self._need()
        j = self._joint(joint)
        L = st.g.length(st.g.edges[j.edge])

        def change():
            j.t = min(max(float(t), 0.5), L - 0.5)
            if not j.fixed:
                update_negab(st, [j])
        return self._joint_edit('перенос стыка', change)

    def edit_track(self, op: str, edge: int | None = None, node: int | None = None,
                   mark: str | None = None, a: dict | None = None, b: dict | None = None):
        """Правка распознанной схемы: delete_edge / add_edge / set_end. Схема
        перекомпоновывается, ручные правки стыков переносятся по месту."""
        st = self._need()
        assert self.graph0 is not None
        labels = {'delete_edge': 'удаление отрезка', 'add_edge': 'новый отрезок',
                  'set_end': 'тип конца пути'}
        if op not in labels:
            raise ValueError(f'неизвестная правка: {op}')
        ops = self._joint_edits()

        def change():
            if op == 'delete_edge':
                edits.delete_edge(self.graph0, int(edge or 0))
            elif op == 'add_edge':
                edits.add_edge(self.graph0, st, a or {}, b or {})
            else:
                edits.set_end(self.graph0, int(node or 0), mark)
            self._rebuild_keeping_edits(ops)
            self.edited = True
        try:
            return self._edit(labels[op], change)
        except Exception as ex:
            raise ValueError(f'не получилось: {ex}') from ex

    def _signal_key(self, signal: int) -> dict:
        s = self._signal_obj(signal)
        return edits.sig_key(self._need(), s.joint, s.toward)

    @staticmethod
    def _check_kind(kind: str | None):
        if kind is not None and kind not in KIND_TEXT:
            raise ValueError(f'неизвестный тип светофора: {kind}')

    def edit_signal(self, signal: int, name: str | None = None, kind: str | None = None,
                    delete: bool = False):
        """Переименовать, сменить тип или удалить светофор."""
        self._check_kind(kind)
        key = self._signal_key(signal)
        change = {}
        if name is not None and name.strip():
            change['name'] = name.strip()
        if kind is not None:
            change['kind'] = kind
        if delete:
            change['deleted'] = True
        return self._joint_edit('удаление светофора' if delete else 'правка светофора',
                                lambda: edits.edit_signal(self.sops, key, **change))

    def add_signal(self, joint: int, toward: int, name: str = 'М', kind: str = 'man_dwarf'):
        """Новый светофор у стыка, разрешающий движение в сторону узла toward."""
        self._check_kind(kind)
        st = self._need()
        j = self._joint(joint)
        e = st.g.edges[j.edge]
        if int(toward) not in (e.a, e.b):
            raise ValueError('направление – к одному из концов отрезка')
        key = edits.sig_key(st, j, int(toward))
        return self._joint_edit('новый светофор', lambda: edits.edit_signal(
            self.sops, key, added=True, deleted=False, name=name, kind=kind))

    def reset_signal(self, signal: int):
        """Вернуть светофор к автоматической расстановке."""
        key = self._signal_key(signal)
        return self._joint_edit('светофор – как по правилам', lambda: edits.reset_signal(self.sops, key))

    def explain(self, what: str, target: int | str):
        """Объяснение объекта (target – номер или имя участка; «id» занято протоколом)."""
        st = self._need()
        if what == 'joint':
            self._joint(target)
            return explain.joint(st, int(target))
        if what == 'signal':
            self._signal_obj(target)
            return explain.signal(st, int(target))
        if what == 'section':
            return explain.section(st, str(target))
        if what == 'node':
            if int(target) not in st.g.nodes:
                raise ValueError('узел не найден – схема изменилась')
            return explain.node(st, int(target))
        raise ValueError(f'нечего объяснять: {what}')

    def _preview(self):
        img, _ = render(self._need(), (960, 420), annots=self.annots, show_grid=False)
        return img.convert('RGB')

    def save_project(self, path: str, autosave: bool = False):
        """Сохранить работу. autosave – резервная копия: открытый файл не меняется."""
        st = self._need()
        assert self.graph0 is not None
        if autosave:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        project.save(path, graph=self.graph0, annots=self.annots0, info=self.info,
                     source=self.src, source_name=self.src_name,
                     settings={'sheets': self.sheets, 'odd_right': st.odd_right,
                               'signals': self.sops},
                     joints=st.joints, preview=None if autosave else self._preview(),
                     edited=self.edited)
        if not autosave:
            self.path = self.project = path
            self.saved = self.pos
        return {'source': self._source(), 'history': self._history()}

    def set_project(self, path: str):
        """Файл работы переименован (интерфейсом) – дальше сохранять в path."""
        self._need()
        self.path = self.project = path
        return {'source': self._source()}

    def thumb(self, path: str):
        """Миниатюра схемы для списка недавних."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = self._preview()
        img.thumbnail((480, 210))
        img.save(path)
        return {'path': path}

    def export_png(self, path: str, title: str = ''):
        st = self._need()
        img, _ = render(st, (3200, 1800), annots=self.annots, **layer_flags(self.layers))
        img.save(path)
        return {'path': path}

    def export_pdf(self, path: str, title: str = ''):
        st = self._need()
        L = self.layers
        pages = make_sheets(st, self.annots if L['annots'] else (), show_grid=L['grid'],
                            show_letters=L['letters'], title=title, fmt=self.sheets)
        save_pdf(pages, path)
        return {'path': path, 'pages': len(pages)}

    def export_docx(self, path: str, title: str = ''):
        save_docx(self._need(), path, title)
        return {'path': path}


# команды документа (всё, кроме служебных) – у каждого открытого таба своя сессия
DOC_COMMANDS = {'load': 'load', 'relayout': 'relayout', 'scene': 'scene_cmd',
                'recompute': 'recompute', 'add_joint': 'add_joint',
                'remove_joint': 'remove_joint', 'toggle_negab': 'toggle_negab',
                'undo': 'undo', 'redo': 'redo', 'restore': 'restore',
                'move_joint': 'move_joint', 'edit_track': 'edit_track',
                'edit_signal': 'edit_signal', 'add_signal': 'add_signal',
                'reset_signal': 'reset_signal', 'explain': 'explain',
                'save_project': 'save_project', 'set_project': 'set_project', 'thumb': 'thumb',
                'export_png': 'export_png', 'export_pdf': 'export_pdf', 'export_docx': 'export_docx'}


class Server:
    """Несколько открытых схем (табы): doc -> Session. Без doc – документ 0
    (совместимость с однодокументным клиентом)."""

    def __init__(self):
        self.docs: dict[int, Session] = {}
        self.next = 1

    def handle(self, cmd: str, req: dict):
        if cmd == 'ping':
            return {'version': VERSION}
        if cmd == 'sample':
            return Session().sample()
        if cmd == 'new_doc':
            doc = self.next
            self.next += 1
            self.docs[doc] = Session()
            return {'doc': doc}
        if cmd == 'close_doc':
            self.docs.pop(int(req.get('doc', 0)), None)
            return {'docs': len(self.docs)}
        if cmd not in DOC_COMMANDS:
            raise ValueError(f'неизвестная команда: {cmd}')
        doc = int(req.pop('doc', 0))
        ses = self.docs.setdefault(doc, Session()) if doc == 0 else self.docs.get(doc)
        if ses is None:
            raise ValueError(f'документ {doc} закрыт')
        return getattr(ses, DOC_COMMANDS[cmd])(**req)


def main():
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')            # type: ignore[union-attr]
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')      # type: ignore[union-attr]
    sys.stdout = sys.stderr                          # случайные print – не в протокол
    srv = Server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.pop('id', None)
            cmd = req.pop('cmd', None)
            resp = {'id': rid, 'ok': True, 'result': srv.handle(cmd, req)}
        except Exception as ex:                      # ошибка команды – ответ, не падение
            traceback.print_exc(file=sys.stderr)
            resp = {'id': rid, 'ok': False, 'error': str(ex)}
        out.write(json.dumps(resp, ensure_ascii=False) + '\n')
        out.flush()


if __name__ == '__main__':
    main()
