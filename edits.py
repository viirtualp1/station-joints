"""Ручные правки поверх автоматической расстановки.

Место на пути задаётся «локацией»: ребро графа, ближний к точке конец ребра (узел) и
расстояние от него в мм. Номера узлов и рёбер при компоновке не меняются, а длина
ребра у концов сохраняется (растягиваются середины путей), поэтому локация переживает
перекомпоновку (формат листов, направление) – правки переносятся по месту, а не
пропадают.

  стыки:     разница «по правилам» -> «как сейчас»: remove / add / negab
  светофоры: список правок по ключу (стык, направление): имя, тип, удалён, добавлен
  пути:      правка распознанного графа: удалить/добавить отрезок, тип конца
"""
from __future__ import annotations

import copy
import math

from graph import Graph, Joint
from joints import Station, analyse
from signals import KIND_TEXT, Signal

TOL = 1.5          # мм – стык «на том же месте»


# --------------------------------------------------------------------------- локации
def loc(st: Station, edge: int, t: float) -> dict:
    g = st.g
    e = g.edges[edge]
    L = g.length(e)
    return {'edge': edge, 'ref': e.a, 'dist': t} if t <= L / 2 else {'edge': edge, 'ref': e.b, 'dist': L - t}


def resolve(st: Station, lc: dict) -> float | None:
    """Локация -> расстояние от узла a ребра (или None, если ребра больше нет)."""
    g = st.g
    e = g.edges.get(lc['edge'])
    if e is None or lc['ref'] not in (e.a, e.b):
        return None
    L = g.length(e)
    t = lc['dist'] if lc['ref'] == e.a else L - lc['dist']
    m = min(0.5, L / 4)
    return min(max(t, m), L - m)


def _anchor_node(j: Joint) -> int | None:
    """Узел, от которого отсчитан стык (по нему к стыку привязаны светофоры б, в, г)."""
    a = j.anchor
    return a[0] if isinstance(a, tuple) and a and not isinstance(a[0], str) else None


def _nearest_joint(st: Station, edge: int, t: float, tol: float = TOL) -> Joint | None:
    best, bd = None, tol
    for j in st.joints:
        if j.edge == edge and abs(j.t - t) < bd:
            best, bd = j, abs(j.t - t)
    return best


# --------------------------------------------------------------------------- стыки
def diff_joints(rules: Station, cur: Station) -> list[dict]:
    """Правки стыков: чем текущая расстановка отличается от расстановки по правилам
    (обе – на одной и той же компоновке)."""
    ops = []
    free = list(cur.joints)
    for r in rules.joints:
        m = min((j for j in free if j.edge == r.edge and abs(j.t - r.t) < 0.3),
                key=lambda j: abs(j.t - r.t), default=None)
        if m is None:
            ops.append({'op': 'remove', **loc(rules, r.edge, r.t)})
            continue
        free.remove(m)
        if m.negab != r.negab:
            ops.append({'op': 'negab', 'value': m.negab, **loc(cur, m.edge, m.t)})
    for j in free:                              # добавленные и перенесённые
        op = {'op': 'add', 'rule': j.rule, 'negab': j.negab, 'fixed': j.fixed,
              'why': j.why, **loc(cur, j.edge, j.t)}
        if _anchor_node(j) is not None:
            op['anchor'] = _anchor_node(j)      # иначе у перенесённого стыка пропадёт светофор
        ops.append(op)
    return ops


def apply_joint_ops(st: Station, ops: list[dict]):
    for op in ops:
        t = resolve(st, op)
        if t is None:
            continue                            # ребра больше нет (правка путей)
        if op['op'] == 'remove':
            j = _nearest_joint(st, op['edge'], t)
            if j is not None:
                st.joints.remove(j)
        elif op['op'] == 'negab':
            j = _nearest_joint(st, op['edge'], t)
            if j is not None:
                j.negab, j.fixed = op['value'], True
        elif op['op'] == 'add':
            if _nearest_joint(st, op['edge'], t, 0.3) is None:
                e = st.g.edges[op['edge']]
                node = op.get('anchor')
                anchor = (node, t if node == e.a else st.g.length(e) - t) if node in (e.a, e.b) else None
                st.joints.append(Joint(op['edge'], t, op.get('rule', 'р'), op.get('negab', False),
                                       op.get('fixed', True), anchor=anchor, why=op.get('why', '')))


# --------------------------------------------------------------------------- светофоры
def sig_key(st: Station, joint: Joint, toward: int) -> dict:
    return {**loc(st, joint.edge, joint.t), 'toward': toward}


def _same(a: dict, b: dict) -> bool:
    return (a['edge'] == b['edge'] and a['toward'] == b['toward'] and a['ref'] == b['ref']
            and abs(a['dist'] - b['dist']) < TOL)


def edit_signal(sops: list[dict], key: dict, **change):
    """Добавить/обновить правку светофора с ключом key (change: name, kind, deleted, added)."""
    for o in sops:
        if _same(o, key):
            o.update(change)
            return
    sops.append({**key, **change})


def reset_signal(sops: list[dict], key: dict):
    sops[:] = [o for o in sops if not _same(o, key)]


def apply_signal_ops(st: Station, sops: list[dict]):
    for o in sops:
        t = resolve(st, o)
        if t is None or o['toward'] not in st.g.nodes:
            continue
        s = next((s for s in st.signals if s.joint.edge == o['edge'] and s.toward == o['toward']
                  and abs(s.joint.t - t) < TOL), None)
        kind = o.get('kind') if o.get('kind') in KIND_TEXT else None   # старый/битый файл
        if s is None and o.get('added'):
            j = _nearest_joint(st, o['edge'], t)
            if j is None:
                continue
            s = Signal(o.get('name', 'М'), kind or 'man_dwarf', j, o['toward'], why='добавлен вручную')
            st.signals.append(s)
        if s is None:
            continue
        if o.get('deleted'):
            st.signals.remove(s)
            continue
        if o.get('name'):
            s.name = o['name']
        if kind:
            s.kind = kind
        s.manual = True


# --------------------------------------------------------------------------- пути
def _scale(g0: Graph) -> float:
    """Пикселей распознанной картинки на мм миллиметровки (междупутье = 10 мм)."""
    return analyse(copy.deepcopy(g0)).u / 10.0


def to_source(g0: Graph, st: Station, x: float, y: float) -> tuple[float, float]:
    """Точка миллиметровки -> координаты распознанной картинки: от ближайшего узла
    с масштабом «междупутье»."""
    n = min(st.g.nodes.values(), key=lambda n: math.hypot(n.x - x, n.y - y))
    s = _scale(g0)
    m = g0.nodes[n.id]
    return m.x + (x - n.x) * s, m.y + (y - n.y) * s


def _point(g0: Graph, st: Station, p: dict) -> int:
    """Конец нового отрезка: узел, точка на ребре (ребро делится) или свободная точка."""
    if 'node' in p:
        if p['node'] not in g0.nodes:
            raise ValueError('узла нет')
        return int(p['node'])
    if 'edge' in p:
        eid = int(p['edge'])
        e0, e = g0.edges.get(eid), st.g.edges.get(eid)
        if e0 is None or e is None:
            raise ValueError('отрезка нет')
        f = min(max(float(p['t']) / (st.g.length(e) or 1), 0.05), 0.95)
        (ax, ay), (bx, by) = g0.pos(e0.a), g0.pos(e0.b)
        m = g0.add_node(ax + (bx - ax) * f, ay + (by - ay) * f)
        a, b = e0.a, e0.b
        g0.remove_edge(eid)
        g0.add_edge(a, m)
        g0.add_edge(m, b)
        return m
    x, y = to_source(g0, st, float(p['x']), float(p['y']))
    return g0.add_node(x, y)


def add_edge(g0: Graph, st: Station, a: dict, b: dict):
    na = _point(g0, st, a)
    nb = _point(g0, st, b)
    if na == nb:
        raise ValueError('отрезок нулевой длины')
    if g0.add_edge(na, nb) is None:
        raise ValueError('отрезок не добавлен')


def chain(g: Graph, eid: int) -> list[int]:
    """Отрезок «от стрелки до стрелки/конца»: ребро и соседние через изломы (узлы степени 2)."""
    out, stack = {eid}, [eid]
    while stack:
        e = g.edges[stack.pop()]
        for n in (e.a, e.b):
            if g.degree(n) != 2:
                continue
            for f in g.incident(n):
                if f.id not in out:
                    out.add(f.id)
                    stack.append(f.id)
    return sorted(out)


def delete_edge(g0: Graph, eid: int):
    """Удалить отрезок целиком (через изломы) и оставшиеся без путей узлы."""
    if eid not in g0.edges:
        raise ValueError('отрезка нет')
    ids = chain(g0, eid)
    ends = {n for i in ids for n in (g0.edges[i].a, g0.edges[i].b)}
    for i in ids:
        g0.remove_edge(i)
    for n in ends:
        if n in g0.nodes and g0.degree(n) == 0:
            g0.nodes.pop(n)


def set_end(g0: Graph, nid: int, mark: str | None):
    n = g0.nodes.get(nid)
    if n is None or g0.degree(nid) != 1:
        raise ValueError('это не конец пути')
    if mark not in ('tupik', 'peregon', 'pp', None):
        raise ValueError(f'неизвестный тип конца: {mark}')
    n.mark = mark
    n.fixed_mark = mark is not None             # тип задан вручную – не угадывать заново
