"""Файлы, которые едут вместе с программой (иконки, пример схемы)."""
from __future__ import annotations

import os
import sys


def resource(name: str) -> str:
    """Путь к файлу рядом с программой – и внутри собранного PyInstaller'ом exe."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)
