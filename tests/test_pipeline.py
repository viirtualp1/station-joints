"""Весь конвейер на образцах заданий: распознавание -> компоновка -> стыки, светофоры,
участки -> сцена для интерфейса и экспорт."""
import json
import zipfile

import pytest
from conftest import built, parsed, sample_path

from checks import audit
from paper import SHEET_FORMATS
from render import render
from report import report
from scene import build_scene
from sheets import make_sheets, save_pdf
from vedomost import save_docx

# сколько чего на образцах: меняется только осознанно (правка правил) – тогда и здесь
EXPECTED = {
    'var91': dict(switches=34, joints=58, signals=33),
    'var96': dict(switches=29, joints=55, signals=33),
    'var97': dict(switches=34, joints=60, signals=32),
}


def test_counts(sample):
    st, _ = built(sample)
    exp = EXPECTED[sample]
    assert (len(st.sw), len(st.joints), len(st.signals)) == \
        (exp['switches'], exp['joints'], exp['signals'])


def test_audit_all_ok(sample):
    """Самопроверка по методичке (разделы 2.2–2.5) проходит на всех образцах."""
    st, _ = built(sample)
    bad = [f'{what}: {why}' for ok, what, why in audit(st) if not ok]
    assert bad == []


@pytest.mark.parametrize('fmt', SHEET_FORMATS)
def test_two_sheets_audit_ok(fmt):
    st, _ = built('var96', sheet_fmt=fmt)
    assert st.sheet_cut is not None
    assert [what for ok, what, _ in audit(st) if not ok] == []


def test_odd_left_audit_ok(sample):
    st, _ = built(sample, odd_right=False)
    assert [what for ok, what, _ in audit(st) if not ok] == []


def test_layout_keeps_topology(sample):
    """Перенос на сетку и раздвижка не меняют порядок узлов: ни один узел не оказывается
    посреди чужого ребра (было на var97: две близкие стрелки менялись местами)."""
    import math
    st, _ = built(sample)
    g = st.g
    for e in g.edges.values():
        (ax, ay), (bx, by) = g.pos(e.a), g.pos(e.b)
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        for n in g.nodes.values():
            if n.id in (e.a, e.b):
                continue
            t = ((n.x - ax) * (bx - ax) + (n.y - ay) * (by - ay)) / L2
            if 0.01 < t < 0.99:
                assert math.hypot(n.x - ax - t * (bx - ax), n.y - ay - t * (by - ay)) > 0.5, (e.id, n.id)


def test_deterministic(sample):
    """Одна и та же картинка – одна и та же схема (на этом держатся файлы работ)."""
    a = build_scene(*built(sample))
    b = build_scene(*built(sample))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_scene_is_json(sample):
    sc = build_scene(*built(sample))
    json.dumps(sc)
    assert sc['joints'] and sc['signals'] and sc['sections'] and sc['items']
    assert set(sc['signal_kinds']) == {'entry', 'exit_mast', 'exit_dwarf', 'man_dwarf', 'man_mast'}


def test_exports(tmp_path):
    st, an = built('var96', sheet_fmt='A3')
    img, _ = render(st, (800, 400), annots=an)
    assert img.size == (800, 400)
    pages = make_sheets(st, an, fmt='A3')
    assert len(pages) == 2
    save_pdf(pages, str(tmp_path / 'x.pdf'))
    assert (tmp_path / 'x.pdf').read_bytes()[:4] == b'%PDF'
    save_docx(st, str(tmp_path / 'x.docx'), 'тест')
    with zipfile.ZipFile(tmp_path / 'x.docx') as z:
        doc = z.read('word/document.xml').decode('utf-8')
    assert 'Изолирующие стыки' in doc and 'Светофоры' in doc
    assert 'Стыков' in report(st)


def test_not_a_scheme(tmp_path):
    """Картинка без схемы – понятная ошибка, а не «min() arg is an empty sequence»."""
    import numpy as np
    from PIL import Image
    p = tmp_path / 'blank.png'
    Image.fromarray(np.full((300, 600), 255, np.uint8)).save(p)
    from parser import parse_image
    with pytest.raises(ValueError, match='не найдена схема станции'):
        parse_image(str(p))


def test_parse_cyrillic_path(tmp_path):
    p = tmp_path / 'схема станции.png'
    p.write_bytes(open(sample_path('var96'), 'rb').read())
    from parser import parse_image
    assert parse_image(str(p))['graph'].switches()


def test_parsed_graph_stable():
    g = parsed('var96')['graph']
    assert len(g.switches()) == 29
