"""Правила методички ДВГУПС (п. 2.2–2.5), проверенные по рисункам пособия."""
from conftest import built

from joints import _walk
from render import REC_PX, Recorder, render
from signals import footprint


def _between(st, line, a, b):
    """Рёбра пути line между узлами a и b (по x)."""
    g = st.g
    xa, xb = sorted((g.nodes[a].x, g.nodes[b].x))
    return [k for k in line['edges']
            if xa - 1e-6 <= min(g.nodes[g.edges[k].a].x, g.nodes[g.edges[k].b].x)
            and max(g.nodes[g.edges[k].a].x, g.nodes[g.edges[k].b].x) <= xb + 1e-6]


def _facing_away(st, line, a, b):
    """Рис. 2.6 б, в / рис. 2.7: ответвление левой стрелки уходит вправо, правой – влево,
    т. е. передвижения по ответвлениям не занимают отрезок между стрелками."""
    ia, ib = st.sw[a], st.sw[b]
    if ia['branch'] in line['edges'] or ib['branch'] in line['edges']:
        return False
    return ia['bdx'] > 0 > ib['bdx']


def test_rule_zh_only_between_facing_away_switches(sample):
    """«ж» на пути ставится только между стрелками, по ответвлениям которых возможны
    параллельные передвижения (рис. 2.7: нет стыков 26–18, 32–20, 14–6, 6–4)."""
    st, _ = built(sample)
    g = st.g
    for line in st.lines:
        sws = [n for n in line['nodes'] if n in st.sw]
        for a, b in zip(sws, sws[1:]):
            ks = set(_between(st, line, a, b))
            zh = [j for j in st.joints if j.rule == 'ж' and j.edge in ks]
            if zh:
                assert _facing_away(st, line, a, b), (g.nodes[a].number, g.nodes[b].number)


def test_rule_zh_separates_parallel_movements(sample):
    """…и такие стрелки всегда в разных участках (стык 20–14 на рис. 2.7)."""
    st, _ = built(sample)
    for line in st.lines:
        sws = [n for n in line['nodes'] if n in st.sw]
        for a, b in zip(sws, sws[1:]):
            if _facing_away(st, line, a, b):
                ks = set(_between(st, line, a, b))
                assert any(j.edge in ks for j in st.joints), \
                    (st.g.nodes[a].number, st.g.nodes[b].number)


def test_rule_z_safety_dead_end():
    """Рис. 2.7, стрелка 36: у стрелки в предохранительный тупик – один стык «з» со
    стороны станции; ответвление-тупик стыком не отделяется и номера (…Т) не получает."""
    st, _ = built('var97')
    g = st.g
    assert len(st.safety) == 1
    (end, s), = st.safety.items()
    assert g.nodes[end].label is None
    z = [j for j in st.joints if j.rule == 'з']
    assert [j.edge for j in z] == [st.sw[s]['straight']]
    stub, _ = _walk(st, s, st.sw[s]['branch'])
    assert not [j for j in st.joints if j.edge in {e.id for e in stub}]
    # остальные тупики пронумерованы подряд: нечётные 1Т, 3Т…, чётные 2Т, 4Т…
    labels = sorted(int(n.label[:-1]) for n in g.nodes.values() if n.label and n.label.endswith('Т'))
    odd, even = [v for v in labels if v % 2], [v for v in labels if not v % 2]
    assert odd == list(range(1, 2 * len(odd), 2)) and even == list(range(2, 2 * len(even) + 1, 2))


def test_no_safety_dead_ends_on_regular_tupiks():
    for name in ('var91', 'var96'):
        st, _ = built(name)
        assert st.safety == {}
        assert not [j for j in st.joints if j.rule == 'з']


def test_dwarf_exit_lamps_rows():
    """Рис. 2.17 (Н5, Н6, Н7, Н9): у карликового выходного к пути ближе ряд
    заглушка–зелёный–жёлтый, красный и лунно-белый – в дальнем ряду."""
    st, _ = built('var96')
    g = st.g
    rec = Recorder(REC_PX)
    render(st, (1, 1), record=rec)
    lamps = [it for it in rec.items if it['t'] == 'circle' and it['g'] == 'signals']
    checked = 0
    for s in st.signals:
        e = g.edges[s.joint.edge]
        if s.kind != 'exit_dwarf' or abs(g.nodes[e.a].y - g.nodes[e.b].y) > 1e-6:
            continue
        x0, y0, x1, y1 = footprint(st, s)
        track_y = g.nodes[e.a].y
        mine = [c for c in lamps if x0 <= c['x'] <= x1 and y0 <= c['y'] <= y1 and c['r'] > 1.0]
        red = [c for c in mine if c['f'] == '#000000']
        assert len(red) == 1, s.name
        nearest = min(abs(c['y'] - track_y) for c in mine)
        assert abs(red[0]['y'] - track_y) > nearest + 1.0, s.name
        checked += 1
    assert checked >= 6


def test_signal_joints_have_signals(sample):
    """Стык «м» (под маневровый светофор для угловых заездов, рис. 2.18) без светофора
    не остаётся; у каждой стрелочной улицы такой светофор есть, если поместился."""
    st, _ = built(sample)
    used = {id(s.joint) for s in st.signals}
    assert all(id(j) in used for j in st.joints if j.rule == 'м')
    assert sum(s.group == 'г' for s in st.signals) >= 1
