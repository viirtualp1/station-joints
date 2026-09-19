"""Расстановка светофоров по п. 2.5 пособия.

  Входные  (Н, НД, Ч, ЧД)  – у стыка «а» на главных путях, мачтовые:
             огни Ж–З–К–Ж + лунно-белый пригласительный (прил. 1, «входной мачтовый»).
  Выходные – с каждого пути станции с обоих концов (пути обезличены), у стыка «б».
             Название: Н/Ч по направлению отправления + номер пути (Н1, Ч3, Н6…):
             из чётной горловины отправляются нечётные – Н, из нечётной – Ч.
             С главных путей – мачтовые: Б–К–Ж–З–Ж (от мачты), остальные – карликовые
             в два ряда: К–Б / Ж–З–заглушка. Маневровые с путей совмещены с выходными (а).
  Маневровые (М1, М3… в нечётной горловине, М2, М4… в чётной, номера растут к оси):
     б) с тупиков и подъездных путей – у стыка, ближайшего к стрелке (стык «г»);
        с подъездного пути – мачтовый; запрещающий огонь красный (ограждают путь);
     в) с бесстрелочных участков за входными светофорами – у стыка «в»;
     г) для угловых заездов – перед общей стрелкой стрелочной улицы (у ближайшего
        стыка со стороны остряков её первой стрелки).
Светофор ставится справа по ходу движения, мачта (основание) – в створе со стыком,
огни развёрнуты по ходу движения (как на рис. 2.17–2.18).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from graph import Joint
from joints import Station, _walk_to_switch

# огни: Y – жёлтый, G – зелёный, R – красный, W – лунно-белый, B – синий, X – заглушка
ENTRY = ['Y', 'G', 'R', 'Y']                  # от конца к мачте; W – отдельно на стойке
EXIT_MAIN = ['Y', 'G', 'Y', 'R', 'W']         # от конца к мачте (прил. 1)
EXIT_DWARF = [['R', 'W'], ['Y', 'G', 'X']]    # два ряда, от конца к основанию


@dataclass
class Signal:
    name: str
    kind: str            # entry | exit_mast | exit_dwarf | man_dwarf | man_mast
    joint: Joint
    toward: int          # узел, в сторону которого разрешает движение
    group: str = ''      # буква пункта для маневровых (б, в, г)
    red: bool = False    # маневровый с красным (ограждает путь/тупик) вместо синего
    why: str = ''


def place_signals(st: Station):
    g = st.g
    sigs: list[Signal] = []
    used = set()                          # (id стыка, направление)

    def add(j, toward, **kw):
        key = (id(j), toward)
        if key in used:
            return
        used.add(key)
        sigs.append(Signal(joint=j, toward=toward, **kw))

    by_rule = {}
    for j in st.joints:
        by_rule.setdefault(j.rule, []).append(j)

    # входные – у стыка «а»
    for l in st.mains:
        for end in (l['nodes'][0], l['nodes'][-1]):
            if g.nodes[end].mark != 'peregon':
                continue
            path, cur = _walk_to_switch(st, end)
            first = path[0]
            ja = [j for j in by_rule.get('а', []) if j.edge == first.id]
            if not ja:
                continue
            j = min(ja, key=lambda j: j.t if first.a == end else g.length(first) - j.t)
            add(j, g.other(first, end), name=st.entry_names.get(end, 'Вх'), kind='entry',
                why='входной (у стыка а)')

    # выходные – у стыков «б» путей станции, по направлению к горловине
    mains = {id(l) for l in st.mains}
    for l in st.lines:
        if 'name' not in l or l.get('central') not in g.edges:
            continue
        e = g.edges[l['central']]
        num = {'I': '1', 'II': '2'}.get(l['name'], l['name'])
        for n in (e.a, e.b):
            jb = [j for j in by_rule.get('б', []) if j.edge == e.id
                  and isinstance(j.anchor, tuple) and j.anchor[0] == n]
            if not jb:
                continue
            letter = 'Ч' if st.odd_side(g.nodes[n].x) else 'Н'
            add(jb[0], n, name=f'{letter}{num}',
                kind='exit_mast' if id(l) in mains else 'exit_dwarf',
                why=f'выходной с пути {l["name"]}П')

    # маневровые б) – с тупиков и подъездных путей, у стыка «г» (ближайшего к стрелке)
    for j in by_rule.get('г', []):
        if not (isinstance(j.anchor, tuple) and j.anchor[0] in g.nodes):
            continue                      # к стрелке (или к излому перед ней)
        cur = j.anchor[0]
        e = g.edges[j.edge]
        far = g.other(e, cur)
        pp = _leads_to(st, far, cur, 'pp')
        add(j, cur, name='', kind='man_mast' if pp else 'man_dwarf', group='б', red=True,
            why='маневровый с подъездного пути' if pp else 'маневровый из тупика')

    # маневровые в) – с бесстрелочных участков за входными светофорами, у стыка «в»
    for j in by_rule.get('в', []):
        if isinstance(j.anchor, tuple) and j.anchor[0] in st.sw:
            add(j, j.anchor[0], name='', kind='man_dwarf', group='в',
                why='маневровый с участка за входным светофором')

    # маневровые г) – для угловых заездов: перед общей стрелкой стрелочной улицы
    for c in st.ladders:
        sws = c['switches']
        # первая стрелка улицы – та, что стоит на главном/приёмо-отправочном пути
        s = max(sws, key=lambda n: abs(g.nodes[n].x - st.xc))
        trunk = g.edges[st.sw[s]['trunk']]
        js = [j for j in st.joints if j.edge == trunk.id]
        if not js:
            continue
        j = min(js, key=lambda j: j.t if trunk.a == s else g.length(trunk) - j.t)
        add(j, s, name='', kind='man_dwarf', group='г',
            why=f'маневровый для угловых заездов на стрелочную улицу (стрелка {g.nodes[s].number})')

    # наложения: маневровые для угловых заездов (г) – самые необязательные;
    # если такой светофор налезает на уже стоящий – не ставим его
    prio = {'entry': 0, 'exit_mast': 1, 'exit_dwarf': 1, 'man_mast': 2, 'man_dwarf': 2}
    order = sorted(sigs, key=lambda s: (prio[s.kind], s.group == 'г'))
    kept, boxes = [], []
    for s in order:
        b = footprint(st, s)
        if s.group == 'г' and any(_overlap(b, o) for o in boxes):
            continue
        kept.append(s)
        boxes.append(b)
    sigs = [s for s in sigs if s in kept]

    # нумерация маневровых: нечётная горловина – М1, М3…, чётная – М2, М4…,
    # номера возрастают по мере приближения к оси станции
    man = [s for s in sigs if s.kind.startswith('man')]
    for odd in (True, False):
        side = [s for s in man if st.odd_side(_pos(st, s.joint)[0]) == odd]
        side.sort(key=lambda s: -abs(_pos(st, s.joint)[0] - st.xc))
        num = 1 if odd else 2
        for s in side:
            s.name = f'М{num}'
            num += 2
    st.signals = sigs
    return sigs


def _leads_to(st, node, came_from, mark):
    """Упирается ли путь от node (не возвращаясь к came_from) в конец с отметкой mark."""
    g = st.g
    prev, cur = came_from, node
    for _ in range(50):
        if g.degree(cur) == 1:
            return g.nodes[cur].mark == mark
        if g.degree(cur) != 2:
            return False
        nxt = [g.other(e, cur) for e in g.incident(cur) if g.other(e, cur) != prev][0]
        prev, cur = cur, nxt
    return False


def _pos(st, j):
    return st.g.point_on(st.g.edges[j.edge], j.t)


def geometry(st: Station, s: Signal):
    """Точка стыка, направление движения (ед. вектор) и нормаль «вправо по ходу»."""
    g = st.g
    x, y = _pos(st, s.joint)
    tx, ty = g.pos(s.toward)
    dx, dy = tx - x, ty - y
    L = math.hypot(dx, dy) or 1
    dx, dy = dx / L, dy / L
    # экран: y вниз; правая сторона для идущего по (dx, dy) – (−dy, dx)
    return (x, y), (dx, dy), (-dy, dx)


def offset(s: Signal) -> float:
    """Ось светофора от оси пути; у негабаритного стыка – за его кружком (Ø6)."""
    from joints import SIG_D, SIG_OFF
    return SIG_OFF + (1.9 if s.joint.negab else 0.0)


def footprint(st: Station, s: Signal):
    """Габарит обозначения светофора (x0, y0, x1, y1) в мм, с подписью."""
    from joints import SIG_H, SIG_LEN, SIG_OFF
    (x, y), (dx, dy), (nx, ny) = geometry(st, s)
    extra = offset(s) - SIG_OFF
    L = SIG_LEN[s.kind] + 0.3
    back = 1.2 + 1.6 * len(s.name or 'М00')          # подпись позади основания
    h0, h1 = extra + 1.0, extra + SIG_H[s.kind]
    pts = [(x + dx * a + nx * c, y + dy * a + ny * c) for a in (-back, L) for c in (h0, h1)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


KIND_TEXT = {'entry': 'входной мачтовый', 'exit_mast': 'выходной мачтовый',
             'exit_dwarf': 'выходной карликовый', 'man_dwarf': 'маневровый карликовый',
             'man_mast': 'маневровый мачтовый'}


def signal_rows(st: Station) -> list[tuple[Signal, str, float]]:
    """(светофор, тип текстом, ордината от левого края в мм) – по возрастанию ординаты."""
    g = st.g
    x0 = min(n.x for n in g.nodes.values())
    rows = []
    for s in sorted(st.signals, key=lambda s: _pos(st, s.joint)[0]):
        kind = KIND_TEXT[s.kind] + (f' ({s.group})' if s.group else '')
        rows.append((s, kind, _pos(st, s.joint)[0] - x0))
    return rows


def report_signals(st: Station) -> list[str]:
    return [f'  {s.name:<5} {k}, ордината {x:.0f} мм – {s.why}' for s, k, x in signal_rows(st)]
