"""Отрисовка схемы и стыков (PIL). Один рендерер – и для экрана, и для PNG.

Модель – в миллиметрах (см. layout.py). Размеры условных обозначений – по прил. 1
пособия (ГОСТ-обозначения ЖАТ):
  стрелка     – ответвление под 30°, междупутье 10 мм; у остряков тонкая линия 5 мм
                и закрашенный прямоугольник 3 мм (высота 1 мм) со стороны ответвления;
  стык        – высота 2 мм, полочки 2 мм;
  негабаритный стык – стык в окружности Ø 6 мм.
"""
from __future__ import annotations

import colorsys
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from joints import Station

BLUE = (20, 70, 200)
JOINT = (0, 0, 0)
RED = (200, 30, 30)

# --- размеры обозначений, мм ------------------------------------------------
SW_LINE = 5.0        # тонкая линия стрелки
SW_BAR = 3.0         # закрашенный прямоугольник стрелки
SW_BAR_H = 1.0       # его высота (расстояние тонкой линии от оси пути)
JOINT_H = 2.0        # высота стыка
JOINT_W = 2.0        # ширина полочек стыка
NEGAB_D = 6.0        # диаметр окружности негабаритного стыка
TUPIK_H = 4.0        # высота тупикового упора
TUPIK_W = 1.5        # длина его полочек
LINE_MAIN = 0.6      # толщина линий: главные пути
LINE_TRACK = 0.4     #                 остальные пути
LINE_THIN = 0.25     #                 тонкие линии обозначений
FONT_NUM = 3.5       # высота шрифта номеров стрелок (ГОСТ 3,5)
FONT_LETTER = 2.5    # буквы правил
FONT_SEC = 2.5       # имена участков


def _font(size):
    for name in ('arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, max(6, int(size)))
        except OSError:
            pass
    return ImageFont.load_default()


def _palette(n):
    cols = []
    for i in range(max(n, 1)):
        h = (i * 0.618034) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.65, 0.85)
        cols.append((int(r * 255), int(g * 255), int(b * 255)))
    return cols


def fit_view(st: Station, size, annots=()):
    """Масштаб и сдвиг, при которых вся схема вписывается в окно."""
    g = st.g
    W, H = size
    x0, y0, x1, y1 = g.bbox()
    for a in annots:
        x0, y0 = min(x0, a.x0), min(y0, a.y0)
        x1, y1 = max(x1, a.x1), max(y1, a.y1)
    pad = st.u * 0.9
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    k = min(W / (x1 - x0), H / (y1 - y0))
    return k, (W - (x1 - x0) * k) / 2 - x0 * k, (H - (y1 - y0) * k) / 2 - y0 * k


def render(st: Station, size, *, show_joints=True, show_letters=True,
           show_numbers=True, show_sections=False, show_section_names=False,
           show_annots=True, annots=(), view=None, highlight=None, show_grid=False):
    """Возвращает (PIL.Image, transform), transform: модель -> экран (k, ox, oy).
    view=(k, ox, oy) – заданный масштаб/сдвиг (зум); None – вписать всю схему."""
    g = st.g
    W, H = size
    if view is None:
        view = fit_view(st, size, annots if show_annots else ())
    k, ox, oy = view

    ss = 2                                  # суперсэмплинг для гладких линий
    img = Image.new('RGB', (W * ss, H * ss), 'white')
    d = ImageDraw.Draw(img)
    mm = st.u / 10.0 * k * ss               # экранных пикселей в 1 мм

    def S(x, y):
        return (x * k + ox) * ss, (y * k + oy) * ss

    def lw(v):
        return max(1, int(round(v * mm)))

    # миллиметровка: 1 мм – тонкие, 5 мм – средние, 10 мм (клетка = междупутье) – жирные
    if show_grid:
        mx0, mx1 = -ox / k, (W - ox) / k
        my0, my1 = -oy / k, (H - oy) / k
        steps = [(1, (253, 228, 212), 1)] if mm >= 5 else []
        steps += [(5, (242, 182, 145), 1), (10, (235, 150, 110), max(1, ss))]
        for step, col, w in steps:
            for i in range(math.floor(mx0 / step), math.ceil(mx1 / step) + 1):
                if step < 10 and (i * step) % (10 if step == 5 else 5) == 0:
                    continue
                X = S(i * step, 0)[0]
                d.line([(X, 0), (X, H * ss)], fill=col, width=w)
            for i in range(math.floor(my0 / step), math.ceil(my1 / step) + 1):
                if step < 10 and (i * step) % (10 if step == 5 else 5) == 0:
                    continue
                Y = S(0, i * step)[1]
                d.line([(0, Y), (W * ss, Y)], fill=col, width=w)

    main_edges = set()
    for l in st.mains:
        main_edges |= set(l['edges'])

    # надписи с исходной картинки (п/п, номер варианта) – как есть
    if show_annots:
        for a in annots:
            m = np.asarray(a.mask, bool)
            if m.size == 0:
                continue
            glyph = Image.fromarray(m.astype(np.uint8) * 255, 'L')
            gw, gh = glyph.size
            sc = getattr(a, 'scale', 1.0) * k * ss
            glyph = glyph.resize((max(1, int(gw * sc)), max(1, int(gh * sc))))
            px, py = S(a.x0, a.y0)
            img.paste((60, 60, 60), (int(px), int(py)), glyph)

    # пути
    if st.sections and show_sections:
        cols = _palette(len(st.sections))
        for i, s in enumerate(st.sections):
            for p in s['pieces']:
                e = g.edges[p['edge']]
                w = LINE_MAIN if p['edge'] in main_edges else LINE_TRACK
                d.line([S(*g.point_on(e, p['t0'])), S(*g.point_on(e, p['t1']))],
                       fill=cols[i], width=lw(w * 1.8))
    else:
        for e in g.edges.values():
            w = LINE_MAIN if e.id in main_edges else LINE_TRACK
            d.line([S(*g.pos(e.a)), S(*g.pos(e.b))], fill='black', width=lw(w))
    if highlight is not None and highlight in g.edges:
        e = g.edges[highlight]
        d.line([S(*g.pos(e.a)), S(*g.pos(e.b))], fill=(255, 150, 0), width=lw(1.5))

    # тупиковые упоры ']'
    for n in g.nodes.values():
        if g.degree(n.id) != 1 or n.mark != 'tupik':
            continue
        e = g.incident(n.id)[0]
        dx, dy = g.direction(e, n.id)       # направление внутрь пути
        nx, ny = -dy, dx
        cx, cy = S(n.x, n.y)
        h, w = TUPIK_H / 2 * mm, TUPIK_W * mm
        p1 = (cx + nx * h, cy + ny * h)
        p2 = (cx - nx * h, cy - ny * h)
        d.line([p1, p2], fill='black', width=lw(LINE_TRACK))
        for p in (p1, p2):
            d.line([p, (p[0] - dx * w, p[1] - dy * w)], fill='black', width=lw(LINE_TRACK))

    f_num = _font(FONT_NUM * mm)
    f_letter = _font(FONT_LETTER * mm)

    # стрелки (прил. 1): со стороны остряков, на стороне ответвления –
    # закрашенный прямоугольник 3×1 мм и тонкая линия 5 мм
    for s, info in st.sw.items():
        n = g.nodes[s]
        tx, ty = g.direction(g.edges[info['trunk']], s)
        nx, ny = -ty, tx
        if nx * info['bdx'] + ny * info['bdy'] < 0:     # нормаль – в сторону ответвления
            nx, ny = -nx, -ny
        cx, cy = S(n.x, n.y)
        bar = [(cx, cy), (cx + tx * SW_BAR * mm, cy + ty * SW_BAR * mm),
               (cx + tx * SW_BAR * mm + nx * SW_BAR_H * mm, cy + ty * SW_BAR * mm + ny * SW_BAR_H * mm),
               (cx + nx * SW_BAR_H * mm, cy + ny * SW_BAR_H * mm)]
        d.polygon(bar, fill='black')
        la = (cx + nx * SW_BAR_H * mm, cy + ny * SW_BAR_H * mm)
        d.line([la, (la[0] + tx * SW_LINE * mm, la[1] + ty * SW_LINE * mm)],
               fill='black', width=lw(LINE_THIN))
        if show_numbers and n.number:
            # номер – со стороны, противоположной ответвлению
            px = cx + tx * SW_BAR / 2 * mm - nx * 3.0 * mm
            py = cy + ty * SW_BAR / 2 * mm - ny * 3.0 * mm
            d.text((px, py), n.number, fill='black', font=f_num, anchor='mm')

    # стыки (прил. 1): 2 мм высота, полочки 2 мм; негабаритный – в окружности Ø6
    if show_joints:
        for j in st.joints:
            e = g.edges[j.edge]
            cx, cy = S(*g.point_on(e, j.t))
            (ax, ay), (bx, by) = g.pos(e.a), g.pos(e.b)
            L = math.hypot(bx - ax, by - ay) or 1
            tx, ty = (bx - ax) / L, (by - ay) / L       # вдоль пути
            nx, ny = -ty, tx                            # поперёк
            if ny > 0:
                nx, ny = -nx, -ny                       # «вверх» по экрану
            h, w = JOINT_H / 2 * mm, JOINT_W / 2 * mm
            c = RED if j.rule == 'р' else JOINT
            d.line([(cx - nx * h, cy - ny * h), (cx + nx * h, cy + ny * h)], fill=c, width=lw(LINE_THIN))
            for sgn in (-1, 1):
                px, py = cx + nx * h * sgn, cy + ny * h * sgn
                d.line([(px - tx * w, py - ty * w), (px + tx * w, py + ty * w)], fill=c, width=lw(LINE_THIN))
            if j.negab:
                r = NEGAB_D / 2 * mm
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=lw(LINE_THIN))
            if show_letters:
                off = (NEGAB_D / 2 + 1.8) * mm if j.negab else (JOINT_H / 2 + 2.0) * mm
                d.text((cx + nx * off, cy + ny * off), j.rule,
                       fill=BLUE if j.rule != 'р' else RED, font=f_letter, anchor='mm')

    # имена участков
    if show_section_names:
        f_sec = _font(FONT_SEC * mm)
        for s in st.sections:
            if not s['name'] or s['name'] == 'перегон':
                continue
            p = max(s['pieces'], key=lambda p: (g.is_horizontal(g.edges[p['edge']]), p['t1'] - p['t0']))
            e = g.edges[p['edge']]
            cx, cy = S(*g.point_on(e, (p['t0'] + p['t1']) / 2))
            d.text((cx, cy + 3.0 * mm), s['name'], fill=(0, 120, 60), font=f_sec, anchor='mm')

    img = img.resize((W, H), Image.LANCZOS)
    return img, (k, ox, oy)
