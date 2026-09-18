"""Отрисовка распознанной схемы и стыков (PIL). Один рендерер – и для экрана, и для PNG."""
from __future__ import annotations

import colorsys
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from joints import Station

BLUE = (20, 70, 200)
JOINT = (0, 0, 0)
RED = (200, 30, 30)


def _font(size):
    for name in ('arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
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


def render(st: Station, size, *, background=None, show_joints=True, show_letters=True,
           show_numbers=True, show_sections=False, show_section_names=False,
           show_annots=True, annots=(), zoom=None, highlight=None, show_grid=False):
    """Возвращает (PIL.Image, transform), transform: модель -> экран (k, ox, oy)."""
    g = st.g
    W, H = size
    x0, y0, x1, y1 = g.bbox()
    for a in annots if show_annots else ():
        x0, y0 = min(x0, a.x0), min(y0, a.y0)
        x1, y1 = max(x1, a.x1), max(y1, a.y1)
    pad = st.u * 0.9
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    k = zoom or min(W / (x1 - x0), H / (y1 - y0))
    ox = (W - (x1 - x0) * k) / 2 - x0 * k
    oy = (H - (y1 - y0) * k) / 2 - y0 * k

    def P(x, y):
        return x * k + ox, y * k + oy

    ss = 2                                  # суперсэмплинг для гладких линий
    img = Image.new('RGB', (W * ss, H * ss), 'white')
    if background is not None:
        bg = Image.fromarray(background).convert('RGB')
        bw, bh = bg.size
        bg = bg.resize((int(bw * k * ss), int(bh * k * ss)))
        bg = Image.blend(Image.new('RGB', bg.size, 'white'), bg, 0.35)
        img.paste(bg, (int(ox * ss), int(oy * ss)))
    d = ImageDraw.Draw(img)

    def S(x, y):
        px, py = P(x, y)
        return px * ss, py * ss

    # миллиметровка: 1 мм – тонкие, 5 мм – средние, 10 мм (клетка = междупутье) – жирные
    if show_grid:
        mx0, mx1 = -ox / k, (W - ox) / k
        my0, my1 = -oy / k, (H - oy) / k
        px_mm = k * ss
        steps = [(1, (253, 228, 212), 1)] if px_mm >= 5 else []
        steps += [(5, (248, 200, 170), 1), (10, (235, 150, 110), max(1, ss))]
        for step, col, w in steps:
            i0, i1 = math.floor(mx0 / step), math.ceil(mx1 / step)
            for i in range(i0, i1 + 1):
                if step < 10 and (i * step) % (10 if step == 5 else 5) == 0:
                    continue
                X = S(i * step, 0)[0]
                d.line([(X, 0), (X, H * ss)], fill=col, width=w)
            i0, i1 = math.floor(my0 / step), math.ceil(my1 / step)
            for i in range(i0, i1 + 1):
                if step < 10 and (i * step) % (10 if step == 5 else 5) == 0:
                    continue
                Y = S(0, i * step)[1]
                d.line([(0, Y), (W * ss, Y)], fill=col, width=w)

    u = st.u * k * ss                       # междупутье в экранных пикселях
    lw = max(2, int(u * 0.045))
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

    # раскраска участков
    sec_color = {}
    if show_sections and st.sections:
        cols = _palette(len(st.sections))
        for i, s in enumerate(st.sections):
            for p in s['pieces']:
                sec_color[(p['edge'], round(p['t0'], 2))] = cols[i]

    # пути
    if st.sections and show_sections:
        for s in st.sections:
            for p in s['pieces']:
                e = g.edges[p['edge']]
                a = S(*g.point_on(e, p['t0']))
                b = S(*g.point_on(e, p['t1']))
                w = lw * 2 if p['edge'] in main_edges else lw
                d.line([a, b], fill=sec_color[(p['edge'], round(p['t0'], 2))], width=int(w * 1.6))
    else:
        for e in g.edges.values():
            w = lw * 2 if e.id in main_edges else lw
            d.line([S(*g.pos(e.a)), S(*g.pos(e.b))], fill='black', width=w)
    if highlight is not None and highlight in g.edges:
        e = g.edges[highlight]
        d.line([S(*g.pos(e.a)), S(*g.pos(e.b))], fill=(255, 150, 0), width=lw * 3)

    # тупиковые упоры ']'
    for n in g.nodes.values():
        if g.degree(n.id) != 1 or n.mark not in ('tupik',):
            continue
        e = g.incident(n.id)[0]
        dx, dy = g.direction(e, n.id)       # направление внутрь пути
        nx, ny = -dy, dx
        cx, cy = S(n.x, n.y)
        h = u * 0.16
        p1 = (cx + nx * h, cy + ny * h)
        p2 = (cx - nx * h, cy - ny * h)
        d.line([p1, p2], fill='black', width=lw)
        for p in (p1, p2):
            d.line([p, (p[0] - dx * h * 0.8, p[1] - dy * h * 0.8)], fill='black', width=lw)

    f_small = _font(max(9, int(u * 0.22)))
    f_letter = _font(max(9, int(u * 0.22)))

    # стрелки: утолщение со стороны остряков (тупой угол между ответвлением и путём),
    # т.е. навстречу противошёрстному движению + номер
    for s, info in st.sw.items():
        n = g.nodes[s]
        e = g.edges[info['trunk']]
        dx, dy = g.direction(e, s)
        cx, cy = S(n.x, n.y)
        L = min(u * 0.25, g.length(e) * k * ss * 0.4)
        d.line([(cx, cy), (cx + dx * L, cy + dy * L)], fill='black', width=int(lw * 2.8))
        if show_numbers and n.number:
            # номер – сбоку от пути, со стороны, противоположной ответвлению
            nx, ny = -dy, dx
            if nx * info['bdx'] + ny * info['bdy'] > 0:
                nx, ny = -nx, -ny
            tx = cx + dx * L * 0.5 + nx * u * 0.24
            ty = cy + dy * L * 0.5 + ny * u * 0.24
            d.text((tx, ty), n.number, fill='black', font=f_small, anchor='mm')

    # стыки
    if show_joints:
        for j in st.joints:
            e = g.edges[j.edge]
            x, y = g.point_on(e, j.t)
            cx, cy = S(x, y)
            (ax, ay), (bx, by) = g.pos(e.a), g.pos(e.b)
            L = math.hypot(bx - ax, by - ay) or 1
            tx, ty = (bx - ax) / L, (by - ay) / L       # вдоль пути
            nx, ny = -ty, tx                            # поперёк
            h = u * 0.13
            c = RED if j.rule == 'р' else JOINT
            d.line([(cx - nx * h, cy - ny * h), (cx + nx * h, cy + ny * h)], fill=c, width=lw)
            for sgn in (-1, 1):
                px, py = cx + nx * h * sgn, cy + ny * h * sgn
                d.line([(px - tx * h * 0.45, py - ty * h * 0.45),
                        (px + tx * h * 0.45, py + ty * h * 0.45)], fill=c, width=lw)
            if j.negab:
                r = h * 1.35
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=max(1, lw - 1))
            if show_letters:
                off = h * 2.2
                d.text((cx + nx * -off, cy + ny * -off - (0 if abs(ny) < 0.5 else 0)),
                       j.rule, fill=BLUE if j.rule != 'р' else RED, font=f_letter, anchor='mm')

    # имена участков
    if show_section_names:
        f_sec = _font(max(9, int(u * 0.2)))
        for s in st.sections:
            if not s['name'] or s['name'] in ('перегон',):
                continue
            p = max(s['pieces'], key=lambda p: (g.is_horizontal(g.edges[p['edge']]), p['t1'] - p['t0']))
            e = g.edges[p['edge']]
            x, y = g.point_on(e, (p['t0'] + p['t1']) / 2)
            cx, cy = S(x, y)
            d.text((cx, cy + u * 0.2), s['name'], fill=(0, 120, 60), font=f_sec, anchor='mm')

    img = img.resize((W, H), Image.LANCZOS)
    return img, (k, ox, oy)
