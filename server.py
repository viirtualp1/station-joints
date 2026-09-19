"""Бэкенд для Flutter-клиента: команды и ответы – JSON по строке через stdin/stdout.

Запрос:  {"id": 1, "cmd": "load", "path": "...", "sheets": "A3"}
Ответ:   {"id": 1, "ok": true, "result": {...}}  |  {"id": 1, "ok": false, "error": "..."}

Команды: ping, sample, load, restore, relayout, scene, recompute, add_joint, remove_joint,
         toggle_negab, undo, redo, save_project, thumb, export_png, export_pdf, export_docx.
Команды, меняющие схему, возвращают новую сцену (см. scene.py)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import traceback

import project
from graph import Graph, Joint
from joints import (Station, check_entries, compute_sections, name_sections, place_joints,
                    update_negab)
from layout import build_station, snap_joints
from parser import parse_image
from render import render
from scene import LAYERS, build_scene
from sheets import make_sheets, save_pdf
from signals import place_signals
from vedomost import save_docx

VERSION = 3
HISTORY = 100                            # шагов отмены


def resource(name: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Session:
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
        # история для отмены/повтора: снимки стыков и настроек компоновки
        self.hist: list[dict] = []
        self.pos = 0

    def _need(self) -> Station:
        if self.st is None:
            raise ValueError('схема не загружена')
        return self.st

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
        return {'label': label, 'sheets': self.sheets, 'odd_right': st.odd_right,
                'edited': self.edited, 'joints': project.joints_to_json(st.joints)}

    def _reset_history(self):
        self.hist, self.pos = [self._snap('')], 0

    def _commit(self, label: str):
        del self.hist[self.pos + 1:]
        self.hist.append(self._snap(label))
        if len(self.hist) > HISTORY:
            del self.hist[0]
        self.pos = len(self.hist) - 1

    def _history(self):
        return {'undo': self.hist[self.pos]['label'] if self.pos > 0 else None,
                'redo': self.hist[self.pos + 1]['label'] if self.pos + 1 < len(self.hist) else None}

    def _restore(self, snap: dict):
        self.sheets, self.odd_right, self.edited = snap['sheets'], snap['odd_right'], snap['edited']
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

    def _settings(self, sheets, odd_right, layers):
        if sheets != 'keep':
            self.sheets = sheets or None
        if odd_right is not None:
            self.odd_right = bool(odd_right)
        if layers:
            self.layers.update(layers)

    def _build(self, joints: list | None = None):
        """Компоновка из распознанного графа; joints – сохранённые стыки (из файла работы)."""
        self.st, self.annots = build_station(copy.deepcopy(self.graph0), copy.deepcopy(self.annots0),
                                             sheet_fmt=self.sheets, odd_right=self.odd_right)
        if joints and all(j.edge in self.st.g.edges for j in joints):
            self.st.joints = joints
            self._refresh()

    def _refresh(self):
        st = self._need()
        st.sections = compute_sections(st)
        name_sections(st)
        check_entries(st)
        place_signals(st)                    # светофоры стоят на стыках – пересчитать

    def _after_edit(self, label: str):
        self.edited = True
        self._refresh()
        self._commit(label)
        return self._with_source()

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
        self._build()
        self._reset_history()
        return self._with_source()

    def _open_project(self, path: str):
        d = project.load(path)
        self.graph0, self.annots0, self.info = d['graph'], d['annots'], d['info']
        self.src, self.src_name = d['source'], d['source_name']
        s = d['settings']
        self.sheets = s.get('sheets')
        if s.get('odd_right') is not None:
            self.odd_right = bool(s['odd_right'])
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
        self._reset_history()
        return self._with_source()

    def restore(self, path: str, project_path: str | None = None, origin: str | None = None):
        """Открыть автосохранение: схема из path, но «файл работы» – прежний
        (project_path) или ещё не сохранённый (origin – исходная картинка)."""
        res = self._open_project(path)
        self.project = project_path or None
        self.path = project_path or origin or self.src_name
        res['source'] = self._source()
        return res

    def relayout(self, sheets='keep', odd_right: bool | None = None):
        """Перекомпоновать без повторного распознавания (формат листов, направление).
        Стыки расставляются по правилам заново – ручные правки сбрасываются."""
        if self.graph0 is None:
            raise ValueError('схема не загружена')
        self._settings(sheets, odd_right, None)
        self.edited = False
        self._build()
        self._commit('перекомпоновка')
        return self._with_source()

    def scene_cmd(self, layers: dict | None = None):
        if layers:
            self.layers.update(layers)
        res = self.scene()
        res['history'] = self._history()
        return res

    def recompute(self):
        st = self._need()
        place_joints(st)
        snap_joints(st)
        place_signals(st)
        self.edited = False
        self._commit('расстановка заново')
        return self._with_source()

    def add_joint(self, edge: int, t: float):
        st = self._need()
        j = Joint(int(edge), float(t), 'р', why='добавлен вручную')
        update_negab(st, [j])
        st.joints.append(j)
        st.log.append('  [р] стык добавлен вручную')
        return self._after_edit('добавление стыка')

    def remove_joint(self, joint: int):
        st = self._need()
        j = st.joints.pop(int(joint))
        st.log.append(f'  [р] удалён стык ({j.rule})')
        return self._after_edit('удаление стыка')

    def toggle_negab(self, joint: int):
        st = self._need()
        j = st.joints[int(joint)]
        j.negab = not j.negab
        j.fixed = True
        return self._after_edit('габарит стыка')

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
                     settings={'sheets': self.sheets, 'odd_right': st.odd_right},
                     joints=st.joints, preview=None if autosave else self._preview(),
                     edited=self.edited)
        if not autosave:
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
        L = self.layers
        img, _ = render(st, (3200, 1800), annots=self.annots if L['annots'] else (),
                        show_grid=L['grid'], show_joints=L['joints'], show_signals=L['signals'],
                        show_numbers=L['numbers'], show_letters=L['letters'],
                        show_sections=L['sections'], show_section_names=L['section_names'])
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


def main():
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')            # type: ignore[union-attr]
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')      # type: ignore[union-attr]
    sys.stdout = sys.stderr                          # случайные print – не в протокол
    ses = Session()
    handlers = {'ping': ses.ping, 'sample': ses.sample, 'load': ses.load,
                'relayout': ses.relayout, 'scene': ses.scene_cmd, 'recompute': ses.recompute,
                'add_joint': ses.add_joint, 'remove_joint': ses.remove_joint,
                'toggle_negab': ses.toggle_negab, 'undo': ses.undo, 'redo': ses.redo,
                'restore': ses.restore, 'save_project': ses.save_project,
                'thumb': ses.thumb, 'export_png': ses.export_png,
                'export_pdf': ses.export_pdf, 'export_docx': ses.export_docx}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.pop('id', None)
            cmd = req.pop('cmd', None)
            if cmd not in handlers:
                raise ValueError(f'неизвестная команда: {cmd}')
            resp = {'id': rid, 'ok': True, 'result': handlers[cmd](**req)}
        except Exception as ex:                      # ошибка команды – ответ, не падение
            traceback.print_exc(file=sys.stderr)
            resp = {'id': rid, 'ok': False, 'error': str(ex)}
        out.write(json.dumps(resp, ensure_ascii=False) + '\n')
        out.flush()


if __name__ == '__main__':
    main()
