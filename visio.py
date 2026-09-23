"""Экспорт схемы в Microsoft Visio (.vsdx).

Файл .vsdx – это zip с XML (как .docx), поэтому собираем его сами, без сторонних
библиотек. Чертёж тот же, что на экране и в PDF: его рисует render.py в режиме записи,
а здесь примитивы (в мм) переводятся в фигуры Visio (внутренние единицы – дюймы,
ось Y вверх).

Что получается в Visio:
  * масштаб 1:1 – миллиметр схемы = миллиметр листа;
  * слои «Пути», «Стрелки», «Стыки», «Светофоры», «Номера», «Участки» – их можно
    гасить и печатать по отдельности;
  * каждый объект (стык, светофор, стрелка, отрезок пути) – отдельная фигура-группа
    со свойствами (правило, обоснование, ордината…) – видны в панели «Данные фигуры».
"""
from __future__ import annotations

import time
import zipfile
from xml.sax.saxutils import escape, quoteattr

from joints import RULE_TEXT, Station, _nm
from render import REC_PX, Recorder, render
from tables import throat_of

MM = 25.4              # мм в дюйме: внутренние единицы Visio – дюймы
MARGIN = 10.0          # поля листа, мм

# слой записи (render.Recorder.tag) -> слой Visio
LAYERS = [('Пути', 'tracks'), ('Стрелки', 'switches'), ('Стыки', 'joints'),
          ('Светофоры', 'signals'), ('Номера и подписи', 'numbers'), ('Участки', 'sections')]
LAYER_IX = {tag: i for i, (_, tag) in enumerate(LAYERS)}

_NS = 'http://schemas.microsoft.com/office/visio/2012/main'
_NSR = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _a(v) -> str:
    return quoteattr(str(v))


def _cell(n: str, v, u: str = '') -> str:
    return f'<Cell N={_a(n)} V={_a(v)}{f" U={_a(u)}" if u else ""}/>'


def _num(v: float) -> str:
    return f'{v:.4f}'


# --------------------------------------------------------------------------- свойства фигур
def _sides(st: Station, edge: int, t: float) -> list[str]:
    out = []
    for s in st.sections:
        for p in s['pieces']:
            if p['edge'] == edge and (abs(p['t0'] - t) < 0.05 or abs(p['t1'] - t) < 0.05):
                out.append(s['name'] or 'участок')
                break
    return out


Rows = list[tuple[str, str, str]]


def _rows(*rows: tuple[str, str, str]) -> Rows:
    return list(rows)


def shape_data(st: Station) -> dict[str, Rows]:
    """Объект схемы -> свойства фигуры: (имя в Visio, подпись, значение)."""
    g = st.g
    x0 = min(n.x for n in g.nodes.values())

    def ordinate(x: float) -> str:
        return f'{round(x - x0)} мм'

    out: dict[str, list[tuple[str, str, str]]] = {}
    for i, j in enumerate(st.joints):
        x, _ = g.point_on(g.edges[j.edge], j.t)
        sides = _sides(st, j.edge, j.t)
        out[f'joint:{i}'] = _rows(
            ('Object', 'Объект', 'Изолирующий стык'),
            ('Rule', 'Правило', f'{j.rule}) {RULE_TEXT.get(j.rule, "")}'.strip(') ')),
            ('Why', 'Обоснование', j.why or '–'),
            ('Gabarit', 'Габарит', 'негабаритный' if j.negab else 'габаритный'),
            ('Sections', 'Разделяет', ' и '.join(sides) if len(sides) == 2 else '–'),
            ('Ordinate', 'Ордината', ordinate(x)),
        )
    for i, s in enumerate(st.signals):
        from signals import KIND_TEXT, _pos
        x = _pos(st, s.joint)[0]
        out[f'signal:{i}'] = _rows(
            ('Object', 'Объект', 'Светофор'),
            ('Name', 'Название', s.name),
            ('Kind', 'Тип', KIND_TEXT.get(s.kind) or s.kind),
            ('Why', 'Назначение', s.why or '–'),
            ('Throat', 'Горловина', throat_of(st, x)),
            ('Ordinate', 'Ордината', ordinate(x)),
        )
    sec_of = {n: s['name'] for s in st.sections for n in s['switches']}
    for n in st.sw:
        out[f'switch:{n}'] = _rows(
            ('Object', 'Объект', 'Стрелочный перевод'),
            ('Number', 'Номер', _nm(st, n)),
            ('Section', 'Участок', sec_of.get(n, '–')),
            ('Throat', 'Горловина', throat_of(st, g.nodes[n].x)),
            ('Ordinate', 'Ордината', ordinate(g.nodes[n].x)),
        )
    sec_of_edge = {p['edge']: s['name'] for s in st.sections for p in s['pieces']}
    for e in g.edges.values():
        out[f'edge:{e.id}'] = _rows(
            ('Object', 'Объект', 'Путь'),
            ('Section', 'Участок', sec_of_edge.get(e.id, '–')),
            ('Length', 'Длина на схеме', f'{round(g.length(e))} мм'),
        )
    ends = {'tupik': 'тупик', 'peregon': 'перегон', 'pp': 'подъездной путь'}
    for n in g.nodes.values():
        if g.degree(n.id) == 1:
            out[f'node:{n.id}'] = _rows(
                ('Object', 'Объект', 'Конец пути'),
                ('Kind', 'Тип', ends.get(n.mark or '', 'не задан')),
                ('Name', 'Имя', n.label or '–'),
                ('Ordinate', 'Ордината', ordinate(n.x)),
            )
    for s in st.sections:
        out[f'section:{s["name"]}'] = _rows(
            ('Object', 'Объект', 'Изолированный участок'),
            ('Name', 'Название', s['name']),
            ('Switches', 'Стрелки', ', '.join(_nm(st, n) for n in s['switches']) or '–'),
        )
    return out


# --------------------------------------------------------------------------- геометрия
def _bbox(it: dict) -> tuple[float, float, float, float]:
    if it['t'] in ('line', 'poly'):
        xs = [p[0] for p in it['p']]
        ys = [p[1] for p in it['p']]
        return min(xs), min(ys), max(xs), max(ys)
    if it['t'] == 'circle':
        r = it['r']
        return it['x'] - r, it['y'] - r, it['x'] + r, it['y'] + r
    w, h = _text_size(it)
    x, y = it['x'], it['y']
    ax, ay = (it.get('a') or 'la')[:1], (it.get('a') or 'la')[1:2]
    x -= {'m': w / 2, 'r': w}.get(ax, 0.0)
    y -= {'m': h / 2, 'b': h, 's': h, 'd': h}.get(ay, 0.0)
    return x, y, x + w, y + h


def _text_size(it: dict) -> tuple[float, float]:
    h = it.get('h', 2.0)
    return max(1.0, 0.62 * h * len(it['s'])), h * 1.25


class _Page:
    """Сбор фигур страницы: перевод мм (ось Y вниз) в дюймы Visio (ось Y вверх)."""

    def __init__(self, bounds, data: dict):
        bx0, by0, bx1, by1 = bounds
        self.dx, self.dy = MARGIN - bx0, MARGIN - by0        # модель -> лист, мм
        self.w = bx1 - bx0 + 2 * MARGIN
        self.h = by1 - by0 + 2 * MARGIN
        self.data = data
        self.id = 0

    def page(self, x: float, y: float) -> tuple[float, float]:
        return x + self.dx, y + self.dy

    def _next(self) -> int:
        self.id += 1
        return self.id

    def shape(self, it: dict, ox: float, oy: float) -> str:
        """Примитив -> фигура Visio. ox, oy – левый-нижний угол родителя (лист, мм)."""
        sx0, sy0, sx1, sy1 = [v for p in (self.page(*_bbox(it)[:2]), self.page(*_bbox(it)[2:]))
                              for v in p]
        w, h = max(sx1 - sx0, 0.01), max(sy1 - sy0, 0.01)
        cells = [_cell('PinX', _num((sx0 - ox + w / 2) / MM)),
                 _cell('PinY', _num((oy - sy1 + h / 2) / MM)),
                 _cell('Width', _num(w / MM)), _cell('Height', _num(h / MM)),
                 _cell('LocPinX', _num(w / 2 / MM)), _cell('LocPinY', _num(h / 2 / MM)),
                 _cell('Angle', '0')]

        def lx(x: float) -> str:
            return _num((self.page(x, 0)[0] - sx0) / MM)

        def ly(y: float) -> str:
            return _num((sy1 - self.page(0, y)[1]) / MM)

        body = ''
        if it['t'] == 'text':
            cells += [_cell('LineWeight', '0'), _cell('LinePattern', '0'),
                      _cell('FillPattern', '0'), _cell('TextBkgnd', '0'),
                      _cell('VerticalAlign', '1'), _cell('LeftMargin', '0'),
                      _cell('RightMargin', '0'), _cell('TopMargin', '0'),
                      _cell('BottomMargin', '0')]
            body = (f'<Section N="Character"><Row IX="0">{_cell("Size", _num(it["h"] / MM))}'
                    f'{_cell("Color", it.get("c") or "#000000")}</Row></Section>'
                    f'<Section N="Paragraph"><Row IX="0">{_cell("HorzAlign", "1")}</Row></Section>'
                    f'<Text>{escape(it["s"])}</Text>')
        elif it['t'] == 'circle':
            cells += [_cell('LineWeight', _num(max(it.get('w', 0.2), 0.12) / MM)),
                      _cell('LineColor', it.get('c') or '#000000')]
            fill = it.get('f')
            cells += [_cell('FillForegnd', fill or '#ffffff'),
                      _cell('FillPattern', '1' if fill else '0'),
                      _cell('LinePattern', '1' if it.get('c') else '0')]
            cx, cy = it['x'], it['y']
            r = it['r']
            body = ('<Section N="Geometry" IX="0">'
                    f'<Row T="Ellipse" IX="1">{_cell("X", lx(cx))}{_cell("Y", ly(cy))}'
                    f'{_cell("A", lx(cx + r))}{_cell("B", ly(cy))}'
                    f'{_cell("C", lx(cx))}{_cell("D", ly(cy - r))}</Row></Section>')
        else:
            cells += [_cell('LineWeight', _num(max(it.get('w', 0.2), 0.12) / MM)),
                      _cell('LineColor', it.get('c') or '#000000')]
            pts = it['p']
            fill = it.get('f') if it['t'] == 'poly' else None
            cells += [_cell('FillForegnd', fill or '#ffffff'),
                      _cell('FillPattern', '1' if fill else '0'),
                      _cell('LinePattern', '0' if (it['t'] == 'poly' and not it.get('c')) else '1')]
            rows = [f'<Row T="MoveTo" IX="1">{_cell("X", lx(pts[0][0]))}'
                    f'{_cell("Y", ly(pts[0][1]))}</Row>']
            for i, (x, y) in enumerate(pts[1:], start=2):
                rows.append(f'<Row T="LineTo" IX="{i}">{_cell("X", lx(x))}{_cell("Y", ly(y))}</Row>')
            if it['t'] == 'poly':
                n = len(pts) + 1
                rows.append(f'<Row T="LineTo" IX="{n}">{_cell("X", lx(pts[0][0]))}'
                            f'{_cell("Y", ly(pts[0][1]))}</Row>')
            body = '<Section N="Geometry" IX="0">' + ''.join(rows) + '</Section>'
        return (f'<Shape ID="{self._next()}" Type="Shape" LineStyle="0" FillStyle="0" '
                f'TextStyle="0">{"".join(cells)}{body}</Shape>')

    def group(self, key: str, items: list[dict]) -> str:
        """Объект схемы: группа примитивов со свойствами (Данные фигуры)."""
        boxes = [_bbox(it) for it in items]
        gx0, gy0 = self.page(min(b[0] for b in boxes), min(b[1] for b in boxes))
        gx1, gy1 = self.page(max(b[2] for b in boxes), max(b[3] for b in boxes))
        w, h = max(gx1 - gx0, 0.01), max(gy1 - gy0, 0.01)
        gid = self._next()
        inner = ''.join(self.shape(it, gx0, gy1) for it in items)
        props = ''
        rows = self.data.get(key, [])
        if rows:
            props = ('<Section N="Property">'
                     + ''.join(f'<Row N={_a(n)}>{_cell("Label", label)}'
                               f'{_cell("Value", value, "STR")}{_cell("Type", "0")}</Row>'
                               for n, label, value in rows)
                     + '</Section>')
        lay = LAYER_IX.get(items[0].get('g', ''), LAYER_IX['numbers'])
        name = self.data.get(key, [('', '', key)])[0][2]
        return (f'<Shape ID="{gid}" NameU={_a(f"{name} {key}")} Type="Group" LineStyle="0" '
                f'FillStyle="0" TextStyle="0">'
                f'{_cell("PinX", _num((gx0 + w / 2) / MM))}'
                f'{_cell("PinY", _num((self.h - gy1 + h / 2) / MM))}'
                f'{_cell("Width", _num(w / MM))}{_cell("Height", _num(h / MM))}'
                f'{_cell("LocPinX", _num(w / 2 / MM))}{_cell("LocPinY", _num(h / 2 / MM))}'
                f'{_cell("Angle", "0")}{_cell("LayerMember", str(lay))}'
                f'{props}<Shapes>{inner}</Shapes></Shape>')


# --------------------------------------------------------------------------- пакет .vsdx
def _rels(items: list[tuple[str, str, str]]) -> str:
    return (_HEAD + f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id={_a(i)} Type={_a(t)} Target={_a(tg)}/>' for i, t, tg in items)
            + '</Relationships>')


def _content_types() -> str:
    parts = {'/visio/document.xml': 'application/vnd.ms-visio.drawing.main+xml',
             '/visio/pages/pages.xml': 'application/vnd.ms-visio.pages+xml',
             '/visio/pages/page1.xml': 'application/vnd.ms-visio.page+xml',
             '/visio/windows.xml': 'application/vnd.ms-visio.windows+xml',
             '/docProps/core.xml': 'application/vnd.openxmlformats-package.core-properties+xml',
             '/docProps/app.xml': 'application/vnd.openxmlformats-officedocument.extended-properties+xml'}
    return (_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + ''.join(f'<Override PartName={_a(p)} ContentType={_a(c)}/>' for p, c in parts.items())
            + '</Types>')


_STYLES = ''.join(
    f'<StyleSheet ID="{i}" NameU={_a(n)} Name={_a(n)} LineStyle="0" FillStyle="0" TextStyle="0">'
    f'{_cell("LineWeight", "0.01")}{_cell("LineColor", "#000000")}{_cell("LinePattern", "1")}'
    f'{_cell("FillForegnd", "#ffffff")}{_cell("FillPattern", "0")}'
    f'{_cell("CharSize", "0.0555")}{_cell("CharColor", "#000000")}'
    '</StyleSheet>' for i, n in enumerate(('No Style', 'Normal', 'None', 'Guide')))


def _document() -> str:
    return (_HEAD + f'<VisioDocument xmlns="{_NS}" xmlns:r="{_NSR}" xml:space="preserve">'
            '<DocumentSettings TopPage="0" DefaultTextStyle="0" DefaultLineStyle="0" '
            'DefaultFillStyle="0" DefaultGuideStyle="0"><GlueSettings>9</GlueSettings>'
            '<SnapSettings>65847</SnapSettings><DynamicGridEnabled>1</DynamicGridEnabled>'
            '<ProtectStyles>0</ProtectStyles><ProtectShapes>0</ProtectShapes>'
            '<ProtectMasters>0</ProtectMasters><ProtectBkgnds>0</ProtectBkgnds>'
            '</DocumentSettings><Colors/><FaceNames/>'
            f'<StyleSheets>{_STYLES}</StyleSheets>'
            '<DocumentSheet NameU="TheDoc" LineStyle="0" FillStyle="0" TextStyle="0"/>'
            '</VisioDocument>')


def _pages(page: _Page, title: str) -> str:
    layers = ''.join(
        f'<Row IX="{i}">{_cell("Name", name)}{_cell("NameUniv", tag)}{_cell("Color", "255")}'
        f'{_cell("Status", "0")}{_cell("Visible", "1")}{_cell("Print", "1")}'
        f'{_cell("Active", "0")}{_cell("Lock", "0")}{_cell("Snap", "1")}{_cell("Glue", "1")}'
        f'{_cell("ColorTrans", "0")}</Row>' for i, (name, tag) in enumerate(LAYERS))
    return (_HEAD + f'<Pages xmlns="{_NS}" xmlns:r="{_NSR}" xml:space="preserve">'
            f'<Page ID="0" NameU={_a(title or "Схема станции")} Name={_a(title or "Схема станции")} '
            f'ViewScale="-1" ViewCenterX="{_num(page.w / 2 / MM)}" '
            f'ViewCenterY="{_num(page.h / 2 / MM)}">'
            '<PageSheet LineStyle="0" FillStyle="0" TextStyle="0">'
            f'{_cell("PageWidth", _num(page.w / MM))}{_cell("PageHeight", _num(page.h / MM))}'
            f'{_cell("PageScale", "1", "IN")}{_cell("DrawingScale", "1", "IN")}'
            f'{_cell("DrawingSizeType", "3")}{_cell("DrawingScaleType", "0")}'
            f'<Section N="Layer">{layers}</Section></PageSheet>'
            '<Rel r:id="rId1"/></Page></Pages>')


def _windows(page: _Page) -> str:
    return (_HEAD + f'<Windows xmlns="{_NS}" xmlns:r="{_NSR}" ClientWidth="1000" ClientHeight="700">'
            '<Window ID="0" WindowType="Drawing" WindowState="1073741824" WindowLeft="0" '
            'WindowTop="0" WindowWidth="1000" WindowHeight="700" ContainerType="Page" Page="0" '
            f'ViewScale="-1" ViewCenterX="{_num(page.w / 2 / MM)}" '
            f'ViewCenterY="{_num(page.h / 2 / MM)}"/></Windows>')


def _props(title: str) -> tuple[str, str]:
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    core = (_HEAD + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title or "Схема станции")}</dc:title>'
            '<dc:creator>Стыки</dc:creator><cp:lastModifiedBy>Стыки</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            '</cp:coreProperties>')
    app = (_HEAD + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
           'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
           '<Application>Microsoft Visio</Application><Company>Стыки</Company></Properties>')
    return core, app


def save_vsdx(st: Station, path: str, *, annots=(), layers: dict | None = None, title: str = ''):
    """Собрать .vsdx: тот же чертёж, что на экране, фигурами Visio со свойствами."""
    lay = {'joints': True, 'signals': True, 'numbers': True, 'letters': False,
           'sections': False, 'section_names': False, **(layers or {})}
    rec = Recorder(REC_PX)
    render(st, (1, 1), record=rec, show_joints=lay['joints'], show_signals=lay['signals'],
           show_numbers=lay['numbers'], show_letters=lay['letters'],
           show_sections=lay['sections'], show_section_names=lay['section_names'])
    items = [it for it in rec.items if it['t'] != 'text' or it.get('s')]
    if not items:
        raise ValueError('на схеме нечего экспортировать')
    boxes = [_bbox(it) for it in items]
    bounds = (min(b[0] for b in boxes), min(b[1] for b in boxes),
              max(b[2] for b in boxes), max(b[3] for b in boxes))
    page = _Page(bounds, shape_data(st))

    shapes, group, key = [], [], None
    for it in items:                                    # подряд идущие примитивы объекта
        o = it.get('o') or ''
        if o != key:
            if group:
                shapes.append(page.group(key or '', group))
            group, key = [], o
        if o:
            group.append(it)
        else:
            shapes.append(page.shape(it, 0.0, page.h))
    if group:
        shapes.append(page.group(key or '', group))

    page_xml = _HEAD + (f'<PageContents xmlns="{_NS}" xmlns:r="{_NSR}" xml:space="preserve">'
                        f'<Shapes>{"".join(shapes)}</Shapes></PageContents>')
    core, app = _props(title)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _content_types())
        z.writestr('_rels/.rels', _rels([
            ('rId1', 'http://schemas.microsoft.com/visio/2010/relationships/document', 'visio/document.xml'),
            ('rId2', 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties', 'docProps/core.xml'),
            ('rId3', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties', 'docProps/app.xml')]))
        z.writestr('docProps/core.xml', core)
        z.writestr('docProps/app.xml', app)
        z.writestr('visio/document.xml', _document())
        z.writestr('visio/_rels/document.xml.rels', _rels([
            ('rId1', 'http://schemas.microsoft.com/visio/2010/relationships/pages', 'pages/pages.xml'),
            ('rId2', 'http://schemas.microsoft.com/visio/2010/relationships/windows', 'windows.xml')]))
        z.writestr('visio/windows.xml', _windows(page))
        z.writestr('visio/pages/pages.xml', _pages(page, title))
        z.writestr('visio/pages/_rels/pages.xml.rels', _rels([
            ('rId1', 'http://schemas.microsoft.com/visio/2010/relationships/page', 'page1.xml')]))
        z.writestr('visio/pages/page1.xml', page_xml)
    return {'shapes': len(shapes), 'width_mm': round(page.w), 'height_mm': round(page.h)}
