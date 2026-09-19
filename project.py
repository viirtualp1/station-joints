"""Файл работы .stj – распознанная схема вместе с исходником и правками.

Это zip-архив:
  project.json  – формат, настройки, граф после распознавания, стыки (с ручными правками)
  source.<ext>  – исходная картинка (файл самодостаточен – можно переслать)
  annot_N.png   – надписи с картинки (п/п, номер варианта)
  preview.png   – миниатюра для списка недавних

Распознавание (самый долгий и капризный шаг) при открытии не повторяется: граф берётся
из файла, компоновка по нему детерминирована, поэтому сохранённые стыки ложатся на те
же рёбра. Светофоры и участки пересчитываются по стыкам."""
from __future__ import annotations

import io
import json
import time
import zipfile

import numpy as np
from PIL import Image

from graph import Annotation, Graph, Joint

FORMAT = 'station-joints'
VERSION = 2               # 2: тип конца «вручную», правки светофоров
EXT = '.stj'


def graph_to_json(g: Graph) -> dict:
    return {'nodes': [[int(n.id), float(n.x), float(n.y), n.mark, n.number, n.label, n.fixed_mark]
                      for n in g.nodes.values()],
            'edges': [[int(e.id), int(e.a), int(e.b)] for e in g.edges.values()],
            'nid': int(g._nid), 'eid': int(g._eid)}


def graph_from_json(d: dict) -> Graph:
    from graph import Edge, Node
    g = Graph()
    for i, x, y, mark, number, label, *rest in d['nodes']:
        g.nodes[i] = Node(i, x, y, mark, number, label, bool(rest and rest[0]))
    for i, a, b in d['edges']:
        g.edges[i] = Edge(i, a, b)
    g._nid, g._eid = d['nid'], d['eid']
    return g


def joints_to_json(joints) -> list:
    return [{'edge': int(j.edge), 't': float(j.t), 'rule': j.rule, 'negab': bool(j.negab),
             'fixed': bool(j.fixed), 'why': j.why, 'anchor': _anchor_out(j.anchor)} for j in joints]


def _anchor_out(a):
    """Привязка стыка: (узел, расстояние) | ('between', da, db) – по ней ставятся светофоры."""
    if not isinstance(a, tuple):
        return None
    return [v if isinstance(v, str) else (int(v) if float(v).is_integer() and i == 0 else float(v))
            for i, v in enumerate(a)]


def joints_from_json(lst) -> list[Joint]:
    return [Joint(d['edge'], d['t'], d['rule'], d['negab'], d.get('fixed', True),
                  anchor=tuple(d['anchor']) if d.get('anchor') else None,
                  why=d.get('why', '')) for d in lst]


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def save(path: str, *, graph: Graph, annots, info: dict, source: bytes, source_name: str,
         settings: dict, joints, preview: Image.Image | None = None, edited: bool = False):
    ext = source_name.rsplit('.', 1)[-1].lower() if '.' in source_name else 'png'
    meta = {
        'format': FORMAT, 'version': VERSION,
        'saved': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'source': {'name': source_name, 'file': f'source.{ext}'},
        'info': {k: (v.item() if isinstance(v, np.generic) else v) for k, v in info.items()
                 if isinstance(v, (int, float, str, bool, np.generic))},
        'settings': settings,
        'graph': graph_to_json(graph),
        'annots': [{'x0': int(a.x0), 'y0': int(a.y0), 'x1': int(a.x1), 'y1': int(a.y1),
                    'scale': float(a.scale),
                    'file': f'annot_{i}.png'} for i, a in enumerate(annots)],
        'joints': joints_to_json(joints),
        'edited': edited,
    }
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json', json.dumps(meta, ensure_ascii=False, indent=1))
        z.writestr(meta['source']['file'], source)
        for i, a in enumerate(annots):
            m = np.asarray(a.mask, bool).astype(np.uint8) * 255
            z.writestr(f'annot_{i}.png', _png(Image.fromarray(m, 'L')))
        if preview is not None:
            z.writestr('preview.png', _png(preview))
    import os
    os.replace(tmp, path)                     # не портим старый файл, если запись упала


def load(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read('project.json').decode('utf-8'))
        if meta.get('format') != FORMAT:
            raise ValueError('это не файл работы «Стыки»')
        if meta.get('version', 0) > VERSION:
            raise ValueError('файл сохранён более новой версией программы')
        annots = []
        for a in meta['annots']:
            m = np.asarray(Image.open(io.BytesIO(z.read(a['file']))).convert('L')) > 127
            annots.append(Annotation(a['x0'], a['y0'], a['x1'], a['y1'], m, a.get('scale', 1.0)))
        return {
            'graph': graph_from_json(meta['graph']),
            'annots': annots,
            'info': meta.get('info', {}),
            'settings': meta.get('settings', {}),
            'joints': joints_from_json(meta.get('joints', [])),
            'edited': meta.get('edited', False),
            'source': z.read(meta['source']['file']),
            'source_name': meta['source']['name'],
            'saved': meta.get('saved', ''),
        }
