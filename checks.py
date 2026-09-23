"""Проверка построенной схемы по методическому пособию (разделы 2.2–2.5).

Каждая проверка: (ok, «пункт пособия – что проверено», подробности при ошибке).
"""
from __future__ import annotations

from joints import Station, _nm, _walk_to_switch
from signals import _overlap, footprint


def _digits(name: str) -> int | None:
    """Номер в имени («М12» -> 12, «3Т» -> 3); None – имя не по шаблону (правка вручную)."""
    d = ''.join(ch for ch in name if ch.isdigit())
    return int(d) if d else None


def _num(st: Station, s) -> int:
    """Номер стрелки числом (0 – если не пронумерована)."""
    return int(st.g.nodes[s].number or 0)


def audit(st: Station) -> list[tuple[bool, str, str]]:
    g = st.g
    out = []

    def check(ok, what, bad=''):
        out.append((bool(ok), what, '' if ok else bad))

    # 2.2 нумерация путей
    names = {l['name']: l for l in st.lines if 'name' in l}
    main_names = sorted(l.get('name', '?') for l in st.mains)
    check(main_names == ['I', 'II'] or main_names == ['I'],
          '2.2 главные пути I и II', f'главные: {main_names}')
    bad = []
    if 'I' in names and 'II' in names:
        yI, yII = names['I']['y'], names['II']['y']
        for nm, l in names.items():
            if nm in ('I', 'II'):
                continue
            odd = int(nm) % 2 == 1
            if odd and not l['y'] > max(yI, yII) and yI > yII:
                bad.append(nm)
            if not odd and not l['y'] < min(yI, yII) and yI > yII:
                bad.append(nm)
    check(not bad, '2.2 нечётные пути со стороны I, чётные – со стороны II', ', '.join(bad))

    bad = []
    for n in g.nodes.values():
        if not n.label:
            continue
        _, cur = _walk_to_switch(st, n.id)
        num = _digits(n.label)
        if cur and (num is None or num % 2 != _num(st, cur) % 2):
            bad.append(n.label)
    check(not bad, '2.2 тупики: в нечётной горловине – нечётные, в чётной – чётные (…Т)',
          ', '.join(bad))

    # 2.3 нумерация стрелок
    bad = [_nm(st, s) for s in st.sw if g.nodes[s].number and
           (_num(st, s) % 2 == 1) != st.odd_side(g.nodes[s].x)]
    nums = [g.nodes[s].number or '' for s in st.sw]
    dup = {n for n in nums if nums.count(n) > 1}
    check(not bad and not dup and all(nums),
          '2.3 стрелки: нечётная горловина – нечётные, чётная – чётные, без повторов',
          f'не в своей горловине: {bad}; повторы: {sorted(dup)}')
    bad = []
    for c in st.crossovers:
        a, b = (_num(st, s) for s in c['switches'])
        if abs(a - b) != 2:
            bad.append(f'{a}/{b}')
    for c in st.ladders:
        ns = sorted(_num(st, s) for s in c['switches'])
        if any(y - x != 2 for x, y in zip(ns, ns[1:])):
            bad.append('улица ' + ','.join(map(str, ns)))
    check(not bad, '2.3 стрелки съездов и стрелочных улиц – непрерывная нумерация', '; '.join(bad))

    # 2.4 стыки
    secs = st.sections
    sec_of = {}
    for i, s in enumerate(secs):
        for n in s['nodes']:
            sec_of[n] = i
    bad = [s['name'] for s in secs if len(s['switches']) > 3]
    check(not bad, '2.4 и) в стрелочном участке не более 3 стрелок', ', '.join(bad))
    bad = [f"{_nm(st, a)}/{_nm(st, b)}" for c in st.crossovers
           for a, b in [c['switches']] if sec_of.get(a) == sec_of.get(b)]
    check(not bad, '2.4 ж) стрелки съезда – в разных участках', ', '.join(bad))
    bad = []
    for c in st.ladders:
        for a, b in zip(c['switches'], c['switches'][1:]):
            if sec_of.get(a) == sec_of.get(b):
                bad.append(f'{_nm(st, a)}-{_nm(st, b)}')
    check(not bad, '2.4 е) каждая стрелка стрелочной улицы – в отдельной РЦ', ', '.join(bad))
    bad = []
    for n in g.nodes.values():
        if g.degree(n.id) == 1 and n.mark in ('tupik', 'pp') and n.id not in st.safety:
            s = secs[sec_of[n.id]] if n.id in sec_of else None
            if s and s['switches']:
                bad.append(n.label or n.mark)
    check(not bad, '2.4 г) тупики и подъездные пути отделены от зоны централизации',
          ', '.join(bad))
    bad = [sig for sig, ok, _ in st.entry_check if not ok]
    check(not bad, '2.4 в) за каждым входным – бесстрелочный участок (НП, НДП, ЧП, ЧДП)',
          ', '.join(bad))
    bad = [nm for nm, l in names.items() if l.get('central') not in g.edges or
           sum(1 for j in st.joints if j.edge == l['central'] and j.rule == 'б') < 1]
    check(not bad, '2.4 б) пути станции выделены в отдельные участки', ', '.join(bad))

    # 2.5 светофоры
    sigs = st.signals
    bad = [s.name for s in sigs if s.kind in ('entry', 'exit_mast', 'exit_dwarf')
           and s.joint.negab]
    check(not bad, '2.5 поездные светофоры – у габаритных стыков', ', '.join(bad))
    for left, pair in ((True, ('Н', 'НД')), (False, ('Ч', 'ЧД'))):
        xs = {s.name: round(g.point_on(g.edges[s.joint.edge], s.joint.t)[0], 1)
              for s in sigs if s.kind == 'entry' and s.name in pair}
        if len(xs) == 2:
            check(len(set(xs.values())) == 1,
                  f'2.5 входные {pair[0]} и {pair[1]} – на одном уровне', str(xs))
    have = {s.name for s in sigs}
    bad = []
    for nm, l in names.items():
        num = {'I': '1', 'II': '2'}.get(nm, nm)
        for letter in ('Н', 'Ч'):
            if f'{letter}{num}' not in have:
                bad.append(f'{letter}{num}')
    check(not bad, '2.5 выходные с обоих концов каждого пути (пути обезличены)', ', '.join(bad))
    bad = [s.name for s in sigs if s.kind == 'exit_mast' and not any(
        s.joint.edge == l.get('central') for l in st.mains)]
    check(not bad, '2.5 мачтовые выходные – только с главных путей', ', '.join(bad))
    man = [s for s in sigs if s.kind.startswith('man')]
    bad = []
    for odd in (True, False):
        side = sorted((s for s in man if st.odd_side(g.point_on(g.edges[s.joint.edge], s.joint.t)[0]) == odd),
                      key=lambda s: abs(g.point_on(g.edges[s.joint.edge], s.joint.t)[0] - st.xc),
                      reverse=True)
        nums = [_digits(s.name) for s in side]
        ns = [n for n in nums if n is not None]
        if len(ns) < len(nums) or any(n % 2 != (1 if odd else 0) for n in ns) or ns != sorted(ns):
            bad.append('нечётная' if odd else 'чётная')
    check(not bad, '2.5 маневровые: нечётные/чётные по горловинам, номера растут к оси',
          ', '.join(bad))
    boxes = [(s.name, footprint(st, s)) for s in sigs]
    bad = [f'{a}/{b}' for i, (a, ba) in enumerate(boxes) for b, bb in boxes[i + 1:]
           if _overlap(ba, bb)]
    check(not bad, 'чертёж: обозначения светофоров не накладываются', ', '.join(bad))

    # геометрия
    if st.geom_check is not None:
        bad_ang, off = st.geom_check
        check(not bad_ang and not off,
              'чертёж: диагонали 15×10 мм, узлы на сетке 5 мм, пути на линиях 10 мм',
              f'наклон: {bad_ang}; вне сетки: {len(off)}')
    return out


def audit_text(st: Station) -> list[str]:
    res = audit(st)
    ok = sum(1 for r in res if r[0])
    lines = [f'Проверка по методичке: {ok} из {len(res)} пунктов в норме']
    for good, what, bad in res:
        lines.append(f"  {'✓' if good else '✗'} {what}" + (f'  — {bad}' if bad else ''))
    return lines
