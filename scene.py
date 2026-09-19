"""Схема станции как JSON-сцена для клиента (Flutter): векторные примитивы в мм
плюс объекты для взаимодействия (стыки, пути, светофоры) и отчёт.

Чертёж рисует render.py в режиме записи – размеры обозначений (прил. 1) остаются
в одном месте, клиент только отображает примитивы."""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from joints import RULE_TEXT, Station, report
from render import REC_PX, Recorder, render
from signals import footprint, signal_rows

LAYERS = dict(joints=True, signals=True, numbers=True, letters=False, sections=False,
              section_names=False, annots=True, grid=True)


def _annot_png(a) -> str:
    """Надпись с картинки (п/п, номер варианта) – PNG с прозрачностью, base64."""
    m = np.asarray(a.mask, bool)
    rgba = np.zeros(m.shape + (4,), np.uint8)
    rgba[..., :3] = 60
    rgba[..., 3] = m.astype(np.uint8) * 255
    buf = io.BytesIO()
    Image.fromarray(rgba, 'RGBA').save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


def build_scene(st: Station, annots=(), layers: dict | None = None) -> dict:
    lay = {**LAYERS, **(layers or {})}
    g = st.g
    rec = Recorder(REC_PX)
    render(st, (1, 1), record=rec, show_joints=lay['joints'], show_signals=lay['signals'],
           show_numbers=lay['numbers'], show_letters=lay['letters'],
           show_sections=lay['sections'], show_section_names=lay['section_names'])

    x0, y0, x1, y1 = g.bbox()
    for s in st.signals:
        b = footprint(st, s)
        x0, y0, x1, y1 = min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])
    ann = []
    if lay['annots']:
        for a in annots:
            ann.append({'x0': a.x0, 'y0': a.y0, 'x1': a.x1, 'y1': a.y1, 'png': _annot_png(a)})
            x0, y0, x1, y1 = min(x0, a.x0), min(y0, a.y0), max(x1, a.x1), max(y1, a.y1)

    joints = []
    for i, j in enumerate(st.joints):
        jx, jy = g.point_on(g.edges[j.edge], j.t)
        joints.append({'id': i, 'x': jx, 'y': jy, 'rule': j.rule, 'negab': j.negab,
                       'text': RULE_TEXT.get(j.rule, '')})
    edges = [{'id': e.id, 'x0': g.nodes[e.a].x, 'y0': g.nodes[e.a].y,
              'x1': g.nodes[e.b].x, 'y1': g.nodes[e.b].y} for e in g.edges.values()]
    index = {id(s): i for i, s in enumerate(st.signals)}
    signals = []
    for s, kind, x in signal_rows(st):
        signals.append({'id': index[id(s)], 'name': s.name, 'kind': kind, 'why': s.why,
                        'ordinate': round(x), 'box': list(footprint(st, s))})
    return {
        'bounds': [x0 - 8, y0 - 8, x1 + 8, y1 + 8],
        'origin_x': min(n.x for n in g.nodes.values()),
        'sheet_cut': st.sheet_cut,
        'items': rec.items,
        'annots': ann,
        'joints': joints,
        'edges': edges,
        'signals': signals,
        'layers': lay,
        'report': report(st),
    }
