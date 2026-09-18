"""Граф путевого развития: узлы (концы, изломы, стрелки) и прямые рёбра между ними."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Node:
    id: int
    x: float
    y: float
    mark: str | None = None      # 'tupik' | 'pp' | 'peregon' для концов
    number: str | None = None    # номер стрелки по методичке
    label: str | None = None     # имя конца пути: тупик «1Т», «2Т»…


@dataclass
class Edge:
    id: int
    a: int
    b: int


@dataclass
class Joint:
    edge: int
    t: float                     # расстояние от узла edge.a вдоль ребра
    rule: str                    # буква правила методички (а..и) или 'р' – ручной
    negab: bool = False          # негабаритный (в окружности)
    fixed: bool = False          # габаритность задана правилом/вручную, не пересчитывать
    anchor: object = None        # (узел, желаемое расстояние) | ('between', da, db) | None


@dataclass
class Annotation:
    """Надписи/мелкие элементы картинки (п/п, номер варианта) – рисуются как есть."""
    x0: int
    y0: int
    x1: int
    y1: int
    mask: object                 # numpy bool array
    scale: float = 1.0           # размер пикселя маски в единицах модели


class Graph:
    def __init__(self):
        self.nodes: dict[int, Node] = {}
        self.edges: dict[int, Edge] = {}
        self._nid = 0
        self._eid = 0

    # --- базовые операции -------------------------------------------------
    def add_node(self, x, y, mark=None) -> int:
        self._nid += 1
        self.nodes[self._nid] = Node(self._nid, float(x), float(y), mark)
        return self._nid

    def add_edge(self, a, b) -> int | None:
        if a == b:
            return None
        for e in self.edges.values():
            if {e.a, e.b} == {a, b}:
                return e.id
        self._eid += 1
        self.edges[self._eid] = Edge(self._eid, a, b)
        return self._eid

    def remove_edge(self, eid):
        self.edges.pop(eid, None)

    def remove_node(self, nid):
        for e in self.incident(nid):
            self.remove_edge(e.id)
        self.nodes.pop(nid, None)

    def incident(self, nid) -> list[Edge]:
        return [e for e in self.edges.values() if e.a == nid or e.b == nid]

    def degree(self, nid) -> int:
        return len(self.incident(nid))

    @staticmethod
    def other(e: Edge, nid) -> int:
        return e.b if e.a == nid else e.a

    def pos(self, nid):
        n = self.nodes[nid]
        return n.x, n.y

    def length(self, e: Edge) -> float:
        (x0, y0), (x1, y1) = self.pos(e.a), self.pos(e.b)
        return math.hypot(x1 - x0, y1 - y0)

    def direction(self, e: Edge, from_node) -> tuple[float, float]:
        """Единичный вектор ребра, выходящий из from_node."""
        x0, y0 = self.pos(from_node)
        x1, y1 = self.pos(self.other(e, from_node))
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        return (x1 - x0) / L, (y1 - y0) / L

    def is_horizontal(self, e: Edge, tol_deg=10) -> bool:
        (x0, y0), (x1, y1) = self.pos(e.a), self.pos(e.b)
        return abs(y1 - y0) <= math.tan(math.radians(tol_deg)) * abs(x1 - x0)

    def point_on(self, e: Edge, t: float):
        (x0, y0), (x1, y1) = self.pos(e.a), self.pos(e.b)
        L = self.length(e) or 1.0
        k = t / L
        return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k

    def kind(self, nid) -> str:
        d = self.degree(nid)
        return {0: 'isolated', 1: 'end', 2: 'bend', 3: 'switch'}.get(d, 'complex')

    def switches(self) -> list[int]:
        return [n for n in self.nodes if self.degree(n) == 3]

    def merge_nodes(self, keep, drop):
        """Стягивает узел drop в keep."""
        for e in self.incident(drop):
            o = self.other(e, drop)
            self.remove_edge(e.id)
            if o != keep:
                self.add_edge(keep, o)
        dn = self.nodes.pop(drop)
        kn = self.nodes[keep]
        kn.mark = kn.mark or dn.mark

    def dissolve(self, nid):
        """Убирает узел степени 2, соединяя соседей напрямую."""
        inc = self.incident(nid)
        if len(inc) != 2:
            return
        a, b = self.other(inc[0], nid), self.other(inc[1], nid)
        self.remove_node(nid)
        self.add_edge(a, b)

    def bbox(self):
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return min(xs), min(ys), max(xs), max(ys)
