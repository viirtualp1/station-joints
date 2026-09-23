"""Маршруты (раздел 3 пособия): поездные основные и вариантные, простые маневровые."""
from conftest import built

from routes import compute, route_rows


def test_every_entry_receives_on_every_track(sample):
    st, _ = built(sample)
    rows = route_rows(st)
    tracks = {f'{v}П' for v in st.track_names.values()}
    for e in (s for s in st.signals if s.kind == 'entry'):
        got = {r['name'].removeprefix('на путь ') for r in rows
               if r['kind'] == 'приём' and r['signal'] == e.name and not r['variant']}
        assert got == tracks, e.name


def test_departures_to_both_mains(sample):
    st, _ = built(sample)
    rows = route_rows(st)
    for x in (s for s in st.signals if s.kind.startswith('exit')):
        notes = {r['note'] for r in rows if r['kind'] == 'отправление' and r['signal'] == x.name
                 and not r['variant']}
        assert notes == {'на прав. путь', 'на неправ. путь'}, x.name


def test_switch_positions_consistent(sample):
    """Съезд – одной парой «a/b»; в маршруте стрелка встречается один раз."""
    st, _ = built(sample)
    for r in compute(st):
        names = [n for n, _ in r.switches]
        assert len(names) == len(set(names))
        assert all(p in '+−' for _, p in r.switches)


def test_main_route_has_fewest_deviations(sample):
    st, _ = built(sample)
    routes = compute(st)
    by = {}
    for r in routes:
        by.setdefault((r.kind, id(r.signal), r.name, r.note), []).append(r)
    for rs in by.values():
        main = [r for r in rs if not r.variant]
        assert len(main) == 1
        assert all(main[0].minus <= r.minus for r in rs)
        for r in rs:
            if r.variant:
                assert r.key, 'вариантный маршрут отличается положением стрелок'


def test_shunting_never_beyond_opposing_signal_onto_switches(sample):
    """П. 3.3: за встречный светофор – только на бесстрелочный участок."""
    st, _ = built(sample)
    secs = {s['name']: s for s in st.sections}
    for r in compute(st):
        if r.kind == 'маневровый' and r.name.startswith('за '):
            assert not secs[r.sections[-1]]['switches'], r.name


def test_route_names_follow_manual():
    st, _ = built('var96')
    rows = route_rows(st)
    names = {(r['signal'], r['name']) for r in rows}
    assert ('Ч', 'на путь IП') in names and ('Н1', 'с пути IП') in names
    # приём: сначала IП, IIП, потом 3П, 4П… (как в табл. 3.1)
    rec = [r['name'] for r in rows if r['kind'] == 'приём' and r['signal'] == 'Ч' and not r['variant']]
    assert rec[:3] == ['на путь IП', 'на путь IIП', 'на путь 3П']
    assert [r['no'] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r['segs'] for r in rows)
