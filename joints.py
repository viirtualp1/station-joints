"""Расстановка изолирующих стыков по методическому пособию ДВГУПС
«Проектирование схематического плана станции…» (Епифанова, Пельменёва, 2017), п. 2.4.

Правила (буквы – как в пособии, рис. 2.7):
  а) стыками отделяется станция от перегона;
  б) в отдельные участки выделяются главные и приёмо-отправочные пути;
  в) выделяются бесстрелочные участки за входными светофорами;
  г) от зоны централизации отделяются тупики, подъездные пути;
  д) на входе с подъездного пути – короткая рельсовая цепь (25 м);
  е) каждая стрелка стрелочной улицы – в отдельной рельсовой цепи (негабаритные стыки);
  ж) стрелки, по которым возможны параллельные передвижения, – в разных участках
     (стык между стрелками съезда; между параллельными съездами – негабаритный);
  и) в стрелочном участке не более трёх стрелок.
Плюс нумерация стрелок (п. 2.3) и наименование участков (п. 2.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from graph import Graph, Joint

RULE_TEXT = {
    'а': 'отделение станции от перегона',
    'б': 'выделение главного / приёмо-отправочного пути',
    'в': 'бесстрелочный участок за входным светофором',
    'г': 'отделение тупика / подъездного пути',
    'д': 'короткая РЦ 25 м на входе с подъездного пути',
    'е': 'стрелка стрелочной улицы в отдельной РЦ',
    'ж': 'стрелки с параллельными передвижениями – в разные участки',
    'з': 'стрелка в предохранительный тупик – отдельный участок',
    'и': 'не более 3 стрелок в участке',
    'р': 'добавлен вручную',
}


@dataclass
class Station:
    g: Graph
    u: float = 60.0                       # «междупутье» в пикселях
    xc: float = 0.0                       # ось станции
    lines: list = field(default_factory=list)       # горизонтальные пути
    mains: list = field(default_factory=list)
    track_names: dict = field(default_factory=dict)  # edge id центральной части -> имя
    entry_names: dict = field(default_factory=dict)  # end node -> 'Н', 'ЧД'…
    sw: dict = field(default_factory=dict)          # switch -> {trunk, straight, branch}
    chains: list = field(default_factory=list)      # диагональные цепочки
    ladders: list = field(default_factory=list)
    crossovers: list = field(default_factory=list)
    joints: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    log: list = field(default_factory=list)
    entry_check: list = field(default_factory=list)  # (сигнал, ok, первая стрелка)


# --------------------------------------------------------------------------
def _ang(g, e, n):
    dx, dy = g.direction(e, n)
    return math.atan2(dy, dx)


def _dev_straight(g, e1, e2, n):
    """Отклонение пары рёбер от прямой (0 – продолжают друг друга)."""
    d = abs((_ang(g, e1, n) - _ang(g, e2, n)) % (2 * math.pi) - math.pi)
    return d


def analyse(g: Graph) -> Station:
    st = Station(g)
    _classify_ends(st)
    _build_lines(st)
    _switch_geometry(st)
    _chains(st)
    _find_center(st)
    _find_mains(st)
    _extend_entries(st)
    _name_tracks(st)
    _number_switches(st)
    _number_tupiks(st)
    return st


def _number_tupiks(st: Station):
    """П. 2.2: тупики в нечётной горловине – нечётные номера, в чётной – чётные,
    с буквой Т (1Т, 3Т… слева; 2Т, 4Т… справа); по порядку от края станции, сверху вниз."""
    g = st.g
    x0, _, x1, _ = g.bbox()
    ends = [n for n in g.nodes.values() if g.degree(n.id) == 1 and n.mark == 'tupik']
    throat = {}                              # горловина – по стрелке, к которой примыкает тупик
    for n in ends:
        _, cur = _walk_to_switch(st, n.id)
        num = g.nodes[cur].number if cur else None
        throat[n.id] = (int(num) % 2 == 1) if num else (n.x < st.xc)
    for left in (True, False):
        side = [n for n in ends if throat[n.id] == left]
        side.sort(key=lambda n: (round((n.x - x0) if left else (x1 - n.x)), n.y))
        num = 1 if left else 2
        for n in side:
            n.label = f'{num}Т'
            num += 2


def _classify_ends(st: Station):
    g = st.g
    x0, _, x1, _ = g.bbox()
    span = x1 - x0
    for n in g.nodes.values():
        if g.degree(n.id) != 1 or n.mark in ('tupik', 'pp'):
            continue
        e = g.incident(n.id)[0]
        at_edge = n.x - x0 < span * 0.04 or x1 - n.x < span * 0.04
        n.mark = 'peregon' if at_edge and g.is_horizontal(e) else 'tupik'


def _build_lines(st: Station):
    """Горизонтальные пути = цепочки коллинеарных горизонтальных рёбер."""
    g = st.g
    hedges = {e.id for e in g.edges.values() if g.is_horizontal(e, 4)}
    seen = set()
    lines = []
    for eid in hedges:
        if eid in seen:
            continue
        comp, stack = [], [eid]
        while stack:
            k = stack.pop()
            if k in seen:
                continue
            seen.add(k)
            comp.append(k)
            e = g.edges[k]
            for n in (e.a, e.b):
                for f in g.incident(n):
                    if f.id in hedges and f.id not in seen and \
                            abs(g.nodes[f.a].y - g.nodes[e.a].y) < 2:
                        stack.append(f.id)
        nodes = set()
        for k in comp:
            nodes |= {g.edges[k].a, g.edges[k].b}
        nodes = sorted(nodes, key=lambda n: g.nodes[n].x)
        lines.append(dict(edges=comp, nodes=nodes, y=g.nodes[nodes[0]].y,
                          x0=g.nodes[nodes[0]].x, x1=g.nodes[nodes[-1]].x))
    st.lines = lines
    ys = sorted({round(l['y']) for l in lines})
    gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 5]
    st.u = sorted(gaps)[len(gaps) // 2] if gaps else 60.0


def _switch_geometry(st: Station):
    g = st.g
    for s in g.switches():
        inc = g.incident(s)
        best = None
        for i in range(3):
            for j in range(i + 1, 3):
                d = _dev_straight(g, inc[i], inc[j], s)
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        b = inc[3 - i - j]
        e1, e2 = inc[i], inc[j]
        # ветвь «отходит» от того прямого ребра, с которым образует острый угол
        a1 = _dev_straight(g, e1, b, s)
        a2 = _dev_straight(g, e2, b, s)
        straight, trunk = (e1, e2) if a1 > a2 else (e2, e1)
        bx, by = g.direction(b, s)
        st.sw[s] = dict(trunk=trunk.id, straight=straight.id, branch=b.id,
                        bdx=bx, bdy=by)


def _chains(st: Station):
    """Цепочки коллинеарных негоризонтальных рёбер (съезды, стрелочные улицы)."""
    g = st.g
    diag = {e.id for e in g.edges.values() if not g.is_horizontal(e, 4)}
    seen = set()
    for eid in diag:
        if eid in seen:
            continue
        chain = [eid]
        seen.add(eid)
        # расширяем в обе стороны через узлы, где диагональ идёт прямо
        for side in (0, 1):
            cur = eid
            node = g.edges[eid].a if side == 0 else g.edges[eid].b
            while True:
                nxt = None
                for f in g.incident(node):
                    if f.id != cur and f.id in diag and f.id not in seen and \
                            _dev_straight(g, g.edges[cur], f, node) < math.radians(14):
                        nxt = f
                if nxt is None:
                    break
                seen.add(nxt.id)
                if side == 0:
                    chain.insert(0, nxt.id)
                else:
                    chain.append(nxt.id)
                cur = nxt.id
                node = g.other(nxt, node)
        # упорядоченный список узлов цепочки
        if len(chain) == 1:
            e = g.edges[chain[0]]
            nodes = [e.a, e.b]
        else:
            e0, e1 = g.edges[chain[0]], g.edges[chain[1]]
            start = e0.a if e0.a not in (e1.a, e1.b) else e0.b
            nodes = [start]
            for k in chain:
                nodes.append(g.other(g.edges[k], nodes[-1]))
        sws = [n for n in nodes if n in st.sw]
        c = dict(edges=chain, nodes=nodes, switches=sws)
        st.chains.append(c)
        if len(sws) >= 3:
            st.ladders.append(c)
        elif len(sws) == 2 and sws == [nodes[0], nodes[-1]] and \
                all(st.sw[s]['branch'] in chain for s in sws):
            st.crossovers.append(c)


def _find_center(st: Station):
    g = st.g
    bx0, _, bx1, _ = g.bbox()
    longl = [l for l in st.lines if l['x1'] - l['x0'] > (bx1 - bx0) * 0.25]
    xs = sorted({round(n.x) for n in g.nodes.values()})
    best, bx = -1, []
    for x0, x1 in zip(xs, xs[1:]):
        xm = (x0 + x1) / 2
        cnt = sum(1 for l in longl if l['x0'] < xm < l['x1'])
        if cnt > best:
            best, bx = cnt, [(x0, x1)]
        elif cnt == best:
            bx.append((x0, x1))
    # берём самый длинный интервал с максимальным числом параллельных путей
    x0, x1 = max(bx, key=lambda p: p[1] - p[0])
    st.xc = (x0 + x1) / 2


def _find_mains(st: Station):
    g = st.g
    mains = []
    for l in st.lines:
        ends = [n for n in (l['nodes'][0], l['nodes'][-1]) if g.nodes[n].mark == 'peregon']
        if len(ends) == 2:
            mains.append(l)
    if not mains:   # запасной вариант – два самых длинных пути
        mains = sorted(st.lines, key=lambda l: l['x1'] - l['x0'])[-2:]
    mains.sort(key=lambda l: l['y'])
    st.mains = mains[-2:]


ENTRY_LEN = 2.6     # мин. длина главного пути от края схемы до первой стрелки, в междупутьях


def _extend_entries(st: Station):
    """На схемах заданий главные пути часто обрываются почти у первой стрелки –
    тогда между входным стыком (а) и стыком у стрелки (в) не остаётся места.
    Продлеваем главные пути в сторону перегона, чтобы участок НП/ЧП поместился."""
    g, u = st.g, st.u
    for left in (True, False):
        ends, firsts = [], []
        for l in st.mains:
            end = l['nodes'][0] if left else l['nodes'][-1]
            sws = [n for n in l['nodes'] if n in st.sw]
            if g.nodes[end].mark != 'peregon' or not sws:
                continue
            ends.append(end)
            firsts.append(g.nodes[sws[0] if left else sws[-1]].x)
        if not ends:
            continue
        if left:
            x = min(min(firsts) - ENTRY_LEN * u, min(g.nodes[e].x for e in ends))
        else:
            x = max(max(firsts) + ENTRY_LEN * u, max(g.nodes[e].x for e in ends))
        for e in ends:
            g.nodes[e].x = x
    for l in st.lines:
        l['x0'] = min(g.nodes[n].x for n in l['nodes'])
        l['x1'] = max(g.nodes[n].x for n in l['nodes'])


def _central_edge(st: Station, line):
    """Средняя часть пути станции: отрезок, пересекающий ось станции, а если
    ось его не пересекает (после раздвижки) – самый длинный отрезок между
    стрелками/изломами этого пути."""
    g = st.g
    # путь станции: средняя часть запомнена при анализе исходной картинки
    # (там ось станции надёжна); компоновка топологию не меняет – ребро то же
    if line.get('central') in g.edges:
        return g.edges[line['central']]
    for k in line['edges']:
        e = g.edges[k]
        xa, xb = sorted((g.nodes[e.a].x, g.nodes[e.b].x))
        if xa <= st.xc <= xb:
            return e
    return None


def _name_tracks(st: Station):
    """Главные: нижний – I, верхний – II (как на рис. 2.1–2.7 пособия);
    над II – чётные 4, 6…, под I – нечётные 3, 5…"""
    g = st.g
    crossing = [l for l in st.lines if l['x0'] < st.xc < l['x1']]
    if len(st.mains) == 2:
        up, lo = st.mains
        names = {id(lo): 'I', id(up): 'II'}
    elif st.mains:
        up = lo = st.mains[0]
        names = {id(lo): 'I'}
    else:
        return
    ev, od = 4, 3
    for l in sorted([l for l in crossing if l['y'] < up['y']], key=lambda l: -l['y']):
        names[id(l)] = str(ev); ev += 2
    for l in sorted([l for l in crossing if l['y'] > lo['y']], key=lambda l: l['y']):
        names[id(l)] = str(od); od += 2
    for l in crossing:
        if id(l) in names:
            e = _central_edge(st, l)
            if e:
                st.track_names[e.id] = names[id(l)]
                l['central'] = e.id
            l['name'] = names[id(l)]
    # входные светофоры: слева нечётная горловина (Н), справа чётная (Ч)
    for l in st.mains:
        nm = l.get('name')
        left, right = l['nodes'][0], l['nodes'][-1]
        if nm == 'I':
            st.entry_names[left], st.entry_names[right] = 'Н', 'ЧД'
        elif nm == 'II':
            st.entry_names[left], st.entry_names[right] = 'НД', 'Ч'


def _number_switches(st: Station):
    """П. 2.3: нечётная горловина (слева) – 1, 3, 5…, чётная (справа) – 2, 4, 6…
    Нумерация от входного светофора по ординатам; при одной ординате меньший
    номер у верхней; стрелки съездов и стрелочных улиц – подряд."""
    g = st.g
    x0, _, x1, _ = g.bbox()
    group_of = {}
    for c in st.ladders + st.crossovers:
        for s in c['switches']:
            group_of.setdefault(s, c['switches'])
    for left in (True, False):
        sws = [s for s in st.sw if (g.nodes[s].x < st.xc) == left]
        dist = (lambda s: g.nodes[s].x - x0) if left else (lambda s: x1 - g.nodes[s].x)
        tol = st.u * 0.15

        def key(s):
            return (round(dist(s) / tol), g.nodes[s].y)

        sws.sort(key=key)
        num = 1 if left else 2
        for s in sws:
            if g.nodes[s].number:
                continue
            grp = [t for t in group_of.get(s, [s]) if t in sws and not g.nodes[t].number]
            if s not in grp:
                grp = [s]
            for t in sorted(grp, key=key):
                g.nodes[t].number = str(num)
                num += 2


# --------------------------------------------------------------------------
# Расстановка стыков
# --------------------------------------------------------------------------
def _add(st: Station, edge, t, rule, negab=None, why=''):
    """negab=None – габаритность будет посчитана по геометрии (update_negab)."""
    g = st.g
    e = g.edges[edge]
    L = g.length(e)
    m = min(L * 0.08, 0.2 * st.u)               # не вплотную к узлу, но без сдвига по норме
    t = min(max(t, m), L - m)
    anchor = st.__dict__.pop('_anchor', None)   # запомнено последним _t_near/_t_between
    # все запросы (даже слившиеся с уже стоящим стыком) – для компоновки по нормам
    st.__dict__.setdefault('demands', []).append((edge, anchor))
    for j in st.joints:
        if j.edge == edge and abs(j.t - t) < st.u * 0.2:
            return j
    j = Joint(edge, t, rule, bool(negab), fixed=negab is not None, anchor=anchor)
    st.joints.append(j)
    if why:
        st.log.append(f'  [{rule}] {why}')
    return j


# --- габарит: предельный столбик ------------------------------------------
# Предельный столбик ставится там, где оси расходящихся путей разошлись на 4100 мм.
# Междупутье на схеме (u) принимаем за 5300 мм, 3,5 м запаса от ПС – ~0.66 u
# (схема не в масштабе по длине, поэтому всё приближённо).
FOUL = 4.1 / 5.3
MARGIN = 3.5 / 5.3 * 0.5
FRAME = 0.7          # стык у рамного рельса со стороны остряков – за обозначением стрелки (5 мм) + 2 мм


def foul_dist(st: Station, s, edge_id) -> float:
    """Расстояние от центра стрелки s вдоль ребра edge_id, начиная с которого
    изолирующий стык габаритный (Lис ≥ Lпс + 3,5 м)."""
    g, u = st.g, st.u
    info = st.sw[s]
    if edge_id == info['trunk']:
        return FRAME * u
    sx, sy = g.direction(g.edges[info['straight']], s)
    bx, by = info['bdx'], info['bdy']
    cos = max(-1.0, min(1.0, sx * bx + sy * by))
    sin = max(math.sqrt(1 - cos * cos), 0.12)
    t_branch = FOUL * u / sin                 # до ПС по ответвлению
    if edge_id == info['branch']:
        return t_branch + MARGIN * u
    return t_branch * cos + MARGIN * u        # проекция ПС на прямой путь


# --- место под светофор у стыка (мм при u = 10 мм) ----------------------------
SIG_D = 3.0          # диаметр огня (прил. 1: Ø3..5 – берём минимальный, чтобы влезать в междупутье)
SIG_OFF = 3.3        # ось светофора от оси пути, справа по ходу
SIG_ROW = 3.1        # шаг рядов карликового выходного
SIG_LEN = {          # длина обозначения от основания в сторону движения
    'entry': 6.0 + SIG_D + 1.5 + 4 * SIG_D,
    'exit_mast': 4.0 + 1.5 + 5 * SIG_D,
    'exit_dwarf': 3 * SIG_D,
    'man_dwarf': 2 * SIG_D + 0.8,
    'man_mast': 6.0 + 2 * SIG_D + 0.8,
}
SIG_H = {            # насколько обозначение отходит от оси пути
    'entry': SIG_OFF + SIG_D / 2 + 2.0,             # с цифрами «2»
    'exit_mast': SIG_OFF + SIG_D / 2 + 2.0,
    'exit_dwarf': SIG_OFF + SIG_ROW + SIG_D / 2,
    'man_dwarf': SIG_OFF + SIG_D * 0.65,
    'man_mast': SIG_OFF + SIG_D * 0.65,
}


def sig_clear(st: Station, e, node, kind) -> float:
    """Минимальное расстояние от узла node до стыка на ребре e, чтобы светофор kind,
    разрешающий движение к node (справа по ходу, огни – по ходу), не залез на
    стрелку и не пересёк диагональ, уходящую от node в его сторону."""
    g = st.g
    k = st.u / 10.0
    L, H = SIG_LEN[kind] * k, SIG_H[kind] * k
    ox, oy = g.direction(e, node)            # от node к стыку
    mx, my = -ox, -oy                        # движение: от стыка к node
    sx, sy = -my, mx                         # правая сторона по ходу (экран: y вниз)
    need = L + 2.0 * k
    for f in g.incident(node):
        if f.id == e.id or g.is_horizontal(f, 4):
            continue
        vx, vy = g.direction(f, node)
        side = vx * sx + vy * sy             # уходит в сторону светофора
        back = vx * ox + vy * oy             # и назад, к стыку
        if side > 0.1 and back > 0.05:
            # + 4 мм: чтобы не задеть и кружок негабаритного стыка (Ø6) на диагонали
            need = max(need, L + H * back / side + 4.0 * k)
    return need


def _t_gab(st, e, node, extra=0.0, sig=None):
    """Ближайшая к узлу node габаритная позиция на ребре e (с местом под светофор sig)."""
    off = foul_dist(st, node, e.id) if node in st.sw else 0.5 * st.u
    if sig:
        off = max(off, sig_clear(st, e, node, sig))
    return _t_near(st, e, node, off + extra)


def _t_between(st, e):
    """Позиция между стрелками на концах ребра: по возможности габаритная для обеих."""
    L = st.g.length(e)
    lo = foul_dist(st, e.a, e.id) if e.a in st.sw else 0.0
    hi = L - (foul_dist(st, e.b, e.id) if e.b in st.sw else 0.0)
    st._anchor = ('between', lo, L - hi)
    return (lo + hi) / 2 if lo <= hi else L * (lo / (lo + (L - hi)))


def update_negab(st: Station, joints=None):
    g = st.g
    for j in joints if joints is not None else st.joints:
        if j.fixed:
            continue
        e = g.edges[j.edge]
        L = g.length(e)
        neg = False
        for s, dist in ((e.a, j.t), (e.b, L - j.t)):
            if s in st.sw and dist < foul_dist(st, s, e.id) - 1e-6:
                neg = True
        j.negab = neg


def _t_near(st, e, node, off):
    """Позиция на ребре e на расстоянии off от узла node."""
    L = st.g.length(e)
    st._anchor = (node, off)                  # желаемое расстояние – для компоновки
    off = min(off, max(L * 0.4, L - 0.5 * st.u))   # не залезать на другой конец
    return off if e.a == node else L - off


def _nm(st, n):
    return st.g.nodes[n].number or f'#{n}'


def place_joints(st: Station):
    g = st.g
    u = st.u
    st.joints.clear()
    st.log.clear()
    st.demands = []

    # а, в – главные пути у перегона: зона между входным стыком (а) и стыком
    # у первой стрелки (в) – бесстрелочный участок НП / НДП / ЧП / ЧДП
    for l in st.mains:
        for end in (l['nodes'][0], l['nodes'][-1]):
            if g.nodes[end].mark != 'peregon':
                continue
            path, cur = _walk_to_switch(st, end)
            sig = st.entry_names.get(end, '')
            first = path[0]
            _add(st, first.id, _t_near(st, first, end, 0.5 * u), 'а', negab=False,
                 why=f'граница станции, входной {sig}')
            if cur is not None:
                last = path[-1]
                _add(st, last.id, _t_gab(st, last, cur, sig='man_dwarf'), 'в',
                     why=f'участок {sig}П: от входного {sig} до стрелки {_nm(st, cur)}')

    # б – пути станции (центральные части путей, пересекающих ось)
    b_at = {}                                   # узел на конце пути -> стык б
    for l in st.lines:
        e = _central_edge(st, l)
        if e is None or 'name' not in l:        # только пути станции (I, II, 3, 4…)
            continue
        nm = l.get('name', '?')
        for n in (e.a, e.b):
            if g.degree(n) >= 2:
                side = 'слева' if g.nodes[n].x < st.xc else 'справа'
                kind = 'exit_mast' if any(l is m for m in st.mains) else 'exit_dwarf'
                b_at[n] = (e, _add(st, e.id, _t_gab(st, e, n, sig=kind), 'б',
                                   why=f'путь {nm}П ({side})'))
    _align_ladder_ends(st, b_at)

    # з – стрелка, ведущая в предохранительный (короткий) тупик, – отдельный участок.
    # Приближённо: ответвление стрелки упирается в тупик длиной < 3 междупутий
    # без других стрелок; сбрасывающие стрелки/остряки на заданиях не рисуются.
    for s, info in st.sw.items():
        e = g.edges[info['branch']]
        n, length, ok = s, 0.0, False
        cur = e
        while True:
            length += g.length(cur)
            n = g.other(cur, n)
            if g.degree(n) == 1:
                ok = g.nodes[n].mark == 'tupik' and length < 3 * u
                break
            if g.degree(n) != 2:
                break
            cur = [x for x in g.incident(n) if x.id != cur.id][0]
        if not ok:
            continue
        for k in (info['trunk'], info['straight'], info['branch']):
            ed = g.edges[k]
            _add(st, k, _t_gab(st, ed, s), 'з',
                 why=f'стрелка {_nm(st, s)} ведёт в предохранительный тупик – отдельный участок')

    # г, д – тупики и подъездные пути
    for n in list(g.nodes.values()):
        if g.degree(n.id) != 1 or n.mark not in ('tupik', 'pp'):
            continue
        path, cur = _walk_to_switch(st, n.id)
        if cur is None:
            continue
        last = path[-1]
        what = 'подъездной путь' if n.mark == 'pp' else 'тупик'
        # если последний участок – центральная часть пути станции, стык уже есть (б)
        if last.id in st.track_names:
            continue
        kind = 'man_mast' if n.mark == 'pp' else 'man_dwarf'
        # если к стрелке тупик подходит наклонным отрезком – стык (и маневровый
        # светофор при нём) ставим на горизонтальной части тупика, у излома
        if not g.is_horizontal(last, 4):
            hz = [k for k, p in enumerate(path) if g.is_horizontal(p, 4)]
            if hz:
                i = hz[-1]
                edge = path[i]
                bend = g.other(edge, n.id) if i == 0 else \
                    [x for x in (edge.a, edge.b) if x in (path[i + 1].a, path[i + 1].b)][0]
                _add(st, edge.id, _t_gab(st, edge, bend, sig=kind), 'г',
                     why=f'{what} отделён от стрелки {_nm(st, cur)}')
                continue
        _add(st, last.id, _t_gab(st, last, cur, sig=kind), 'г',
             why=f'{what} отделён от стрелки {_nm(st, cur)}')
        if n.mark == 'pp':
            _add(st, last.id, _t_gab(st, last, cur, 0.8 * u, sig=kind), 'д',
                 why='короткая РЦ (25 м) на входе с подъездного пути')

    # е – стрелочные улицы (стыки между стрелками улицы негабаритные, рис. 2.7)
    for c in st.ladders:
        sws = c['switches']
        nums = ', '.join(_nm(st, s) for s in sws)
        for a, b in zip(sws, sws[1:]):
            ia, ib = c['nodes'].index(a), c['nodes'].index(b)
            k = c['edges'][ia] if ib == ia + 1 else c['edges'][(ia + ib) // 2]
            e = g.edges[k]
            _add(st, k, g.length(e) / 2, 'е', negab=True,
                 why=f'стрелочная улица ({nums}): стык между {_nm(st, a)} и {_nm(st, b)}')

    # ж – съезды: стык между стрелками съезда; стрелки спаренные, поэтому
    # стык не считается негабаритным (п. 2.4)
    for c in st.crossovers:
        a, b = c['switches']
        k = c['edges'][len(c['edges']) // 2]
        _add(st, k, g.length(g.edges[k]) / 2, 'ж', negab=False,
             why=f'съезд {_nm(st, a)}/{_nm(st, b)}: стык между спаренными стрелками')

    # ж – соседние стрелки на одном пути с ответвлениями в разные стороны
    for l in st.lines:
        ns = [n for n in l['nodes'] if n in st.sw]
        for a, b in zip(ns, ns[1:]):
            ia, ib = st.sw[a], st.sw[b]
            if ia['branch'] in l['edges'] or ib['branch'] in l['edges']:
                continue            # стрелка, у которой по этому пути идёт ответвление
            if ia['bdy'] * ib['bdy'] >= 0:
                continue            # ответвления в одну сторону
            k = _edge_between(st, l, a, b)
            if k is None or any(j.edge == k for j in st.joints):
                continue            # уже разделены (например, стыками пути – б)
            e = g.edges[k]
            _add(st, k, _t_between(st, e), 'ж',
                 why=f'параллельные передвижения по стрелкам {_nm(st, a)} и {_nm(st, b)}')

    # и – не более трёх стрелок в участке
    for _ in range(50):
        secs = compute_sections(st)
        big = [s for s in secs if len(s['switches']) > 3]
        if not big:
            break
        s = big[0]
        k, t = _best_split(st, s)
        if k is None:
            break
        _add(st, k, t, 'и', why='в участке было {} стрелок ({}) – разделён'.format(
            len(s['switches']), ', '.join(sorted((_nm(st, x) for x in s['switches']), key=_numkey))))
    update_negab(st)
    st.sections = compute_sections(st)
    name_sections(st)
    check_entries(st)


def _align_ladder_ends(st: Station, b_at):
    """Крайний путь стрелочной улицы, примыкающий к ней изломом (без стрелки),
    получает стык б на той же ординате, что и соседний путь у последней стрелки
    улицы, – стыки стоят друг под другом."""
    g = st.g
    for bend, (e, j) in b_at.items():
        if g.degree(bend) != 2:
            continue
        diag = [f for f in g.incident(bend) if f.id != e.id][0]
        chain = next((c for c in st.chains if diag.id in c['edges']), None)
        if chain is None or not chain['switches']:
            continue
        # ближайшая к излому стрелка цепочки
        idx = chain['nodes'].index(bend) if bend in chain['nodes'] else None
        if idx is None:
            continue
        s = min(chain['switches'], key=lambda n: abs(chain['nodes'].index(n) - idx))
        if s not in b_at:
            continue
        e2, j2 = b_at[s]
        x_target = g.point_on(e2, j2.t)[0]
        ax, bx = g.nodes[e.a].x, g.nodes[e.b].x
        L = g.length(e)
        t = (x_target - ax) / (bx - ax) * L if bx != ax else j.t
        if 0.5 < t < L - 0.5:                   # хоть 1 мм от излома – но строго под соседним
            j.t = t
            j.align_to = j2                     # держать ординату и после округления
            j.anchor = (bend, t if e.a == bend else L - t)


def _walk_to_switch(st: Station, end):
    """Путь от конца (тупик/перегон) по узлам степени 2 до первой стрелки."""
    g = st.g
    e = g.incident(end)[0]
    path = [e]
    cur = g.other(e, end)
    while cur not in st.sw and g.degree(cur) == 2:
        f = [x for x in g.incident(cur) if x.id != path[-1].id][0]
        path.append(f)
        cur = g.other(f, cur)
    return path, (cur if cur in st.sw else None)


def check_entries(st: Station):
    """Проверка: на каждом въезде есть бесстрелочная зона, ограниченная двумя
    стыками (а – у входного светофора, в – перед первой стрелкой)."""
    g = st.g
    st.entry_check = []
    for l in st.mains:
        for end in (l['nodes'][0], l['nodes'][-1]):
            if g.nodes[end].mark != 'peregon':
                continue
            sig = st.entry_names.get(end, '?')
            path, cur = _walk_to_switch(st, end)
            eids = {e.id for e in path}
            js = [j for j in st.joints if j.edge in eids]
            has_a = any(j.rule == 'а' for j in js)
            has_v = any(j.rule == 'в' for j in js)
            sec = next((s for s in st.sections if s['name'] == f'{sig}П'), None)
            ok = has_a and has_v and sec is not None and not sec['switches']
            st.entry_check.append((sig, ok, _nm(st, cur) if cur else '—'))


def _numkey(s):
    try:
        return int(s.strip('#'))
    except ValueError:
        return 999


def _edge_between(st, line, a, b):
    g = st.g
    xa, xb = sorted((g.nodes[a].x, g.nodes[b].x))
    for k in line['edges']:
        e = g.edges[k]
        ex0, ex1 = sorted((g.nodes[e.a].x, g.nodes[e.b].x))
        if ex0 >= xa - 1 and ex1 <= xb + 1:
            return k
    return None


def _best_split(st: Station, sec):
    """Ищем ребро между стрелками, разрез которого лучше всего делит участок."""
    g = st.g
    best = None
    for k in sec['edges']:
        e = g.edges[k]
        if not (e.a in st.sw and e.b in st.sw):
            continue
        if any(j.edge == k for j in st.joints):
            continue
        L = g.length(e)
        if L < st.u * 0.3:
            continue
        trial = Joint(k, L / 2, 'и')
        st.joints.append(trial)
        parts = [s for s in compute_sections(st) if set(s['switches']) & set(sec['switches'])]
        st.joints.pop()
        worst = max(len(p['switches']) for p in parts)
        score = (worst, 0 if g.is_horizontal(e) else 1, -L)
        if best is None or score < best[0]:
            best = (score, k, L / 2)
    return (best[1], best[2]) if best else (None, None)


# --------------------------------------------------------------------------
# Участки (секции) = связные компоненты после разрезания стыками
# --------------------------------------------------------------------------
def pieces_of(st: Station):
    """Каждое ребро делится стыками на куски: (edge, t0, t1, node_or_None_at_t0, node_or_None_at_t1)."""
    g = st.g
    by_edge = {}
    for j in st.joints:
        by_edge.setdefault(j.edge, []).append(j.t)
    out = []
    for e in g.edges.values():
        ts = sorted(by_edge.get(e.id, []))
        L = g.length(e)
        cuts = [0.0] + ts + [L]
        for i in range(len(cuts) - 1):
            out.append(dict(edge=e.id, t0=cuts[i], t1=cuts[i + 1],
                            na=e.a if i == 0 else None,
                            nb=e.b if i == len(cuts) - 2 else None))
    return out


def compute_sections(st: Station):
    g = st.g
    pcs = pieces_of(st)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i, p in enumerate(pcs):
        find(('p', i))
        for n in (p['na'], p['nb']):
            if n is not None:
                union(('p', i), ('n', n))
    comps = {}
    for i, p in enumerate(pcs):
        comps.setdefault(find(('p', i)), []).append(i)
    secs = []
    for idx, members in enumerate(comps.values()):
        nodes = set()
        for i in members:
            for n in (pcs[i]['na'], pcs[i]['nb']):
                if n is not None:
                    nodes.add(n)
        edges = {pcs[i]['edge'] for i in members
                 if pcs[i]['na'] is not None and pcs[i]['nb'] is not None}
        secs.append(dict(pieces=[pcs[i] for i in members], nodes=nodes, edges=edges,
                         switches=[n for n in nodes if n in st.sw], name=''))
    return secs


def name_sections(st: Station):
    g = st.g
    for s in st.sections:
        pcs = s['pieces']
        ends = [n for n in s['nodes'] if g.degree(n) == 1]
        if s['switches']:
            nums = sorted((_nm(st, x) for x in s['switches']), key=_numkey)
            s['name'] = f'{nums[0]}СП' if len(nums) == 1 else f'{nums[0]}-{nums[-1]}СП'
            continue
        if any(g.nodes[n].mark == 'peregon' for n in ends):
            s['name'] = 'перегон'
            continue
        if any(g.nodes[n].mark in ('tupik', 'pp') for n in ends):
            if any(g.nodes[n].mark == 'pp' for n in ends):
                s['name'] = 'п/п'
            else:
                s['name'] = next((g.nodes[n].label for n in ends if g.nodes[n].label), 'тупик')
            continue
        # бесстрелочный участок
        eids = {p['edge'] for p in pcs}
        tn = [st.track_names[k] for k in eids if k in st.track_names]
        if tn:
            s['name'] = f'{tn[0]}П'
            continue
        # за входным светофором?
        nm = None
        for end, sig in st.entry_names.items():
            e = g.incident(end)[0]
            if e.id in eids:
                nm = f'{sig}П'
        if nm:
            s['name'] = nm
            continue
        # между стрелками: соседние стрелки по концам кусков
        near = set()
        for p in pcs:
            e = g.edges[p['edge']]
            for n in (e.a, e.b):
                if n in st.sw:
                    near.add(_nm(st, n))
        near = sorted(near, key=_numkey)
        s['name'] = '/'.join(near) + 'П' if near else 'П'


def report(st: Station) -> str:
    g = st.g
    out = []
    out.append(f'Стрелок: {len(st.sw)}, путей станции: {len([l for l in st.lines if "name" in l])}, '
               f'съездов: {len(st.crossovers)}, стрелочных улиц: {len(st.ladders)}')
    out.append(f'Стыков: {len(st.joints)} (негабаритных: {sum(j.negab for j in st.joints)})')
    if abs(st.u - 10) < 1e-6:
        x0 = min(n.x for n in g.nodes.values())
        out.append('Миллиметровка: 1 клетка = 10 мм = междупутье; ординаты от левого края, мм:')
        sws = sorted(st.sw, key=lambda s: _numkey(_nm(st, s)))
        out.append('  ' + ', '.join(f'{_nm(st, s)}: {g.nodes[s].x - x0:.0f}' for s in sws))
        chk = getattr(st, 'geom_check', None)
        if chk is not None:
            bad, off = chk
            out.append('Проверка чертежа: диагонали 10 мм по высоте на 15 мм по горизонтали – '
                       + ('все' if not bad else f'НЕ все ({len(bad)}: {bad})')
                       + '; узлы на линиях сетки – ' + ('все' if not off else f'НЕ все ({len(off)})'))
    out.append('')
    out.append('Въезды (зона между стыками а и в):')
    for sig, ok, first in st.entry_check:
        out.append(f'  {sig}П: ' + (f'есть, до стрелки {first}' if ok else 'НЕТ – проверьте!'))
    out.append('')
    from checks import audit_text                   # поздний импорт: checks зависит от joints
    out += audit_text(st)
    out.append('')
    if getattr(st, 'signals', None):
        from signals import report_signals          # поздний импорт: signals зависит от joints
        out.append(f'Светофоры ({len(st.signals)}):')
        out += report_signals(st)
        out.append('')
    out.append('Обоснование стыков:')
    out += st.log
    out.append('')
    out.append('Участки:')
    for s in sorted(st.sections, key=lambda s: (s['name'] in ('перегон', 'тупик', 'п/п'), s['name'])):
        if s['name'] in ('перегон',):
            continue
        extra = ''
        if s['switches']:
            extra = f"  стрелок: {len(s['switches'])}"
            if len(s['switches']) > 3:
                extra += '  (!) > 3'
        out.append(f"  {s['name']}{extra}")
    return '\n'.join(out)
