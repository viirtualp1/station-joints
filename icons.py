"""Иконки интерфейса, нарисованные в коде (PIL): без внешних файлов, чёткие на любом DPI.
Каждая – в двух цветах: для светлой и тёмной темы."""
from __future__ import annotations

import math

import customtkinter as ctk
from PIL import Image, ImageDraw

LIGHT_FG = (55, 65, 81, 255)      # серо-графитовый для светлой темы
DARK_FG = (220, 223, 228, 255)    # светло-серый для тёмной


def _canvas(size, ss=4):
    S = size * ss
    return Image.new('RGBA', (S, S), (0, 0, 0, 0)), S


def _done(im, size):
    return im.resize((size, size), Image.Resampling.LANCZOS)


def moon(size, color):
    im, S = _canvas(size)
    d = ImageDraw.Draw(im)
    r = S * 0.36
    c = S / 2
    d.ellipse([c - r, c - r, c + r, c + r], fill=color)
    o = S * 0.2                                      # вырез – полумесяц
    d.ellipse([c - r + o, c - r - o * 0.6, c + r + o, c + r - o * 0.6], fill=(0, 0, 0, 0))
    return _done(im, size)


def sun(size, color):
    im, S = _canvas(size)
    d = ImageDraw.Draw(im)
    c, r = S / 2, S * 0.18
    d.ellipse([c - r, c - r, c + r, c + r], fill=color)
    w = max(2, int(S * 0.07))
    for k in range(8):
        a = k * math.pi / 4
        r0, r1 = S * 0.29, S * 0.42
        d.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)),
                (c + r1 * math.cos(a), c + r1 * math.sin(a))], fill=color, width=w)
    return _done(im, size)


def dots(size, color):
    im, S = _canvas(size)
    d = ImageDraw.Draw(im)
    r = S * 0.075
    for x in (0.25, 0.5, 0.75):
        cx, cy = S * x, S / 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    return _done(im, size)


def replace(size, color):
    """Две круговые стрелки – «заменить»."""
    im, S = _canvas(size)
    d = ImageDraw.Draw(im)
    c, r = S / 2, S * 0.3
    w = max(2, int(S * 0.08))
    box = [c - r, c - r, c + r, c + r]
    d.arc(box, 200, 340, fill=color, width=w)
    d.arc(box, 20, 160, fill=color, width=w)
    h = S * 0.13
    for ang, sgn in ((340, 1), (160, 1)):
        a = math.radians(ang)
        px, py = c + r * math.cos(a), c + r * math.sin(a)
        tx, ty = -math.sin(a) * sgn, math.cos(a) * sgn          # касательная по ходу
        nx, ny = math.cos(a), math.sin(a)
        d.polygon([(px + tx * h, py + ty * h), (px - nx * h * 0.9, py - ny * h * 0.9),
                   (px + nx * h * 0.9, py + ny * h * 0.9)], fill=color)
    return _done(im, size)


def ctk_icon(fn, size=20) -> ctk.CTkImage:
    """CTkImage с вариантами для светлой и тёмной темы (рисуется с запасом под HiDPI)."""
    px = size * 2
    return ctk.CTkImage(light_image=fn(px, LIGHT_FG), dark_image=fn(px, DARK_FG),
                        size=(size, size))


def theme_icon(size=22) -> ctk.CTkImage:
    """Луна в светлой теме (перейти в тёмную), солнце – в тёмной."""
    px = size * 2
    return ctk.CTkImage(light_image=moon(px, LIGHT_FG), dark_image=sun(px, DARK_FG),
                        size=(size, size))
