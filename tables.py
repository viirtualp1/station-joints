"""Табличные сведения о схеме: участки, стрелки, светофоры, стыки.

Общие для вкладки «Участки» (scene.py) и ведомости для пояснительной записки
(vedomost.py). Ординаты – в мм от левого края схемы."""
from __future__ import annotations

import re

from joints import RULE_TEXT, Station, _nm, _numkey

THROAT_ODD, THROAT_EVEN, PARK = 'нечётная горловина', 'чётная горловина', 'пути станции'


def _x0(st: Station) -> float:
    return min(n.x for n in st.g.nodes.values())


def throat_of(st: Station, x: float) -> str:
    return THROAT_ODD if st.odd_side(x) else THROAT_EVEN


def _natural(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r'(\d+)', s)]


def section_rows(st: Station) -> list[dict]:
    """Изолированные участки (кроме перегона): имя, тип, горловина, стрелки, стыки,
    длина на схеме, отрезки для подсветки. Порядок – слева направо по горловинам."""
    g = st.g
    tracks = {f'{v}П' for v in st.track_names.values()}
    entries = {f'{v}П' for v in st.entry_names.values()}
    out = []
    for s in st.sections:
        name = s['name']
        if name == 'перегон':
            continue
        segs, length, joints = [], 0.0, 0
        for p in s['pieces']:
            e = g.edges[p['edge']]
            (ax, ay), (bx, by) = g.point_on(e, p['t0']), g.point_on(e, p['t1'])
            segs.append([ax, ay, bx, by])
            length += p['t1'] - p['t0']
            joints += (p['na'] is None) + (p['nb'] is None)
        xs = [v for sg in segs for v in (sg[0], sg[2])]
        ys = [v for sg in segs for v in (sg[1], sg[3])]
        cx = (min(xs) + max(xs)) / 2
        if s['switches']:
            kind = 'стрелочный'
        elif name in tracks:
            kind = 'путь станции'
        elif name in entries:
            kind = 'за входным светофором'
        elif name == 'п/п':
            kind = 'подъездной путь'
        elif name.endswith('Т') or name == 'тупик':
            kind = 'тупик'
        else:
            kind = 'бесстрелочный'
        out.append({
            'name': name, 'kind': kind,
            'throat': PARK if kind == 'путь станции' else throat_of(st, cx),
            'switches': sorted((_nm(st, n) for n in s['switches']), key=_numkey),
            'joints': joints, 'length': round(length),
            'segs': segs, 'box': [min(xs), min(ys), max(xs), max(ys)],
            'x': cx - _x0(st),
        })
    left = THROAT_EVEN if st.odd_right else THROAT_ODD
    order = {left: 0, PARK: 1}
    out.sort(key=lambda r: (order.get(r['throat'], 2),
                            r['kind'] == 'тупик' or r['kind'] == 'подъездной путь',
                            _numkey(r['switches'][0]) if r['switches'] else 0,
                            _natural(r['name'])))
    for i, r in enumerate(out):
        r['id'] = i
    return out


def switch_rows(st: Station) -> list[dict]:
    g = st.g
    sec_of = {n: s['name'] for s in st.sections for n in s['switches']}
    x0 = _x0(st)
    rows = [{'number': _nm(st, n), 'throat': throat_of(st, g.nodes[n].x),
             'x': round(g.nodes[n].x - x0), 'section': sec_of.get(n, '')} for n in st.sw]
    rows.sort(key=lambda r: (r['throat'] != THROAT_ODD, _numkey(r['number'])))
    return rows


def signal_table(st: Station) -> list[dict]:
    from signals import _pos, signal_rows          # поздний импорт: signals -> joints
    return [{'name': s.name, 'kind': k, 'why': s.why, 'x': round(x),
             'throat': throat_of(st, _pos(st, s.joint)[0])} for s, k, x in signal_rows(st)]


def joint_rows(st: Station) -> list[dict]:
    g = st.g
    x0 = _x0(st)
    rows = []
    for j in st.joints:
        x, _ = g.point_on(g.edges[j.edge], j.t)
        rows.append({'rule': j.rule, 'rule_text': RULE_TEXT.get(j.rule, ''),
                     'negab': j.negab, 'x': round(x - x0), 'why': j.why})
    rows.sort(key=lambda r: (r['x'], r['rule']))
    return rows


def issues(st: Station) -> list[str]:
    """Замечания самопроверки (пустой список – всё по пособию)."""
    from checks import audit                        # поздний импорт: checks -> joints
    out = [f'{what}: {bad}' if bad else what for ok, what, bad in audit(st) if not ok]
    out += [f'нет участка {sig}П между стыками а и в' for sig, ok, _ in st.entry_check if not ok]
    return out
