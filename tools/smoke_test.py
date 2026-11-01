"""Быстрая проверка бэкенда: распознать образец и выгрузить все форматы.

    python tools/smoke_test.py

Запускается в CI перед сборкой; падает с ошибкой, если что-то сломалось.
"""
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server  # noqa: E402


def main():
    s = server.Session()
    s.load(os.path.join('samples', 'var96_photo.jpg'))
    with tempfile.TemporaryDirectory() as tmp:
        for kind in ('png', 'pdf', 'docx', 'vsdx'):
            path = os.path.join(tmp, f'out.{kind}')
            getattr(s, f'export_{kind}')(path)
            size = os.path.getsize(path)
            assert size > 0, f'{kind}: пустой файл'
            if kind in ('docx', 'vsdx'):
                assert zipfile.ZipFile(path).testzip() is None, f'{kind}: битый архив'
            print(f'ok {kind}: {size} bytes')


if __name__ == '__main__':
    main()
