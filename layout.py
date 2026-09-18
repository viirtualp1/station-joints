"""Компоновка схемы «на миллиметровке».

Схема перечерчивается так, как её чертили бы на миллиметровой бумаге:
  * междупутье = 1 клетка = 10 мм, все пути лежат на линиях сетки 10 мм;
  * все диагонали (съезды, стрелочные улицы, ответвления) – под 30° (прил. 1);
  * все узлы (стрелки, изломы, концы) – на линиях миллиметровки (целые мм),
    поэтому проекция диагонали на 1 междупутье = 17 мм (угол 30,5°);
  * между элементами выдерживаются минимальные расстояния (см. ниже);
  * если стыки не помещаются, схема раздвигается по горизонтали, наклон
    диагоналей и взаимный порядок элементов при этом не меняются.

Задача раздвижки – система разностных ограничений x_b - x_a >= L,
решается поиском самых длинных путей (Беллман–Форд) от исходных положений.
"""
from __future__ import annotations

import math

from graph import Annotation
from joints import (Station, _central_edge, _find_center, _switch_geometry, analyse,
                    place_joints)

CELL = 10.0          # мм – междупутье
MIN_EDGE = 5.0       # мин. длина любого горизонтального отрезка между узлами
MIN_SW = 14.0        # мин. расстояние между соседними стрелками (2 обозначения по 5 мм + зазор)
MIN_JJ = 8.0         # мин. расстояние между соседними стыками
MIN_NJ = 5.0         # мин. расстояние от узла до «свободного» стыка
ENTRY_ZONE = 30.0    # мин. длина участка НП/ЧП между стыками а и в
TRACK_ZONE = 30.0    # мин. длина пути станции между стыками б
MIN_GAP = 15.0       # зазор между несвязанными отрезками на одной линии сетки
PP_TEXT = 15.0       # место под надпись «п/п» у конца подъездного пути
MARGIN = 20.0        # поля листа слева/сверху


def build_station(graph, annots=()):
    """analyse -> перенос на сетку -> раздвижка по нормам -> расстановка стыков."""
    st = analyse(graph)
    orig = {n.id: (n.x, n.y) for n in graph.nodes.values()}
    y0, u0 = to_grid(st)
    for _ in range(8):
        place_joints(st)
        if not relax(st):
            break
    refresh(st)
    place_joints(st)
    st.geom_check = check_geometry(st)
    new_annots = _move_annots(st, annots, orig, y0, u0)
    return st, new_annots


# --------------------------------------------------------------------------
def to_grid(st: Station):
    g = st.g
    u = st.u
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
    for n in g.nodes.values():
        n.y = MARGIN + row_of[n.y] * CELL
        n.x = round(MARGIN + (n.x - x0) / u * CELL)     # на линии сетки (1 мм)
    # направление каждой диагонали (вправо/влево) берём с картинки,
    # а наклон дальше задаётся строго 30° (прил. 1)
    st.diag_dir = {}
    for e in g.edges.values():
        na, nb = g.nodes[e.a], g.nodes[e.b]
        if abs(na.y - nb.y) > 1e-6:
            st.diag_dir[e.id] = 1 if nb.x >= na.x else -1
    st.u = CELL
    refresh(st)
    return y0, u


def refresh(st: Station):
    g = st.g
    for l in st.lines:
        l['x0'] = min(g.nodes[n].x for n in l['nodes'])
        l['x1'] = max(g.nodes[n].x for n in l['nodes'])
        l['y'] = g.nodes[l['nodes'][0]].y
        l['nodes'].sort(key=lambda n: g.nodes[n].x)
    st.sw.clear()
    _switch_geometry(st)
    _find_center(st)
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
    a, b = (e.a, e.b) if g.nodes[e.a].x <= g.nodes[e.b].x else (e.b, e.a)
    need = MIN_EDGE
    if a in st.sw and b in st.sw:
        need = MIN_SW
    js = [j for j in st.joints if j.edge == e.id]
    dem = [an for k, an in getattr(st, 'demands', []) if k == e.id]
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
            a, b = (e.a, e.b) if na.x <= nb.x else (e.b, e.a)
            cons.append((a, b, math.ceil(_required(st, e) - 1e-6)))
        else:
            d = diag_dx(st, e)                  # строго 30° к горизонтали
            cons.append((e.a, e.b, d))
            rev.append((e.b, e.a, -d))
    # на одной линии сетки несвязанные отрезки не должны наезжать друг на друга
    rows = {}
    for n in g.nodes.values():
        rows.setdefault(round(n.y * 2), []).append(n.id)
    linked = {frozenset((e.a, e.b)) for e in g.edges.values()}
    for ids in rows.values():
        ids.sort(key=lambda n: g.nodes[n].x)
        for a, b in zip(ids, ids[1:]):
            if frozenset((a, b)) not in linked:
                cons.append((a, b, MIN_GAP))
    ok = _solve(x, cons + rev, len(x))
    st.slope_ok = ok
    if not ok:                                  # цикл (напр., перекрёстный съезд) –
        x = {n: g.nodes[n].x for n in g.nodes}  # разрешаем диагоналям менять наклон
        _solve(x, cons, len(x))
    moved = max(abs(x[n] - g.nodes[n].x) for n in x) if x else 0
    for n in x:
        g.nodes[n].x = round(x[n])              # все узлы – на линиях миллиметровки
    if moved > 0.25:
        refresh(st)
    return moved > 0.25


SLOPE = 1 / math.tan(math.radians(30))     # √3: горизонталь на 1 мм подъёма


def diag_dx(st: Station, e) -> int:
    """Горизонтальная проекция диагонали под 30°, округлённая до целого мм
    (узлы – на линиях сетки): 1 междупутье (10 мм) -> 17 мм, 2 -> 35 мм, 3 -> 52 мм."""
    g = st.g
    dy = abs(g.nodes[e.b].y - g.nodes[e.a].y)
    return st.diag_dir.get(e.id, 1) * round(SLOPE * dy)


def check_geometry(st: Station):
    """Проверка чертежа: углы диагоналей, узлы на сетке."""
    g = st.g
    bad_angle, off_grid = [], []
    for e in g.edges.values():
        na, nb = g.nodes[e.a], g.nodes[e.b]
        dy = abs(nb.y - na.y)
        if dy > 1e-6:
            ang = math.degrees(math.atan2(dy, abs(nb.x - na.x)))
            if abs(ang - 30) > 1.0:
                bad_angle.append(round(ang, 1))
    for n in g.nodes.values():
        if abs(n.x - round(n.x)) > 1e-6 or abs(n.y - round(n.y)) > 1e-6:
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
