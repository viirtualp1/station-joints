"""Генерация иконки приложения: assets/icon.ico (запускать один раз)."""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw(size: int) -> Image.Image:
    s = 4                                            # суперсэмплинг
    S = size * s
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=(37, 99, 235, 255))
    w = max(2, int(S * 0.07))
    y1, y2 = int(S * 0.36), int(S * 0.64)
    x0, x1 = int(S * 0.16), int(S * 0.84)
    d.line([(x0, y1), (x1, y1)], fill='white', width=w)          # путь II
    d.line([(x0, y2), (x1, y2)], fill='white', width=w)          # путь I
    d.line([(int(S * 0.34), y2), (int(S * 0.62), y1)], fill='white', width=w)  # съезд
    jx, h = int(S * 0.76), int(S * 0.09)                           # изолирующий стык
    d.line([(jx, y2 - h), (jx, y2 + h)], fill='white', width=max(2, w // 2))
    for yy in (y2 - h, y2 + h):
        d.line([(jx - h * 0.8, yy), (jx + h * 0.8, yy)], fill='white', width=max(2, w // 2))
    return im.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == '__main__':
    os.makedirs(os.path.join(ROOT, 'assets'), exist_ok=True)
    big = draw(256)
    big.save(os.path.join(ROOT, 'assets', 'icon.ico'),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(ROOT, 'assets', 'icon.png'))
    print('ok')
