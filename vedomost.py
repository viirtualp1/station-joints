"""Ведомость для пояснительной записки – документ Word (.docx) с таблицами:
стрелки, изолированные участки, светофоры, изолирующие стыки и маршруты
(основные и вариантные поездные, простые маневровые – как табл. 3.1–3.3 пособия).

Файл собирается вручную (WordprocessingML в zip) – без python-docx и lxml,
чтобы не утяжелять сборку. Шрифт Times New Roman 12 (14 – заголовки)."""
from __future__ import annotations

import time
import zipfile
from xml.sax.saxutils import escape

from joints import Station
from routes import route_rows
from tables import joint_rows, section_rows, signal_table, switch_rows

_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
       '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
       '</Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
         '</Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
             '</Relationships>')
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_W}>'
           '<w:docDefaults><w:rPrDefault><w:rPr>'
           '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
           '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
           '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
           '</w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
           '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
           '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>'
           '<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>'
           '<w:style w:type="table" w:styleId="Grid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
           + ''.join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                     for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
           + '</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/>'
           '</w:tblCellMar></w:tblPr></w:style>'
           '</w:styles>')


def _run(text: str, bold=False, size: int | None = None) -> str:
    rpr = ('<w:b/>' if bold else '') + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else '')
    return (f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def _p(text='', *, bold=False, style: str | None = None, align: str | None = None,
       size: int | None = None, after: int | None = None) -> str:
    ppr = ((f'<w:pStyle w:val="{style}"/>' if style else '')
           + (f'<w:spacing w:after="{after}"/>' if after is not None else '')
           + (f'<w:jc w:val="{align}"/>' if align else ''))
    return f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}{_run(text, bold, size) if text else ""}</w:p>'


def _table(head: list[str], rows: list[list], widths: list[int], center: set[int]) -> str:
    """widths – в мм; center – номера столбцов с выравниванием по центру."""
    tw = [round(w * 56.7) for w in widths]           # мм -> twips

    def cell(i, text, bold=False, shade=False):
        tcpr = f'<w:tcW w:w="{tw[i]}" w:type="dxa"/>' + ('<w:shd w:val="clear" w:color="auto" w:fill="EDEDED"/>' if shade else '')
        return (f'<w:tc><w:tcPr>{tcpr}</w:tcPr>'
                + _p(text, bold=bold, size=22, align='center' if bold or i in center else None)
                + '</w:tc>')
    x = ['<w:tbl><w:tblPr><w:tblStyle w:val="Grid"/><w:tblW w:w="0" w:type="auto"/>'
         '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'
         + ''.join(f'<w:gridCol w:w="{w}"/>' for w in tw) + '</w:tblGrid>']
    x.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>'
             + ''.join(cell(i, h, bold=True, shade=True) for i, h in enumerate(head)) + '</w:tr>')
    for r in rows:
        x.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>'
                 + ''.join(cell(i, str(v)) for i, v in enumerate(r)) + '</w:tr>')
    x.append('</w:tbl>')
    return ''.join(x)


def _short(throat: str) -> str:
    return throat.replace(' горловина', '')


def build(st: Station, title: str = '') -> str:
    body = []
    body.append(_p('Ведомость к схематическому плану станции', bold=True, align='center', size=28))
    if title:
        body.append(_p(f'Схема: {title}', align='center'))
    body.append(_p(f'Нечётная горловина – {"справа" if st.odd_right else "слева"}; '
                   f'масштаб схемы – 1 клетка (10 мм) = междупутье; ординаты – от левого края, мм.',
                   align='center', after=120))

    n = 0

    def caption(text):
        nonlocal n
        n += 1
        body.append(_p(f'Таблица {n} – {text}', style='Heading1'))

    sw = switch_rows(st)
    caption(f'Стрелочные переводы ({len(sw)})')
    body.append(_table(['№ стрелки', 'Горловина', 'Ордината, мм', 'Участок'],
                       [[r['number'], _short(r['throat']), r['x'], r['section']] for r in sw],
                       [25, 55, 30, 50], {0, 2, 3}))

    secs = section_rows(st)
    caption(f'Изолированные участки ({len(secs)})')
    body.append(_table(['Участок', 'Тип', 'Расположение', 'Стрелки', 'Стыков', 'Длина на схеме, мм'],
                       [[r['name'], r['kind'], _short(r['throat']), ', '.join(r['switches']) or '–',
                         r['joints'], r['length']] for r in secs],
                       [24, 38, 34, 32, 16, 26], {0, 3, 4, 5}))

    sig = signal_table(st)
    caption(f'Светофоры ({len(sig)})')
    body.append(_table(['Светофор', 'Тип', 'Назначение', 'Ордината, мм'],
                       [[r['name'], r['kind'], r['why'], r['x']] for r in sig],
                       [22, 55, 72, 22], {0, 3}))

    js = joint_rows(st)
    caption(f'Изолирующие стыки ({len(js)}, негабаритных – {sum(r["negab"] for r in js)})')
    body.append(_table(['№', 'Ордината, мм', 'Правило (п. 2.4)', 'Габарит', 'Обоснование'],
                       [[i + 1, r['x'], f'{r["rule"]}) {r["rule_text"]}',
                         'негабаритный' if r['negab'] else 'габаритный', r['why'] or '–']
                        for i, r in enumerate(js)],
                       [12, 22, 60, 26, 51], {0, 1, 3}))

    routes = route_rows(st)
    train = [r for r in routes if r['kind'] != 'маневровый']
    main = [r for r in train if not r['variant']]
    caption(f'Основные поездные маршруты ({len(main)})')
    body.append(_table(['№', 'Горловина', 'Маршрут', 'Наименование', 'Светофор', 'Стрелки', 'Примечание'],
                       [[r['no'], _short(r['throat']), r['kind'], r['name'], r['signal'],
                         ', '.join(r['switches']), r['note']] for r in main],
                       [10, 20, 24, 26, 18, 52, 20], {0, 4}))
    var = [r for r in train if r['variant']]
    if var:
        caption(f'Вариантные поездные маршруты ({len(var)})')
        body.append(_table(['№', 'Горловина', 'Маршрут', 'Наименование', 'Светофор',
                            'Стрелки, определяющие маршрут', 'Примечание'],
                           [[r['no'], _short(r['throat']), r['kind'], r['name'], r['signal'],
                             ', '.join(r['key']), r['note']] for r in var],
                           [10, 20, 24, 26, 18, 52, 20], {0, 4}))
    shunt = [r for r in routes if r['kind'] == 'маневровый']
    caption(f'Простые маневровые маршруты ({len(shunt)})')
    body.append(_table(['№', 'Горловина', 'От светофора', 'Наименование', 'Стрелки, определяющие маршрут'],
                       [[r['no'], _short(r['throat']), r['signal'], r['name'],
                         ', '.join(r['key']) if r['variant'] else '–'] for r in shunt],
                       [10, 24, 26, 30, 80], {0, 2}))
    body.append(_p('Плюс – стрелка по прямому ходу, минус – по ответвлению; стрелки съездов '
                   'спаренные (14/16). Охранные стрелки и негабаритные участки, контролируемые '
                   'в маршрутах (табл. 2.1 пособия), программа не определяет – дополните вручную.',
                   size=20, after=120))

    body.append(_p(f'Сформировано программой «Стыки» {time.strftime("%d.%m.%Y")}.', size=20))
    # A4 книжная, поля: левое 30 мм, правое 10, верх/низ 20 (ГОСТ 7.32)
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="567" w:bottom="1134" w:left="1701" w:header="709" '
            'w:footer="709" w:gutter="0"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>'
            + ''.join(body) + sect + '</w:body></w:document>')


def save_docx(st: Station, path: str, title: str = ''):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CT)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        z.writestr('word/styles.xml', _STYLES)
        z.writestr('word/document.xml', build(st, title))
