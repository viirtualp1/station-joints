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
from typing import Any

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


from joints import SIG_D as SIG_LAMP, SIG_OFF, SIG_ROW   # общие с расчётом места под светофор
SIG_STEM = 6.0       # стойка мачты до огней (прил. 1: 6 мм)
SIG_BASE = 2.0       # полувысота основания мачты
SIG_BOX = 4.0        # трансформаторный ящик (прил. 1: 4 мм)


def _draw_signal(d, st, s, S, mm, lw, font_name, font2):
    from signals import ENTRY, EXIT_DWARF, EXIT_MAIN, geometry, offset
    (x, y), (dx, dy), (nx, ny) = geometry(st, s)
    r = SIG_LAMP / 2

    def pt(along, across):
        """Точка в мм: along – по ходу от стыка, across – вправо от оси пути."""
        return S(x + dx * along + nx * across, y + dy * along + ny * across)

    def line(a0, c0, a1, c1, w=0.25):
        d.line([pt(a0, c0), pt(a1, c1)], fill='black', width=lw(w))

    def lamp(along, across, kind, big=False):
        rr = r * (1.25 if big else 1.0) * mm
        cx, cy = pt(along, across)
        box = [cx - rr, cy - rr, cx + rr, cy + rr]
        if kind == 'R':
            d.ellipse(box, fill='black')
            return
        d.ellipse(box, outline='black', width=lw(0.25), fill='white')
        if kind == 'W':
            q = rr * 0.45
            d.ellipse([cx - q, cy - q, cx + q, cy + q], outline='black', width=lw(0.2))
        elif kind == 'B':
            q = rr * 0.45
            d.ellipse([cx - q, cy - q, cx + q, cy + q], fill='black')
        elif kind == 'Y':                       # штриховка
            for k in (-0.5, 0.0, 0.5):
                h = math.sqrt(max(0.0, 1 - k * k)) * rr * 0.9
                ox_, oy_ = k * rr * 0.7071, -k * rr * 0.7071
                d.line([(cx + ox_ - h * 0.7071, cy + oy_ - h * 0.7071),
                        (cx + ox_ + h * 0.7071, cy + oy_ + h * 0.7071)], fill='black', width=lw(0.15))
        elif kind == 'X':                       # заглушка
            q = rr * 0.7071
            d.line([(cx - q, cy - q), (cx + q, cy + q)], fill='black', width=lw(0.2))
            d.line([(cx - q, cy + q), (cx + q, cy - q)], fill='black', width=lw(0.2))

    def two(along, across):                     # «2» – двухнитевая лампа
        d.text(pt(along, across + r + 1.1), '2', fill='black', font=font2, anchor='mm')

    c = offset(s)
    if s.kind == 'entry':
        line(0, c - SIG_BASE, 0, c + SIG_BASE)
        line(0, c, SIG_STEM, c)
        a = SIG_STEM + r
        lamp(a, c, 'W')
        line(a + r, c, a + r + 1.5, c)
        a += 2 * r + 1.5
        for k in reversed(ENTRY):               # от мачты к концу
            lamp(a + r, c, k)
            two(a + r, c)
            a += 2 * r
        end = a
    elif s.kind == 'exit_mast':
        line(0, c - SIG_BASE, 0, c + SIG_BASE)
        b = SIG_BOX
        d.polygon([pt(0, c - 1), pt(b, c - 1), pt(b, c + 1), pt(0, c + 1)], outline='black',
                  width=lw(0.25))
        line(b / 2, c - 1, b / 2, c + 1)
        line(b, c, b + 1.5, c)
        a = b + 1.5
        for k in reversed(EXIT_MAIN):
            lamp(a + r, c, k)
            if k != 'W':
                two(a + r, c)
            a += 2 * r
        end = a
    elif s.kind == 'exit_dwarf':
        rows = [c, c + SIG_ROW]
        line(0, rows[0] - r, 0, rows[1] + r)
        end = 0
        for row, lamps in zip(rows, EXIT_DWARF):
            a = 0
            for k in reversed(lamps):
                lamp(a + r, row, k)
                if k == 'R':                    # двухнитевая лампа на красном (п. 2.5)
                    d.text(pt(a + 2 * r + 0.9, row), '2', fill='black', font=font2, anchor='mm')
                a += 2 * r
            end = max(end, a)
    else:                                       # маневровые
        big = s.red
        first = 'R' if s.red else 'B'
        if s.kind == 'man_mast':
            line(0, c - SIG_BASE, 0, c + SIG_BASE)
            d.polygon([pt(0, c - 1), pt(2.5, c - 1), pt(2.5, c)], outline='black', width=lw(0.25))
            line(0, c, SIG_STEM, c)
            a = SIG_STEM
        else:
            line(0, c - r * 1.2, 0, c + r * 1.2)
            a = 0
        rr = r * (1.25 if big else 1.0)
        lamp(a + rr, c, first, big)
        a += 2 * rr
        lamp(a + r, c, 'W')
        end = a + 2 * r
    # название – позади основания (против хода движения)
    tx, ty = pt(-1.2, c)
    w = font_name.getlength(s.name)
    tx += -dx * w / 2
    d.text((tx, ty), s.name, fill='black', font=font_name, anchor='mm')
    return end


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


class Recorder:
    """Подмена ImageDraw: вместо рисования записывает векторные примитивы.
    Координаты приходят в пикселях при REC_PX пикселей на мм и пишутся в мм –
    так Flutter-клиент рисует ту же схему векторно, без дублирования логики."""

    def __init__(self, px_per_mm: float):
        self.k = 1.0 / px_per_mm
        self.items: list[dict] = []
        self._probe = ImageDraw.Draw(Image.new('L', (1, 1)))
        self.tag = ''                            # слой, к которому относятся примитивы

    @staticmethod
    def _col(c):
        if c is None:
            return None
        if isinstance(c, str):
            return {'black': '#000000', 'white': '#ffffff'}.get(c, c)
        return '#%02x%02x%02x' % tuple(c[:3])

    def _pts(self, xy):
        return [[round(x * self.k, 3), round(y * self.k, 3)] for x, y in xy]

    def line(self, xy, fill=None, width=1):
        self.items.append({'t': 'line', 'p': self._pts(xy), 'c': self._col(fill),
                           'w': round(width * self.k, 3), 'g': self.tag})

    def polygon(self, xy, fill=None, outline=None, width=1):
        self.items.append({'t': 'poly', 'p': self._pts(xy), 'f': self._col(fill),
                           'c': self._col(outline), 'w': round(width * self.k, 3), 'g': self.tag})

    def ellipse(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        self.items.append({'t': 'circle', 'x': round((x0 + x1) / 2 * self.k, 3),
                           'y': round((y0 + y1) / 2 * self.k, 3),
                           'r': round((x1 - x0) / 2 * self.k, 3), 'f': self._col(fill),
                           'c': self._col(outline), 'w': round(width * self.k, 3), 'g': self.tag})

    def rectangle(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        self.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=fill, outline=outline,
                     width=width)

    def text(self, xy, text, fill=None, font=None, anchor='la'):
        size = getattr(font, 'size', 10)
        self.items.append({'t': 'text', 'x': round(xy[0] * self.k, 3),
                           'y': round(xy[1] * self.k, 3), 's': text,
                           'h': round(size * self.k, 3), 'a': anchor, 'c': self._col(fill),
                           'g': self.tag})

    def textbbox(self, xy, text, font=None, anchor='la'):
        return self._probe.textbbox(xy, text, font=font, anchor=anchor)


REC_PX = 10.0          # пикселей на мм при записи (шрифты PIL – целые, точность 0,1 мм)


def render(st: Station, size, *, show_joints=True, show_letters=False,
           show_numbers=True, show_sections=False, show_section_names=False,
           show_annots=True, annots=(), view=None, highlight=None, show_grid=False,
           show_signals=True, record: Recorder | None = None):
    """Возвращает (PIL.Image, transform), transform: модель -> экран (k, ox, oy).
    view=(k, ox, oy) – заданный масштаб/сдвиг (зум); None – вписать всю схему.
    record – записать векторные примитивы в мм вместо картинки (см. scene.py)."""
    g = st.g
    W, H = size
    ss = 2                                  # суперсэмплинг для гладких линий
    if record is not None:                  # запись: 1 мм = REC_PX px, без сдвига
        view = (REC_PX / ss / (st.u / 10.0), 0.0, 0.0)
        show_grid = show_annots = False     # сетку и надписи клиент рисует сам
    if view is None:
        view = fit_view(st, size, annots if show_annots else ())
    k, ox, oy = view

    img = Image.new('RGB', (1, 1) if record is not None else (W * ss, H * ss), 'white')
    # PIL-холст или запись векторных примитивов (толщины – дробные мм)
    d: Any = record if record is not None else ImageDraw.Draw(img)
    mm = st.u / 10.0 * k * ss               # экранных пикселей в 1 мм

    def S(x, y):
        return (x * k + ox) * ss, (y * k + oy) * ss

    def lw(v):
        if record is not None:
            return v * mm                   # вектор: толщина без округления
        return max(1, int(round(v * mm)))

    # миллиметровка: 1 мм – тонкие, 5 мм – средние, 10 мм (клетка = междупутье) – жирные
    if show_grid:
        mx0, mx1 = -ox / k, (W - ox) / k
        my0, my1 = -oy / k, (H - oy) / k
        # мелкие линии – только когда они различимы, иначе сетка «забивает» схему
        steps = [(1, (250, 236, 226), 1)] if mm >= 6 else []
        if mm >= 2.5:
            steps.append((5, (243, 207, 184), 1))
        steps.append((10, (236, 172, 136) if mm >= 2.5 else (244, 212, 192), max(1, ss)))
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

    if record is not None:
        record.tag = 'tracks'
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

    if record is not None:
        record.tag = 'tracks'
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
        if n.label and show_numbers:            # номер тупика (п. 2.2) – за упором, снаружи
            d.text((cx - dx * 2.5 * mm, cy), n.label, fill='black',
                   font=_font(FONT_LETTER * 1.2 * mm), anchor='rm' if dx > 0 else 'lm')

    if record is not None:
        record.tag = 'numbers'
    # ось станции и номера путей с указанием специализации (п. 2.2): пути обезличены –
    # стрелки в обе стороны, номер пути – над стрелками
    named = [l for l in st.lines if 'name' in l and l.get('central') in g.edges]
    if show_numbers and named:
        free = {}                               # свободная часть пути: между стыками «б»
        for l in named:
            e = g.edges[l['central']]
            xs_ = [g.point_on(e, j.t)[0] for j in st.joints if j.edge == e.id and j.rule == 'б']
            xa, xb = sorted((g.nodes[e.a].x, g.nodes[e.b].x))
            if len(xs_) >= 2:
                xa, xb = min(xs_), max(xs_)
            free[id(l)] = (xa + 9, xb - 9)          # у стыков «б» – светофоры с подписями
        lo = max(v[0] for v in free.values())
        hi = min(v[1] for v in free.values())
        ax = (lo + hi) / 2 if lo < hi else st.xc
        if st.sheet_cut is not None and lo < st.sheet_cut - 30 < hi:
            ax = st.sheet_cut - 30          # два листа: ось – на листе 1, не на линии склейки
        xs = S(ax, 0)[0]
        ys = [l['y'] for l in named]
        y_top, y_bot = S(0, min(ys) - 6)[1], S(0, max(ys) + 6)[1]
        yy, dash = y_top, 2.0 * mm
        while yy < y_bot:                       # штриховая ось станции
            d.line([(xs, yy), (xs, min(yy + dash, y_bot))], fill='black', width=lw(0.2))
            yy += dash * 1.8
        f_tr = _font(FONT_LETTER * 1.2 * mm)
        for l in named:                         # обозначение пути – на оси (рис. 2.18)
            cx, cy = S(ax, l['y'])
            a, h = 2.2 * mm, 0.9 * mm
            for sgn in (-1, 1):                 # ◀▶ – путь обезличен
                d.polygon([(cx + sgn * 0.3 * mm, cy - h), (cx + sgn * (0.3 * mm + a), cy),
                           (cx + sgn * 0.3 * mm, cy + h)], fill='black')
            label = f"{l['name']}П"
            ty = cy - 2.0 * mm
            box = d.textbbox((cx, ty), label, font=f_tr, anchor='mb')
            d.rectangle([box[0] - 0.4 * mm, box[1] - 0.2 * mm, box[2] + 0.4 * mm, box[3]],
                        fill='white')           # ось не перечёркивает номер
            d.text((cx, ty), label, fill='black', font=f_tr, anchor='mb')

    f_num = _font(FONT_NUM * mm)
    f_letter = _font(FONT_LETTER * mm)
    sig_boxes = []
    if show_signals:
        from signals import footprint
        sig_boxes = [footprint(st, s) for s in getattr(st, 'signals', [])]

    if record is not None:
        record.tag = 'switches'
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
            # номер – со стороны, противоположной ответвлению; если там светофор –
            # на стороне ответвления, над обозначением стрелки
            # п. 2.3: номер пишут со стороны привода – со стороны поля или широкого
            # междупутья; при равных междупутьях – напротив ответвления
            mx_, my_ = n.x + tx * SW_BAR / 2 * st.u / 10, n.y + ty * SW_BAR / 2 * st.u / 10
            side = -1.0
            if abs(ty) < 0.2:                   # стрелка на горизонтальном пути
                gap = {}
                for sgn in (-1, 1):             # -1: напротив ответвления, +1: со стороны
                    dirn = sgn * (1 if ny > 0 else -1)          # +1 – вниз по экрану
                    ds = [(l['y'] - n.y) * dirn for l in st.lines
                          if l['x0'] - 1 <= n.x <= l['x1'] + 1 and (l['y'] - n.y) * dirn > 0.5]
                    gap[sgn] = min(ds) if ds else 1e9
                if gap[1] > gap[-1] + 1.0:
                    side = 1.0 + SW_BAR_H / 3.0
            # если на месте номера светофор – пробуем другую сторону, затем место
            # перед стрелкой (со стороны ответвления номер не мешает обозначению)
            other = -1.0 if side > 0 else 1.0 + SW_BAR_H / 3.0
            u10 = st.u / 10
            cands = [(side, SW_BAR / 2), (other, SW_BAR / 2), (side, -3.5), (other, -3.5)]

            hw = 0.5 + 1.1 * len(n.number)          # полуширина номера, мм

            def busy(sd, al):
                qx = n.x + tx * al * u10 + sd * nx * 3.0 * u10
                qy = n.y + ty * al * u10 + sd * ny * 3.0 * u10
                return any(b[0] - hw < qx < b[2] + hw and b[1] - 1.8 < qy < b[3] + 1.8
                           for b in sig_boxes)
            side, along = next((c for c in cands if not busy(*c)), cands[0])
            px = cx + tx * along * mm + side * nx * 3.0 * mm
            py = cy + ty * along * mm + side * ny * 3.0 * mm
            d.text((px, py), n.number, fill='black', font=f_num, anchor='mm')

    if record is not None:
        record.tag = 'joints'
    # стыки (прил. 1): 2 мм высота, полочки 2 мм; негабаритный – в окружности Ø6
    sig_side = {}                                   # стык -> сторона, где стоит светофор
    if show_signals:
        from signals import geometry
        for s in getattr(st, 'signals', []):
            sig_side.setdefault(id(s.joint), []).append(geometry(st, s)[2])
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
                # светофор на этом стыке с той же стороны – букву пишем с другой
                if any(sx * nx + sy * ny > 0.3 for sx, sy in sig_side.get(id(j), [])):
                    off = -off
                d.text((cx + nx * off, cy + ny * off), j.rule,
                       fill=BLUE if j.rule != 'р' else RED, font=f_letter, anchor='mm')

    if record is not None:
        record.tag = 'signals'
    # светофоры
    if show_signals:
        f_sig = _font(FONT_LETTER * 1.2 * mm)
        f_two = _font(1.5 * mm)
        for s in getattr(st, 'signals', []):
            _draw_signal(d, st, s, S, mm, lw, f_sig, f_two)

    # линия склейки двух листов (режим «Два листа»); клиент рисует её сам
    if st.sheet_cut is not None and record is None:
        cx = S(st.sheet_cut, 0)[0]
        yy, dash = 0.0, 2.5 * mm
        while yy < H * ss:
            d.line([(cx, yy), (cx, min(yy + dash, H * ss))], fill=(200, 30, 30), width=lw(0.3))
            yy += dash * 1.8

    if record is not None:
        record.tag = 'sections'
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

    if record is not None:
        return img, (k, ox, oy)
    img = img.resize((W, H), Image.Resampling.LANCZOS)
    return img, (k, ox, oy)
