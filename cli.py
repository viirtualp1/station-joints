"""Без GUI: python cli.py схема.jpg результат.png [--sections]"""
import sys

from joints import analyse, place_joints, report
from parser import parse_image
from render import render


def main():
    src, out = sys.argv[1], sys.argv[2]
    r = parse_image(src)
    st = analyse(r['graph'])
    place_joints(st)
    img, _ = render(st, (1800, 1000), annots=r['annots'],
                    show_sections='--sections' in sys.argv,
                    show_section_names='--names' in sys.argv)
    img.save(out)
    print(report(st))


if __name__ == '__main__':
    main()
