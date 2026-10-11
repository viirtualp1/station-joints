"""Компоновка схемы «на миллиметровке».

Схема перечерчивается так, как её чертили бы на миллиметровой бумаге:
  * междупутье = 1 клетка = 10 мм, все пути лежат на линиях сетки 10 мм;
  * все диагонали (съезды, стрелочные улицы, ответвления) – одного наклона:
    10 мм по высоте на 15 мм по горизонтали (DIAG_RUN);
  * все узлы (стрелки, изломы, концы) – на линиях миллиметровки (целые мм);
  * между элементами выдерживаются минимальные расстояния (см. ниже);
  * если стыки не помещаются, схема раздвигается по горизонтали, наклон
    диагоналей и взаимный порядок элементов при этом не меняются.

Задача раздвижки – система разностных ограничений x_b - x_a >= L,
решается поиском самых длинных путей (Беллман–Форд) от исходных положений.
"""
from __future__ import annotations

import math

from graph import Annotation
from joints import (Station, _central_edge, _find_center, _switch_geometry, analyse, place_joints,
                    update_negab, update_sections)
from paper import OVERLAP, usable_width
from signals import drawing_bounds, place_signals, prune_signal_joints

CELL = 10.0          # мм – междупутье
MIN_EDGE = 5.0       # мин. длина любого горизонтального отрезка между узлами
MIN_SW = 14.0        # мин. расстояние между соседними стрелками (2 обозначения по 5 мм + зазор)
MIN_JJ = 8.0         # мин. расстояние между соседними стыками
MIN_NJ = 5.0         # мин. расстояние от узла до «свободного» стыка
ENTRY_ZONE = 40.0    # мин. длина участка НП/ЧП между стыками а и в (помещается входной светофор)
TRACK_ZONE = 30.0    # мин. длина пути станции между стыками б
MIN_GAP = 15.0       # зазор между несвязанными отрезками на одной линии сетки
PP_TEXT = 15.0       # место под надпись «п/п» у конца подъездного пути
GRID_X = 5           # шаг сетки для узлов по горизонтали, мм: стрелки, повороты, концы
                     # стоят на линиях 5 мм (диагональ 15 мм кратна 5 – оба её конца на сетке)
MARGIN = 20.0        # поля листа слева/сверху


def snap(v: float, up=False) -> int:
    """Округление до линии сетки GRID_X (up=True – вверх, для минимальных длин)."""
    q = v / GRID_X
    return int((math.ceil(q - 1e-6) if up else round(q)) * GRID_X)


def build_station(graph, annots=(), sheet_fmt: str | None = None,
                  odd_right: bool | None = None):
    """analyse -> перенос на сетку -> раздвижка по нормам -> расстановка стыков."""
    st = analyse(graph, odd_right)
    orig = {n.id: (n.x, n.y) for n in graph.nodes.values()}
    y0, u0 = to_grid(st)
    for _ in range(8):
        place_joints(st)
        if not relax(st):
            break
    refresh(st)
    place_joints(st)
    snap_joints(st)
    place_signals(st)
    prune_signal_joints(st)
    if sheet_fmt:
        # две горловины – на двух листах, пути парка вытянуты через оба (как чертят
        # вручную на миллиметровке); после растяжки стыки и светофоры – заново
        if spread_to_sheets(st, sheet_fmt):
            place_joints(st)
            snap_joints(st)
            place_signals(st)
            prune_signal_joints(st)
    st.geom_check = check_geometry(st)
    new_annots = _move_annots(st, annots, orig, y0, u0)
    return st, new_annots


def _cut_candidates(st: Station):
    """Ординаты, где схему пересекают только горизонтальные пути (растягивать можно)."""
    g = st.g
    xs = sorted({n.x for n in g.nodes.values()})
    out = []
    for a, b in zip(xs, xs[1:]):
        if b - a < 1:
            continue
        x = (a + b) / 2
        crossing = [e for e in g.edges.values()
                    if min(g.nodes[e.a].x, g.nodes[e.b].x) < x < max(g.nodes[e.a].x, g.nodes[e.b].x)]
        if crossing and all(abs(g.nodes[e.a].y - g.nodes[e.b].y) < 1e-6 for e in crossing):
            out.append(x)
    return out


def spread_to_sheets(st: Station, fmt: str) -> bool:
    """Растянуть пути парка по оси станции так, чтобы левая горловина заполнила
    лист 1, правая – лист 2 выбранного формата. Возвращает True, если растянули."""
    g = st.g
    cands = _cut_candidates(st)
    if not cands:
        st.sheet_cut = None
        return False
    x = min(cands, key=lambda c: abs(c - st.xc))
    bx0, _, bx1, _ = drawing_bounds(st, pad=6)
    W = usable_width(fmt) - OVERLAP / 2 - 6        # запас под подписи у кромки
    dl = max(0, math.floor((W - (x - bx0)) / 10) * 10)
    dr = max(0, math.floor((W - (bx1 - x)) / 10) * 10)
    d = dl + dr
    if d:
        for n in g.nodes.values():
            if n.x > x:
                n.x += d
        refresh(st)
    st.sheet_cut = x + dl
    return d > 0


# --------------------------------------------------------------------------
def to_grid(st: Station):
    g = st.g
    u = st.u
    st.orig_x = {n.id: n.x for n in g.nodes.values()}
    x0 = min(n.x for n in g.nodes.values())
    y0 = min(n.y for n in g.nodes.values())
    # уровни путей -> целые клетки: каждый уровень строго на линии 10 мм,
    # соседние уровни не ближе одной клетки, порядок сверху вниз сохраняется
    levels = []
    for y in sorted(n.y for n in g.nodes.values()):
        if levels and y - levels[-1][-1] < u * 0.3:
            levels[-1].append(y)
        else:
            levels.append([y])
    row_of, prev = {}, None
    for lv in levels:
        r = round((sum(lv) / len(lv) - y0) / u)
        if prev is not None:
            r = max(r, prev + 1)
        for y in lv:
            row_of[y] = r
        prev = r
    # направление каждой диагонали (вправо/влево) берём с картинки ДО округления
    # (у крутых улиц отрезок между соседними стрелками короче шага сетки);
    # у цепочки (улица, съезд) направление общее – по её концам
    st.diag_dir = {}
    for e in g.edges.values():
        na, nb = g.nodes[e.a], g.nodes[e.b]
        if abs(row_of[na.y] - row_of[nb.y]) > 0:
            st.diag_dir[e.id] = 1 if nb.x >= na.x else -1
    for c in st.chains:
        ns = c['nodes']
        first, last = g.nodes[ns[0]], g.nodes[ns[-1]]
        if row_of[first.y] == row_of[last.y]:
            continue
        # знак «x растёт вместе с y» для всей цепочки
        s = 1 if (last.x - first.x) * (last.y - first.y) >= 0 else -1
        for k in c['edges']:
            e = g.edges[k]
            na, nb = g.nodes[e.a], g.nodes[e.b]
            if e.id in st.diag_dir:
                st.diag_dir[e.id] = s if nb.y > na.y else -s
    # а наклон дальше задаётся единый: 10 мм по высоте на 15 мм по горизонтали
    for n in g.nodes.values():
        n.y = MARGIN + row_of[n.y] * CELL
        n.x = snap(MARGIN + (n.x - x0) / u * CELL)      # на линии сетки (5 мм)
    st.u = CELL
    refresh(st)
    return y0, u


def _find_center_named(st: Station):
    """Ось станции после компоновки: середина общего участка путей станции,
    получивших имена при анализе (кроме главных – они идут через всю схему)."""
    mains = {id(l) for l in st.mains}
    named = [l for l in st.lines if 'name' in l and id(l) not in mains]
    if not named:
        _find_center(st)
        return
    lo = max(l['x0'] for l in named)
    hi = min(l['x1'] for l in named)
    if lo < hi:
        st.xc = (lo + hi) / 2
    else:
        mids = sorted((l['x0'] + l['x1']) / 2 for l in named)
        st.xc = mids[len(mids) // 2]


def refresh(st: Station):
    g = st.g
    for l in st.lines:
        l['x0'] = min(g.nodes[n].x for n in l['nodes'])
        l['x1'] = max(g.nodes[n].x for n in l['nodes'])
        l['y'] = g.nodes[l['nodes'][0]].y
        l['nodes'].sort(key=st.xkey)
    st.sw.clear()
    _switch_geometry(st)
    _find_center_named(st)
    # имена путей привязаны к рёбрам, пересекающим ось; ось могла сместиться
    names = {}
    for l in st.lines:
        if 'name' in l:
            e = _central_edge(st, l)
            if e:
                names[e.id] = l['name']
    if names:
        st.track_names = names


# --------------------------------------------------------------------------
def _required(st: Station, e) -> float:
    """Минимальная длина горизонтального отрезка e, чтобы на нём разошлись
    его стыки с нормативными расстояниями от стрелок."""
    g = st.g
    a, b = (e.a, e.b) if st.xkey(e.a) <= st.xkey(e.b) else (e.b, e.a)
    need = MIN_EDGE
    if a in st.sw and b in st.sw:
        need = MIN_SW
    js = [j for j in st.joints if j.edge == e.id]
    dem = [an for k, an in st.demands if k == e.id]
    if not js and not dem:
        return need
    offs_a, offs_b = [], []
    floats = 0
    between = 0.0
    rules = {j.rule for j in js}
    for an in dem:
        if isinstance(an, tuple) and an and an[0] == 'between':
            floats += 1
            between = max(between, an[1] + an[2])
        elif isinstance(an, tuple) and an[0] == a:
            offs_a.append(an[1])
        elif isinstance(an, tuple) and an[0] == b:
            offs_b.append(an[1])
        else:
            floats += 1

    def chain(offs):
        """Стыки от одного узла: каждый не ближе нормы к своему месту и
        не ближе MIN_JJ к предыдущему (одинаковые места – один стык)."""
        p = None
        for o in sorted(offs):
            if p is None:
                p = o
            elif o - p >= 1.0:
                p = max(o, p + MIN_JJ)
        return p or 0.0

    A, B = chain(offs_a), chain(offs_b)
    groups = (A > 0) + (B > 0) + floats
    L = A + B + MIN_JJ * max(0, groups - 1)
    if A == 0:
        L += MIN_NJ
    if B == 0:
        L += MIN_NJ
    need = max(need, L, between + (MIN_JJ if floats > 1 else 0))
    if 'а' in rules and 'в' in rules:
        need = max(need, A + B + ENTRY_ZONE)
    if 'б' in rules and e.id in st.track_names:
        need = max(need, A + B + TRACK_ZONE)
    if any(g.nodes[n].mark == 'pp' for n in (a, b)):
        need += PP_TEXT
    return need


def relax(st: Station) -> bool:
    """Раздвигает схему, чтобы все горизонтальные отрезки получили нужную длину.
    Возвращает True, если что-то сдвинулось."""
    g = st.g
    x = {n: g.nodes[n].x for n in g.nodes}
    cons, rev = [], []                          # x[v] >= x[u] + w
    for e in g.edges.values():
        na, nb = g.nodes[e.a], g.nodes[e.b]
        if abs(na.y - nb.y) < 1e-6:
            a, b = (e.a, e.b) if st.xkey(e.a) <= st.xkey(e.b) else (e.b, e.a)
            cons.append((a, b, snap(_required(st, e), up=True)))
        else:
            d = diag_dx(st, e)                  # единый наклон 10:15
            cons.append((e.a, e.b, d))
            rev.append((e.b, e.a, -d))
    # на одной линии сетки несвязанные отрезки не должны наезжать друг на друга
    rows = {}
    for n in g.nodes.values():
        rows.setdefault(round(n.y * 2), []).append(n.id)
    linked = {frozenset((e.a, e.b)) for e in g.edges.values()}
    for ids in rows.values():
        ids.sort(key=st.xkey)
        for a, b in zip(ids, ids[1:]):
            if frozenset((a, b)) not in linked:
                cons.append((a, b, snap(MIN_GAP, up=True)))
    # концы главных путей у перегона с одной стороны – на одной ординате: входные
    # Н и НД (Ч и ЧД) ставятся «на одном уровне» (п. 2.5)
    for left in (True, False):
        ends = [n.id for n in g.nodes.values() if n.mark == 'peregon'
                and (n.x < st.xc) == left]
        for a, b in zip(ends, ends[1:]):
            rev.append((a, b, 0))
            rev.append((b, a, 0))
    ok = _solve(x, cons + rev, len(x))
    st.slope_ok = ok
    if not ok:                                  # цикл (напр., перекрёстный съезд) –
        x = {n: g.nodes[n].x for n in g.nodes}  # разрешаем диагоналям менять наклон
        _solve(x, cons, len(x))
    moved = max(abs(x[n] - g.nodes[n].x) for n in x) if x else 0
    for n in x:
        g.nodes[n].x = snap(x[n])               # все узлы – на линиях сетки 5 мм
    if moved > 0.25:
        refresh(st)
    return moved > 0.25


DIAG_RUN = 15.0      # мм по горизонтали на одно междупутье (10 мм по высоте)
SLOPE = DIAG_RUN / CELL
DIAG_ANGLE = math.degrees(math.atan2(CELL, DIAG_RUN))


def diag_dx(st: Station, e) -> int:
    """Горизонтальная проекция диагонали: на 10 мм по высоте – 15 мм по горизонтали
    (1 междупутье -> 15 мм, 2 -> 30 мм, 3 -> 45 мм), узлы остаются на линиях сетки."""
    g = st.g
    dy = abs(g.nodes[e.b].y - g.nodes[e.a].y)
    return st.diag_dir.get(e.id, 1) * round(SLOPE * dy)


def snap_joints(st: Station):
    """Стыки на горизонтальных путях – на целые миллиметры (линии миллиметровки)."""
    g = st.g
    update_negab(st)
    for j in st.joints:
        e = g.edges[j.edge]
        (ax, ay), (bx, by) = g.pos(e.a), g.pos(e.b)
        if abs(ay - by) > 1e-6:
            continue
        L = g.length(e)
        x0 = ax + (bx - ax) * j.t / L
        was_negab, t_old = j.negab, j.t
        # ближайшее целое, затем другое – если округление сделало стык негабаритным
        for x in sorted({math.floor(x0), math.ceil(x0)}, key=lambda v: abs(v - x0)):
            t = abs(x - ax)
            if not 0.5 < t < L - 0.5:
                continue
            j.t = t
            update_negab(st, [j])
            if j.negab <= was_negab:
                break
        else:
            j.t = t_old
            update_negab(st, [j])
    # стыки в конце стрелочной улицы – строго под стыком соседнего пути
    for j in st.joints:
        j2 = j.align_to
        if j2 is None:
            continue
        e = g.edges[j.edge]
        ax, bx = g.nodes[e.a].x, g.nodes[e.b].x
        x = g.point_on(g.edges[j2.edge], j2.t)[0]
        L = g.length(e)
        t = (x - ax) / (bx - ax) * L if bx != ax else j.t
        if 0.5 < t < L - 0.5:
            j.t = t
    update_negab(st)
    update_sections(st)                         # участки – по окончательным положениям стыков


def check_geometry(st: Station):
    """Проверка чертежа: углы диагоналей, узлы на сетке."""
    g = st.g
    bad_angle, off_grid = [], []
    for e in g.edges.values():
        na, nb = g.nodes[e.a], g.nodes[e.b]
        dy = abs(nb.y - na.y)
        if dy > 1e-6:
            ang = math.degrees(math.atan2(dy, abs(nb.x - na.x)))
            if abs(ang - DIAG_ANGLE) > 0.5:
                bad_angle.append(round(ang, 1))
    for n in g.nodes.values():
        if abs(n.x % GRID_X) > 1e-6 or abs(n.y % CELL) > 1e-6:
            off_grid.append(n.id)
    return bad_angle, off_grid


def _solve(x, cons, n):
    for _ in range(4 * n + 10):
        changed = False
        for u, v, w in cons:
            if x[u] + w > x[v] + 1e-6:
                x[v] = x[u] + w
                changed = True
        if not changed:
            return True
    return False


# --------------------------------------------------------------------------
def _move_annots(st: Station, annots, orig, y0, u0):
    """Надписи (п/п, номер варианта) переносим вслед за ближайшим узлом схемы."""
    g = st.g
    out = []
    s = CELL / u0
    for a in annots:
        cx, cy = (a.x0 + a.x1) / 2, (a.y0 + a.y1) / 2
        near = min((n for n in g.nodes if n in orig),
                   key=lambda n: math.hypot(orig[n][0] - cx, orig[n][1] - cy), default=None)
        if near is None:
            continue
        nx = g.nodes[near].x + (cx - orig[near][0]) * s
        ny = g.nodes[near].y + (cy - orig[near][1]) * s
        w, h = (a.x1 - a.x0) * s, (a.y1 - a.y0) * s
        out.append(Annotation(nx - w / 2, ny - h / 2, nx + w / 2, ny + h / 2, a.mask, scale=s))
    return out
