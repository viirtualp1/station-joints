"""Печать схемы на двух листах в натуральную величину (1 мм схемы = 1 мм бумаги).

Пособие (п. 2.1): высота чертежа – по типовым форматам (210, 297, 420, 594, 840 мм),
длина не лимитируется. Длинную схему удобнее печатать двумя листами:
  * разрез – у оси станции: лист 1 – нечётная горловина, лист 2 – чётная;
  * место разреза выбирается там, где нет стрелок, стыков и светофоров;
  * на обоих листах повторяется полоса перекрытия OVERLAP мм с линией склейки;
  * формат – наименьший стандартный (A4…A1, альбомный), куда помещается половина;
  * рамка по ГОСТ 2.301: поле слева 20 мм, остальные – 5 мм.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw

from joints import Station
from paper import FIELD, FIELD_L, FORMATS, OVERLAP, PAD, TITLE_H, fit_format
from render import _font, render
from signals import drawing_bounds, footprint

DPI = 300
PX = DPI / 25.4                       # пикселей в 1 мм


def _busy(st: Station, annots=()):
    """Интервалы по x (мм), где резать нельзя: стрелки, стыки, светофоры, надписи."""
    g = st.g
    spans = []
    for s in st.sw:
        x = g.nodes[s].x
        spans.append((x - 6, x + 6))
    for j in st.joints:
        x = g.point_on(g.edges[j.edge], j.t)[0]
        spans.append((x - 4, x + 4))
    for s in st.signals:
        x0, _, x1, _ = footprint(st, s)
        spans.append((x0 - 2, x1 + 2))
    for a in annots:
        spans.append((a.x0 - 2, a.x1 + 2))
    return spans


def cut_x(st: Station, annots=()) -> float:
    """Ордината разреза: линия склейки пересекает как можно меньше обозначений
    (в полосе перекрытия они и так печатаются на обоих листах), при равенстве –
    ближе к оси станции. Ищем в средней трети схемы с шагом 0,5 мм."""
    spans = _busy(st, annots) + [(st.xc - 7, st.xc + 7)]    # номера путей у оси
    x0, _, x1, _ = st.g.bbox()
    lo, hi = x0 + (x1 - x0) / 3, x1 - (x1 - x0) / 3
    best = None
    for i in range(int((hi - lo) * 2) + 1):
        x = lo + i / 2
        key = (sum(1 for a, b in spans if a < x < b), abs(x - st.xc))
        if best is None or key < best[0]:
            best = (key, x)
    return best[1] if best else st.xc


def _edge(st: Station, x: float, side: int, annots=(), limit: float = 15.0) -> float:
    """Край части листа: обозначение (светофор, стрелка с номером, стык, надпись),
    попавшее на кромку, берём в часть целиком, а не оставляем обрезком.
    Один проход, сдвиг не больше limit мм."""
    out = x
    for b0, b1 in _busy(st, annots):
        if b0 < x < b1:
            out = max(out, b1) if side > 0 else min(out, b0)
    return min(out, x + limit) if side > 0 else max(out, x - limit)


def _bounds(st: Station, annots):
    return drawing_bounds(st, annots, pad=6)          # подписи номеров, упоры тупиков


def make_sheets(st: Station, annots=(), *, show_grid=False, show_letters=False,
                title='', fmt: str | None = None) -> list[Image.Image]:
    x0, y0, x1, y1 = _bounds(st, annots)
    xc = st.sheet_cut if st.sheet_cut is not None else cut_x(st, annots)
    parts = [(x0, _edge(st, xc + OVERLAP / 2, +1, annots)),
             (_edge(st, xc - OVERLAP / 2, -1, annots), x1)]
    hmax = y1 - y0
    fname, fw, fh = fit_format(max(b - a for a, b in parts), hmax)
    want = next((f for f in FORMATS if f[0] == fmt), None)
    if want and FORMATS.index(want) > FORMATS.index((fname, fw, fh)):
        fname, fw, fh = want                  # заданный формат, если схема в него влезает
    labels = ('нечётная горловина', 'чётная горловина')

    pages = []
    for i, (a, b) in enumerate(parts):
        W, H = round(fw * PX), round(fh * PX)
        page = Image.new('RGB', (W, H), 'white')
        # рабочее поле внутри рамки
        fx0, fy0 = FIELD_L, FIELD
        fx1, fy1 = fw - FIELD, fh - FIELD - TITLE_H
        iw, ih = round((fx1 - fx0) * PX), round((fy1 - fy0) * PX)
        # схема по центру поля по высоте; лист 1 прижат к правому краю (к разрезу),
        # лист 2 – к левому, чтобы полосы склейки были у кромки
        oy = ((fy1 - fy0) - hmax) / 2 - y0
        ox = ((fx1 - fx0) - PAD) - b if i == 0 else PAD - a
        img, _ = render(st, (iw, ih), view=(PX, ox * PX, oy * PX), annots=annots,
                        show_grid=False, show_letters=show_letters)
        # всё, что за пределами своей части, – закрашиваем
        d = ImageDraw.Draw(img)
        lx, rx = (a + ox) * PX, (b + ox) * PX
        d.rectangle([0, 0, lx, ih], fill='white')
        d.rectangle([rx, 0, iw, ih], fill='white')
        # светофор, оставшийся на кромке, – целиком на соседнем листе; здесь скрываем
        for sg in st.signals:
            b0, by0, b1, by1 = footprint(st, sg)
            if b0 < a < b1 or b0 < b < b1:
                d.rectangle([(b0 - 1 + ox) * PX, (by0 - 1 + oy) * PX,
                             (b1 + 1 + ox) * PX, (by1 + 1 + oy) * PX], fill='white')
        # полоса склейки: штриховая линия разреза и подпись
        cx = (xc + ox) * PX
        yy, dash = 0.0, 2.5 * PX
        while yy < ih:
            d.line([(cx, yy), (cx, min(yy + dash, ih))], fill=(200, 30, 30), width=3)
            yy += dash * 1.8
        f = _font(3.0 * PX)                     # подпись – внутри своего листа
        d.text((cx + (-1.5 * PX if i == 0 else 1.5 * PX), 3 * PX),
               'линия склейки', fill=(200, 30, 30), font=f, anchor='ra' if i == 0 else 'la')
        if show_grid:                           # миллиметровка на всё поле, в осях схемы
            img = ImageChops.multiply(_grid(iw, ih, ox, oy), img)
        page.paste(img, (round(fx0 * PX), round(fy0 * PX)))

        pd = ImageDraw.Draw(page)
        w = max(2, round(0.5 * PX))                     # основная линия рамки
        pd.rectangle([fx0 * PX, fy0 * PX, fx1 * PX, (fh - FIELD) * PX], outline='black',
                     width=w)
        pd.line([(fx0 * PX, fy1 * PX), (fx1 * PX, fy1 * PX)], fill='black', width=w)
        ft = _font(3.5 * PX)
        text = f'Лист {i + 1} из 2 · {labels[i]} · {fname}, М 1:1 (мм)'
        if title:
            text = f'{title} · ' + text
        pd.text(((fx0 + 3) * PX, (fy1 + TITLE_H / 2) * PX), text, fill='black', font=ft,
                anchor='lm')
        pages.append(page)
    return pages


def _grid(iw, ih, ox, oy) -> Image.Image:
    """Миллиметровка 1/5/10 мм, привязанная к координатам схемы (линии 10 мм = пути)."""
    im = Image.new('RGB', (iw, ih), 'white')
    d = ImageDraw.Draw(im)
    for step, col, w in ((1, (250, 236, 226), 1), (5, (243, 207, 184), 2),
                         (10, (236, 172, 136), 3)):
        k0 = math.floor(-ox / step)
        for k in range(k0, k0 + int(iw / PX / step) + 2):
            if step < 10 and (k * step) % (10 if step == 5 else 5) == 0:
                continue
            X = (k * step + ox) * PX
            d.line([(X, 0), (X, ih)], fill=col, width=w)
        k0 = math.floor(-oy / step)
        for k in range(k0, k0 + int(ih / PX / step) + 2):
            if step < 10 and (k * step) % (10 if step == 5 else 5) == 0:
                continue
            Y = (k * step + oy) * PX
            d.line([(0, Y), (iw, Y)], fill=col, width=w)
    return im


def save_pdf(pages: list[Image.Image], path: str):
    pages[0].save(path, 'PDF', resolution=DPI, save_all=True, append_images=pages[1:])
