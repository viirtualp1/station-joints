"""Команды бэкенда (server.Session): правки, отмена, файлы работ, защита от ошибок."""
import json

import pytest
from conftest import sample_path

import server
from server import Server, Session


@pytest.fixture
def ses():
    s = Session()
    s.load(sample_path('var96'))
    return s


def _joints(res):
    return sorted((j['edge'], round(j['t'], 1)) for j in res['joints'])


def test_load_is_clean(ses):
    h = ses.scene_cmd()['history']
    assert h == {'undo': None, 'redo': None, 'dirty': False}


def test_undo_redo_all_joints_removed(ses):
    """Удалили все стыки – отмена/повтор и повторное открытие не возвращают стыки «по правилам»."""
    for _ in range(len(ses.st.joints)):
        ses.remove_joint(0)
    assert ses.st.joints == []
    ses.undo()
    ses.redo()
    assert ses.st.joints == []


def test_project_with_no_joints_roundtrip(ses, tmp_path):
    for _ in range(len(ses.st.joints)):
        ses.remove_joint(0)
    p = str(tmp_path / 'empty.stj')
    ses.save_project(p)
    t = Session()
    assert t.load(p)['joints'] == []


@pytest.mark.parametrize('bad', [-1, 10_000])
def test_bad_joint_index(ses, bad):
    n = len(ses.st.joints)
    with pytest.raises(ValueError, match='стык не найден'):
        ses.remove_joint(bad)
    with pytest.raises(ValueError):
        ses.toggle_negab(bad)
    assert len(ses.st.joints) == n
    assert ses.scene_cmd()['history']['undo'] is None


def test_bad_signal_kind_does_not_break_document(ses):
    with pytest.raises(ValueError, match='неизвестный тип'):
        ses.edit_signal(0, kind='bogus')
    ses.scene_cmd()                                # документ цел
    with pytest.raises(ValueError):
        ses.add_signal(0, ses.st.g.edges[ses.st.joints[0].edge].a, kind='bogus')


def test_add_joint_clamped(ses):
    e = next(iter(ses.st.g.edges.values()))
    L = ses.st.g.length(e)
    ses.add_joint(e.id, L + 100)
    j = ses.st.joints[-1]
    assert 0 < j.t < L
    with pytest.raises(ValueError):
        ses.add_joint(99_999, 1)


def test_dirty_tracks_saved_state(ses, tmp_path):
    ses.remove_joint(0)
    assert ses._history()['dirty']
    ses.undo()
    assert not ses._history()['dirty']             # вернулись к открытому состоянию
    ses.redo()
    p = str(tmp_path / 'a.stj')
    assert ses.save_project(p)['history']['dirty'] is False
    ses.toggle_negab(0)
    assert ses._history()['dirty']
    ses.undo()
    assert not ses._history()['dirty']
    ses.undo()                                     # раньше сохранения – снова «изменено»
    assert ses._history()['dirty']


def test_relayout_keeps_signal_of_moved_joint(ses):
    """Перенесённый вручную стык «б» после смены листа не теряет свой выходной светофор."""
    jb = next(i for i, j in enumerate(ses.st.joints) if j.rule == 'б')
    before = sorted(s.name for s in ses.st.signals)
    ses.move_joint(jb, ses.st.joints[jb].t + 5)
    res = ses.relayout(sheets='A3')
    assert res['kept'] >= 1
    assert sorted(s['name'] for s in res['signals']) == before
    assert not res['issues']
    res = ses.relayout(sheets=None)
    assert sorted(s['name'] for s in res['signals']) == before


def test_project_roundtrip(ses, tmp_path):
    ses.move_joint(10, ses.st.joints[10].t + 5)
    ses.edit_signal(0, name='XX')
    p = str(tmp_path / 'p.stj')
    ses.save_project(p)
    t = Session()
    res = t.load(p)
    assert _joints(res) == _joints(ses.scene())
    assert any(s['name'] == 'XX' for s in res['signals'])
    assert res['history']['dirty'] is False
    # старое имя сохраняется и после перекомпоновки
    assert any(s['name'] == 'XX' for s in t.relayout(odd_right=False)['signals'])


def test_restore_is_dirty(ses, tmp_path):
    ses.remove_joint(0)
    auto = str(tmp_path / 'auto' / 'doc_1.stj')
    ses.save_project(auto, autosave=True)
    assert ses._history()['dirty']                 # резервная копия – не сохранение
    t = Session()
    res = t.restore(auto, origin=sample_path('var96'))
    assert res['history']['dirty'] is True
    assert res['source']['project'] is None


def test_failed_track_edit_rolls_back(ses):
    before = _joints(ses.scene())
    with pytest.raises(ValueError, match='не получилось'):
        ses.edit_track('set_end', node=99_999, mark='tupik')
    assert _joints(ses.scene()) == before
    assert ses._history()['undo'] is None


def test_track_edit_and_undo(ses):
    sc = ses.scene()
    end = next(n for n in sc['nodes'] if n['end'] and n['mark'] == 'tupik')
    res = ses.edit_track('add_edge', a={'node': end['id']}, b={'x': end['x'], 'y': end['y'] - 25})
    assert res['history']['undo'] == 'новый отрезок'
    ses.undo()
    assert _joints(ses.scene()) == _joints(sc)


def test_explain_everything(ses):
    sc = ses.scene()
    for i in range(len(sc['joints'])):
        assert ses.explain('joint', i)['title']
    for i in range(len(sc['signals'])):
        assert ses.explain('signal', i)['title']
    for n in sc['nodes']:
        assert ses.explain('node', n['id'])['title']
    for s in sc['sections']:
        assert ses.explain('section', s['name'])['title']
    with pytest.raises(ValueError):
        ses.explain('joint', -1)


def test_server_protocol(monkeypatch, capsys):
    srv = Server()
    doc = srv.handle('new_doc', {})['doc']
    res = srv.handle('load', {'doc': doc, 'path': sample_path('var96')})
    assert res['history']['dirty'] is False
    with pytest.raises(ValueError, match='неизвестная команда'):
        srv.handle('nope', {})
    srv.handle('close_doc', {'doc': doc})
    with pytest.raises(ValueError, match='закрыт'):
        srv.handle('scene', {'doc': doc})
    assert server.VERSION >= 6


def test_main_loop_survives_errors(monkeypatch, capsys):
    import io
    import sys
    lines = [json.dumps({'id': 1, 'cmd': 'ping'}), 'not json', json.dumps({'id': 2, 'cmd': 'nope'})]
    monkeypatch.setattr(sys, 'stdin', io.StringIO('\n'.join(lines) + '\n'))
    out = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', out)
    server.main()
    resp = [json.loads(line) for line in out.getvalue().splitlines()]
    assert resp[0] == {'id': 1, 'ok': True, 'result': {'version': server.VERSION}}
    assert resp[1]['ok'] is False and resp[2]['ok'] is False
