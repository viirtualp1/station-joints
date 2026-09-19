"""Бэкенд для Flutter-клиента: команды и ответы – JSON по строке через stdin/stdout.

Запрос:  {"id": 1, "cmd": "load", "path": "...", "sheets": "A3"}
Ответ:   {"id": 1, "ok": true, "result": {...}}  |  {"id": 1, "ok": false, "error": "..."}

Команды: ping, sample, load, scene, recompute, add_joint, remove_joint, toggle_negab,
         export_png, export_pdf, export_report.
Команды, меняющие схему, возвращают новую сцену (см. scene.py)."""
from __future__ import annotations

import json
import os
import sys
import traceback

from graph import Joint
from joints import (RULE_TEXT, Station, check_entries, compute_sections, name_sections,
                    place_joints, report, update_negab)
from layout import build_station, snap_joints
from parser import parse_image
from render import render
from scene import LAYERS, build_scene
from sheets import make_sheets, save_pdf
from signals import place_signals

VERSION = 1


def resource(name: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Session:
    def __init__(self):
        self.st: Station | None = None
        self.annots: list = []
        self.path: str | None = None
        self.sheets: str | None = 'A3'
        self.layers = dict(LAYERS)

    def _need(self) -> Station:
        if self.st is None:
            raise ValueError('схема не загружена')
        return self.st

    def scene(self):
        return build_scene(self._need(), self.annots, self.layers)

    def _after_edit(self):
        st = self._need()
        st.sections = compute_sections(st)
        name_sections(st)
        check_entries(st)
        place_signals(st)                    # светофоры стоят на стыках – пересчитать
        return self.scene()

    # --- команды -----------------------------------------------------------------
    def ping(self):
        return {'version': VERSION}

    def sample(self):
        return {'path': resource(os.path.join('samples', 'var96_photo.jpg'))}

    def load(self, path: str | None = None, sheets='keep', layers: dict | None = None):
        """Распознать картинку и построить схему. sheets: 'A4'|'A3'|'A2'|None|'keep'."""
        path = path or self.path
        if not path:
            raise ValueError('не указан файл')
        if sheets != 'keep':
            self.sheets = sheets or None
        if layers:
            self.layers.update(layers)
        parsed = parse_image(path)
        self.st, self.annots = build_station(parsed['graph'], parsed['annots'],
                                             sheet_fmt=self.sheets)
        self.path = path
        res = self.scene()
        res['source'] = {'path': path, 'name': os.path.basename(path),
                         'angle': parsed['info']['angle'], 'sheets': self.sheets}
        return res

    def scene_cmd(self, layers: dict | None = None):
        if layers:
            self.layers.update(layers)
        return self.scene()

    def recompute(self):
        st = self._need()
        place_joints(st)
        snap_joints(st)
        place_signals(st)
        return self.scene()

    def add_joint(self, edge: int, t: float):
        st = self._need()
        j = Joint(int(edge), float(t), 'р')
        update_negab(st, [j])
        st.joints.append(j)
        st.log.append('  [р] стык добавлен вручную')
        return self._after_edit()

    def remove_joint(self, joint: int):
        st = self._need()
        j = st.joints.pop(int(joint))
        st.log.append(f'  [р] удалён стык ({j.rule})')
        return self._after_edit()

    def toggle_negab(self, joint: int):
        st = self._need()
        j = st.joints[int(joint)]
        j.negab = not j.negab
        j.fixed = True
        return self._after_edit()

    def export_png(self, path: str):
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

    def export_report(self, path: str):
        st = self._need()
        legend = '\n'.join(f'  {k}) {v}' for k, v in RULE_TEXT.items())
        with open(path, 'w', encoding='utf-8') as f:
            f.write(report(st) + '\n\nПравила (п. 2.4 пособия):\n' + legend)
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
                'scene': ses.scene_cmd, 'recompute': ses.recompute,
                'add_joint': ses.add_joint, 'remove_joint': ses.remove_joint,
                'toggle_negab': ses.toggle_negab, 'export_png': ses.export_png,
                'export_pdf': ses.export_pdf, 'export_report': ses.export_report}
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
