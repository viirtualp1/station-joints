"""Общие данные тестов: образцы заданий из samples/ (распознаются один раз)."""
import copy
import functools
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from layout import build_station  # noqa: E402
from parser import parse_image  # noqa: E402

SAMPLES = ['var91', 'var96', 'var97']


def sample_path(name: str) -> str:
    return os.path.join(ROOT, 'samples', f'{name}_pdf.png')


@functools.lru_cache(maxsize=None)
def _parsed(name: str):
    return parse_image(sample_path(name))


def parsed(name: str):
    """Результат распознавания (копия – тесты могут менять граф)."""
    return copy.deepcopy(_parsed(name))


def built(name: str, **kw):
    """Станция после компоновки и расстановки: (Station, надписи)."""
    r = parsed(name)
    return build_station(r['graph'], r['annots'], **kw)


@pytest.fixture(params=SAMPLES)
def sample(request):
    return request.param
