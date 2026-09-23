"""Маршрутизация передвижений на станции – раздел 3 пособия (табл. 3.1–3.3).

Маршрут – путь по схеме от светофора в сторону, куда он разрешает движение:
  * приём – от входного светофора до пути станции («на путь IП»);
  * отправление – от выходного светофора до перегона («с пути 3П»),
    на правильный или неправильный путь перегона;
  * простой маневровый (п. 3.3) – от светофора с маневровым показанием до первого
    попутного такого же светофора («до М4»), на путь станции («на 3П»), за встречный
    светофор на бесстрелочный участок («за М2») или до входного светофора («до ЧД»);
    за встречный светофор на стрелочную секцию маршрута нет.

Стрелка, пройденная по прямому ходу, – в плюсовом положении (+), по ответвлению – в
минусовом (−); стрелки съезда спаренные и пишутся парой «14/16». Из маршрутов с общим
началом и концом основной – с наименьшим числом отклонений по стрелкам (при равенстве –
самый короткий), остальные – вариантные. Охранные стрелки (в скобках) не вычисляются –
для них нужен анализ негабаритных участков (табл. 2.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from joints import Station, _nm, _numkey
from signals import Signal, _pos
from tables import THROAT_EVEN, THROAT_ODD, throat_of

EPS = 1e-6
MAX_PATHS = 400                          # на один светофор – схемы заданий дают десятки
SHUNT = ('man_dwarf', 'man_mast', 'exit_mast', 'exit_dwarf')   # есть маневровое показание


@dataclass
class Route:
    kind: str                            # приём | отправление | маневровый
    signal: Signal
    name: str                            # «на путь IП», «с пути 3П», «до М4»…
    note: str = ''                       # правильный / неправильный путь перегона
    switches: list = field(default_factory=list)   # [(стрелка или пара, '+' | '−')]
    sections: list = field(default_factory=list)   # имена участков по порядку
    legs: list = field(default_factory=list)       # [(ребро, t от, t до)] – для подсветки
    length: float = 0.0
    variant: bool = False
    key: list = field(default_factory=list)        # стрелки, определяющие вариантный маршрут

    @property
    def minus(self) -> int:
        return sum(p == '−' for _, p in self.switches)


class _Net:
    """Схема для обхода: стыки на рёбрах, светофоры у стыков, куски участков."""

    def __init__(self, st: Station):
        self.st = st
        g = st.g
        self.on_edge: dict[int, list] = {}
        for j in st.joints:
            self.on_edge.setdefault(j.edge, []).append(j)
        self.sigs: dict[int, list[Signal]] = {}
        for s in st.signals:
            self.sigs.setdefault(id(s.joint), []).append(s)
        self.pieces: dict[int, list] = {}           # ребро -> [(t0, t1, участок)]
        for sec in st.sections:
            for p in sec['pieces']:
                self.pieces.setdefault(p['edge'], []).append((p['t0'], p['t1'], sec))
        self.tracks = {f'{v}П' for v in st.track_names.values()}
        self.pair = {}                               # стрелка съезда -> «a/b»
        for c in st.crossovers:
            a, b = sorted((_nm(st, s) for s in c['switches']), key=_numkey)
            for s in c['switches']:
                self.pair[s] = f'{a}/{b}'
        self.g = g

    def section_after(self, edge: int, t: float, forward: bool):
        """Участок, в который попадаешь, проехав точку t ребра в данном направлении."""
        for t0, t1, sec in self.pieces.get(edge, []):
            if (forward and t0 - EPS <= t < t1 - EPS) or (not forward and t0 + EPS < t <= t1 + EPS):
                return sec
        return None

    def sections_of(self, edge: int, ta: float, tb: float) -> list:
        lo, hi = min(ta, tb), max(ta, tb)
        out = [(t0, sec) for t0, t1, sec in self.pieces.get(edge, []) if t0 < hi - EPS and t1 > lo + EPS]
        out.sort(key=lambda p: p[0], reverse=ta > tb)
        return [sec for _, sec in out]


def _ahead(net: _Net, edge: int, t: float, forward: bool):
    js = [j for j in net.on_edge.get(edge, []) if (j.t > t + EPS if forward else j.t < t - EPS)]
    return sorted(js, key=lambda j: j.t, reverse=not forward)


def _explore(net: _Net, sig: Signal, decide) -> list[Route]:
    """Все пути от светофора sig по ходу его разрешения; decide(ctx) решает у каждого стыка
    и на каждом конце: None – ехать дальше, 'stop' – пути нет, (имя, ...) – маршрут готов."""
    g, st = net.g, net.st
    out: list[Route] = []

    def finish(legs, sw, end_name, tail_sec=None, note=''):
        r = Route('', sig, end_name, note)
        r.legs = list(legs)
        r.switches = _merge_pairs(net, sw)
        secs = []
        for e, ta, tb in legs:
            secs += net.sections_of(e, ta, tb)
        if tail_sec is not None:
            secs.append(tail_sec)
            r.legs += [(p['edge'], p['t0'], p['t1']) for p in tail_sec['pieces']]
        for s in secs:                              # без повторов, по порядку
            if s['name'] and s['name'] not in r.sections:
                r.sections.append(s['name'])
        r.length = sum(abs(tb - ta) for e, ta, tb in legs)
        out.append(r)

    def walk(edge, t, node, legs, sw, seen):
        if len(out) >= MAX_PATHS or (edge, node) in seen:
            return
        seen = seen | {(edge, node)}
        e = g.edges[edge]
        forward = node == e.b
        L = g.length(e)
        for j in _ahead(net, edge, t, forward):
            here = legs + [(edge, t, j.t)]
            res = decide('joint', j=j, edge=edge, node=node, forward=forward, legs=here)
            if res == 'stop':
                return
            if res is not None:
                finish(here, sw, *res)
                return
        legs = legs + [(edge, t, L if forward else 0.0)]
        deg = g.degree(node)
        if deg == 1:
            res = decide('end', node=node, legs=legs)
            if res not in (None, 'stop'):
                finish(legs, sw, *res)
            return
        if node in st.sw:
            info = st.sw[node]
            if edge == info['trunk']:
                nexts = [(info['straight'], '+'), (info['branch'], '−')]
            else:
                nexts = [(info['trunk'], '+' if edge == info['straight'] else '−')]
            for k, pos in nexts:
                f = g.edges[k]
                walk(k, 0.0 if f.a == node else g.length(f), g.other(f, node), legs,
                     sw + [(node, pos)], seen)
            return
        f = next((x for x in g.incident(node) if x.id != edge), None)   # излом
        if f is not None:
            walk(f.id, 0.0 if f.a == node else g.length(f), g.other(f, node), legs, sw, seen)

    walk(sig.joint.edge, sig.joint.t, sig.toward, [], [], frozenset())
    return out


def _merge_pairs(net: _Net, sw: list) -> list:
    """Стрелки по порядку прохода; стрелки одного съезда – одной парой."""
    out, seen = [], {}
    for n, pos in sw:
        name = net.pair.get(n) or _nm(net.st, n)
        if name in seen:
            if pos == '−':                          # пара едет по съезду – минус
                out[seen[name]] = (name, '−')
            continue
        seen[name] = len(out)
        out.append((name, pos))
    return out


def _signals_at(net: _Net, j, node):
    """Светофоры у стыка j: попутные (разрешают движение к node) и встречные."""
    sigs = net.sigs.get(id(j), [])
    return [s for s in sigs if s.toward == node], [s for s in sigs if s.toward != node]


def _peregon_note(st: Station, end: int, departure: bool) -> str:
    """Главный путь перегона: «Д» у входного – путь, по которому отсюда уходят поезда
    (для них он правильный); без «Д» – путь приёма."""
    wrong = not st.entry_names.get(end, '').endswith('Д')
    if departure:
        return 'на неправ. путь' if wrong else 'на прав. путь'
    return 'с неправ. пути' if not wrong else 'с прав. пути'


def _train_routes(net: _Net) -> list[Route]:
    st, g = net.st, net.g
    out = []
    for sig in st.signals:
        if sig.kind == 'entry':
            end = next((n for n, _ in st.entry_names.items()
                        if g.degree(n) == 1 and sig.joint.edge == g.incident(n)[0].id), None)

            def decide(what, **c):
                if what == 'end':
                    return 'stop'
                sec = net.section_after(c['edge'], c['j'].t, c['forward'])
                if sec is None:
                    return None
                if sec['name'] in net.tracks:
                    return (f'на путь {sec["name"]}', sec, _peregon_note(st, end, False) if end is not None else '')
                if sec['name'] == 'перегон':
                    return 'stop'
                return None
            rs = _explore(net, sig, decide)
            for r in rs:
                r.kind = 'приём'
            out += rs
        elif sig.kind.startswith('exit'):
            start_track = net.section_after(sig.joint.edge, sig.joint.t, not _forward(net, sig))

            def decide(what, **c):
                if what == 'end':
                    return 'stop'
                sec = net.section_after(c['edge'], c['j'].t, c['forward'])
                if sec is None:
                    return None
                if sec['name'] in net.tracks:
                    return 'stop'                    # через другой путь станции не отправляют
                if sec['name'] == 'перегон':
                    end = _peregon_end(net, c['edge'], c['forward'])
                    return (f'с пути {start_track["name"] if start_track else "?"}', None,
                            _peregon_note(st, end, True) if end is not None else '')
                return None
            rs = _explore(net, sig, decide)
            for r in rs:
                r.kind = 'отправление'
            out += rs
    return out


def _forward(net: _Net, sig: Signal) -> bool:
    return sig.toward == net.g.edges[sig.joint.edge].b


def _peregon_end(net: _Net, edge: int, forward: bool):
    """Конец перегона, к которому ведёт ребро (через изломы)."""
    g = net.g
    e = g.edges[edge]
    node, prev = (e.b if forward else e.a), edge
    for _ in range(100):
        if g.degree(node) == 1:
            return node
        if g.degree(node) != 2:
            return None
        f = next(x for x in g.incident(node) if x.id != prev)
        node, prev = g.other(f, node), f.id
    return None


def _shunt_routes(net: _Net) -> list[Route]:
    st = net.st
    out = []
    for sig in st.signals:
        if sig.kind not in SHUNT:
            continue

        def decide(what, **c):
            if what == 'end':
                n = net.g.nodes[c['node']]
                if n.mark in ('tupik', 'pp') and c['node'] not in st.safety:
                    return (f'на {n.label or ("п/п" if n.mark == "pp" else "тупик")}',)
                return 'stop'
            j, node = c['j'], c['node']
            same, other = _signals_at(net, j, node)
            if any(s.kind in SHUNT for s in same):
                return (f'до {next(s for s in same if s.kind in SHUNT).name}',)
            sec = net.section_after(c['edge'], j.t, c['forward'])
            entry = next((s for s in other if s.kind == 'entry'), None)
            if entry is not None or (sec is not None and sec['name'] == 'перегон'):
                return (f'до {entry.name}',) if entry else 'stop'
            if sec is None:
                return None
            if other:
                if sec['switches']:
                    return 'stop'                    # за встречный – только на бесстрелочный участок
                name = f'на {sec["name"]}' if sec['name'] in net.tracks else f'за {other[0].name}'
                return (name, sec)
            if sec['name'] in net.tracks:
                return (f'на {sec["name"]}', sec)
            return None
        rs = _explore(net, sig, decide)
        for r in rs:
            r.kind = 'маневровый'
        out += rs
    return out


def _mark_variants(routes: list[Route]):
    """Основной – с наименьшим числом минусовых стрелок, затем самый короткий."""
    groups: dict[tuple, list[Route]] = {}
    for r in routes:
        groups.setdefault((r.kind, id(r.signal), r.name, r.note), []).append(r)
    for rs in groups.values():
        rs.sort(key=lambda r: (r.minus, r.length))
        main = dict(rs[0].switches)
        for r in rs[1:]:
            r.variant = True
            r.key = [(n, p) for n, p in r.switches if main.get(n) != p]


def compute(st: Station) -> list[Route]:
    """Все маршруты станции – в порядке таблиц пособия: основные поездные (приём,
    отправление), вариантные поездные, маневровые; внутри – по горловинам."""
    net = _Net(st)
    train = _dedupe(_train_routes(net))
    shunt = _dedupe(_shunt_routes(net))
    _mark_variants(train)
    _mark_variants(shunt)
    left = THROAT_EVEN if st.odd_right else THROAT_ODD
    kinds = {'приём': 0, 'отправление': 1, 'маневровый': 2}

    def key(r: Route):
        x = _pos(st, r.signal.joint)[0]
        return (r.kind == 'маневровый', r.variant, throat_of(st, x) != left, kinds[r.kind],
                _natural(r.signal.name), r.note, _natural(r.name), r.minus, r.length)
    return sorted(train + shunt, key=key)


def _dedupe(routes: list[Route]) -> list[Route]:
    seen, out = set(), []
    for r in routes:
        k = (r.kind, id(r.signal), r.name, r.note, tuple(r.switches))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _natural(s: str):
    """Ключ сортировки «как у людей»: IП, IIП, 3П, 4П… 10П; М2, М4… М10."""
    s = s.replace('IIП', '2П').replace('IП', '1П')
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'(\d+)', s) if p]


def route_rows(st: Station) -> list[dict]:
    """Маршруты для интерфейса и ведомости: номер, горловина, геометрия для подсветки."""
    g = st.g
    index = {id(s): i for i, s in enumerate(st.signals)}
    rows = []
    for no, r in enumerate(compute(st), 1):
        segs = []
        for e, ta, tb in r.legs:
            if abs(tb - ta) < EPS:
                continue
            (x0, y0), (x1, y1) = g.point_on(g.edges[e], ta), g.point_on(g.edges[e], tb)
            segs.append([x0, y0, x1, y1])
        x = _pos(st, r.signal.joint)[0]
        rows.append({
            'id': no - 1, 'no': no, 'kind': r.kind, 'variant': r.variant,
            'throat': throat_of(st, x), 'signal': r.signal.name, 'signal_id': index[id(r.signal)],
            'name': r.name, 'note': r.note,
            'switches': [f'{p}{n}' for n, p in r.switches],
            'key': [f'{p}{n}' for n, p in r.key],
            'sections': r.sections, 'segs': segs,
        })
    return rows

