"""Без GUI: python cli.py схема.jpg результат.png [--sections] [--names] [--grid] [--letters]
                                                  [--sheets листы.pdf] [--odd-left]
--sheets – дополнительно PDF из двух листов в натуральную величину (разрез у оси станции);
--odd-left – нечётная горловина слева, как в пособии (по умолчанию – справа)."""
import sys

from joints import report
from layout import build_station
from parser import parse_image
from render import render
from sheets import make_sheets, save_pdf


def main():
    src, out = sys.argv[1], sys.argv[2]
    r = parse_image(src)
    st, annots = build_station(r['graph'], r['annots'],
                                odd_right='--odd-left' not in sys.argv)
    img, _ = render(st, (2000, 1000), annots=annots,
                    show_sections='--sections' in sys.argv,
                    show_section_names='--names' in sys.argv,
                    show_grid='--grid' in sys.argv,
                    show_letters='--letters' in sys.argv)
    img.save(out)
    if '--sheets' in sys.argv:
        pdf = sys.argv[sys.argv.index('--sheets') + 1]
        save_pdf(make_sheets(st, annots, show_grid='--grid' in sys.argv,
                             show_letters='--letters' in sys.argv), pdf)
    print(report(st))


if __name__ == '__main__':
    main()
