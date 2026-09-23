"""Форматы листов и поля рамки (ГОСТ 2.301) – общие для компоновки на два листа
(layout.py) и печати (sheets.py). Все размеры – в мм, листы альбомные."""
from __future__ import annotations

FORMATS = [('A4', 297, 210), ('A3', 420, 297), ('A2', 594, 420), ('A1', 841, 594)]
OVERLAP = 10.0                        # полоса перекрытия двух листов для склейки
PAD = 4.0                             # отступ схемы от рамки
FIELD_L, FIELD = 20.0, 5.0            # поля рамки: слева 20, остальные 5
TITLE_H = 8.0                         # строка подписи листа внизу рамки
SHEET_FORMATS = ('A4', 'A3', 'A2')    # из чего выбирает пользователь в режиме «Два листа»


def usable_width(fmt: str) -> float:
    """Ширина рабочего поля листа формата fmt, мм."""
    fw = next((w for n, w, _ in FORMATS if n == fmt), None)
    if fw is None:
        raise ValueError(f'неизвестный формат листа: {fmt}')
    return fw - FIELD_L - FIELD - 2 * PAD


def fit_format(w: float, h: float) -> tuple[str, int, int]:
    """Наименьший формат, на рабочее поле которого помещается чертёж w × h мм."""
    for name, fw, fh in FORMATS:
        if w <= fw - FIELD_L - FIELD - 2 * PAD and h <= fh - 2 * FIELD - TITLE_H - 2 * PAD:
            return name, fw, fh
    return FORMATS[-1]
