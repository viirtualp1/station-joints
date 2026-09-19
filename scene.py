"""Схема станции как JSON-сцена для клиента (Flutter): векторные примитивы в мм
плюс объекты для взаимодействия (стыки, пути, светофоры, участки) и замечания самопроверки.

Чертёж рисует render.py в режиме записи – размеры обозначений (прил. 1) остаются
в одном месте, клиент только отображает примитивы."""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from joints import RULE_TEXT, Station
from render import REC_PX, Recorder, render
from signals import footprint, signal_rows
from edits import chain
from tables import issues, section_rows

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
                       'text': RULE_TEXT.get(j.rule, ''), 'edge': j.edge, 't': j.t})
    chain_of = {}                               # ребро -> отрезок «от стрелки до стрелки»
    for e in g.edges.values():
        if e.id not in chain_of:
            ids = chain(g, e.id)
            for i in ids:
                chain_of[i] = ids[0]
    edges = [{'id': e.id, 'x0': g.nodes[e.a].x, 'y0': g.nodes[e.a].y,
              'x1': g.nodes[e.b].x, 'y1': g.nodes[e.b].y, 'a': e.a, 'b': e.b,
              'chain': chain_of[e.id]} for e in g.edges.values()]
    index = {id(s): i for i, s in enumerate(st.signals)}
    jindex = {id(j): i for i, j in enumerate(st.joints)}
    signals = []
    for s, kind, x in signal_rows(st):
        signals.append({'id': index[id(s)], 'name': s.name, 'kind': kind, 'why': s.why,
                        'ordinate': round(x), 'box': list(footprint(st, s)),
                        'code': s.kind, 'manual': s.manual, 'joint': jindex.get(id(s.joint), -1),
                        'toward': s.toward})
    # узлы: стрелки и концы путей (правка путей, «Объясни»)
    nodes = []
    for n in g.nodes.values():
        deg = g.degree(n.id)
        if deg == 2:
            continue
        nodes.append({'id': n.id, 'x': n.x, 'y': n.y, 'switch': n.id in st.sw,
                      'end': deg == 1, 'mark': n.mark, 'label': n.label or n.number or '',
                      'manual': n.fixed_mark})
    return {
        'bounds': [x0 - 8, y0 - 8, x1 + 8, y1 + 8],
        'origin_x': min(n.x for n in g.nodes.values()),
        'sheet_cut': st.sheet_cut,
        'items': rec.items,
        'annots': ann,
        'joints': joints,
        'edges': edges,
        'signals': signals,
        'nodes': nodes,
        'layers': lay,
        'sections': section_rows(st),
        'issues': issues(st),
        'odd_right': st.odd_right,
    }
