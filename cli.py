"""Без GUI: python cli.py схема.jpg результат.png [--sections] [--names] [--grid] [--letters]"""
import sys

from joints import report
from layout import build_station
from parser import parse_image
from render import render


def main():
    src, out = sys.argv[1], sys.argv[2]
    r = parse_image(src)
    st, annots = build_station(r['graph'], r['annots'])
    img, _ = render(st, (2000, 1000), annots=annots,
                    show_sections='--sections' in sys.argv,
                    show_section_names='--names' in sys.argv,
                    show_grid='--grid' in sys.argv,
                    show_letters='--letters' in sys.argv)
    img.save(out)
    print(report(st))


if __name__ == '__main__':
    main()
