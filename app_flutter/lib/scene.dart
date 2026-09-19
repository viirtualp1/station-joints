import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui';

/// JSON-сцена от бэкенда (scene.py). Все координаты – в мм, ось y вниз.

Color? parseColor(Object? v) {
  if (v is! String || !v.startsWith('#') || v.length != 7) return null;
  return Color(0xFF000000 | int.parse(v.substring(1), radix: 16));
}

Offset _pt(dynamic p) {
  final l = p as List;
  return Offset((l[0] as num).toDouble(), (l[1] as num).toDouble());
}

double _d(Object? v) => (v as num?)?.toDouble() ?? 0;

sealed class Item {
  final String group;
  Item(this.group);

  static Item fromJson(Map<String, dynamic> j) {
    final g = j['g'] as String? ?? '';
    switch (j['t']) {
      case 'line':
        return LineItem(g, [for (final p in j['p'] as List) _pt(p)], parseColor(j['c']), _d(j['w']));
      case 'poly':
        return PolyItem(g, [for (final p in j['p'] as List) _pt(p)], parseColor(j['f']),
            parseColor(j['c']), _d(j['w']));
      case 'circle':
        return CircleItem(g, Offset(_d(j['x']), _d(j['y'])), _d(j['r']), parseColor(j['f']),
            parseColor(j['c']), _d(j['w']));
      case 'text':
        return TextItem(g, Offset(_d(j['x']), _d(j['y'])), j['s'] as String, _d(j['h']),
            j['a'] as String? ?? 'la', parseColor(j['c']));
    }
    throw FormatException('неизвестный примитив ${j['t']}');
  }
}

class LineItem extends Item {
  final List<Offset> pts;
  final Color? color;
  final double width;
  LineItem(super.group, this.pts, this.color, this.width);
}

class PolyItem extends Item {
  final List<Offset> pts;
  final Color? fill, stroke;
  final double width;
  PolyItem(super.group, this.pts, this.fill, this.stroke, this.width);
}

class CircleItem extends Item {
  final Offset c;
  final double r;
  final Color? fill, stroke;
  final double width;
  CircleItem(super.group, this.c, this.r, this.fill, this.stroke, this.width);
}

class TextItem extends Item {
  final Offset at;
  final String text;
  final double size; // «кегль» PIL – высота шрифта в мм
  final String anchor; // как в PIL: la, mm, rb, mb, lm, rm…
  final Color? color;
  TextItem(super.group, this.at, this.text, this.size, this.anchor, this.color);
}

class JointObj {
  final int id;
  final Offset pos;
  final String rule, text;
  final bool negab;
  JointObj(this.id, this.pos, this.rule, this.text, this.negab);
}

class EdgeObj {
  final int id;
  final Offset a, b;
  EdgeObj(this.id, this.a, this.b);
  double get length => (b - a).distance;
}

class SignalObj {
  final int id;
  final String name, kind, why;
  final int ordinate;
  final Rect box;
  SignalObj(this.id, this.name, this.kind, this.why, this.ordinate, this.box);
}

/// Изолированный участок (рельсовая цепь): имя, тип, стрелки, отрезки для подсветки.
class SectionObj {
  final int id;
  final String name, kind, throat;
  final List<String> switches;
  final int joints, length;
  final List<(Offset, Offset)> segs;
  final Rect box;
  SectionObj(this.id, this.name, this.kind, this.throat, this.switches, this.joints, this.length,
      this.segs, this.box);

  factory SectionObj.fromJson(Map<String, dynamic> o) {
    final bb = (o['box'] as List).map(_d).toList();
    return SectionObj(
      o['id'] as int,
      o['name'] as String,
      o['kind'] as String,
      o['throat'] as String,
      [for (final s in o['switches'] as List) s as String],
      o['joints'] as int,
      (o['length'] as num).round(),
      [
        for (final s in o['segs'] as List)
          (Offset(_d(s[0]), _d(s[1])), Offset(_d(s[2]), _d(s[3])))
      ],
      Rect.fromLTRB(bb[0], bb[1], bb[2], bb[3]),
    );
  }

  /// Расстояние от точки до ближайшего отрезка участка, мм.
  double distanceTo(Offset p) {
    var best = double.infinity;
    for (final (a, b) in segs) {
      final ab = b - a;
      final l2 = ab.distanceSquared;
      final t = l2 == 0 ? 0.0 : (((p - a).dx * ab.dx + (p - a).dy * ab.dy) / l2).clamp(0.0, 1.0);
      final d = (a + ab * t - p).distance;
      if (d < best) best = d;
    }
    return best;
  }
}

class AnnotObj {
  final Rect rect;
  final Uint8List png;
  AnnotObj(this.rect, this.png);
}

class Scene {
  final Rect bounds;
  final double originX;
  final double? sheetCut;
  final List<Item> items;
  final List<AnnotObj> annots;
  final List<JointObj> joints;
  final List<EdgeObj> edges;
  final List<SignalObj> signals;
  final List<SectionObj> sections;
  final List<String> issues;
  Map<String, dynamic>? source; // сведения об открытом файле (меняются при сохранении)

  Scene({
    required this.bounds,
    required this.originX,
    required this.sheetCut,
    required this.items,
    required this.annots,
    required this.joints,
    required this.edges,
    required this.signals,
    required this.sections,
    required this.issues,
    this.source,
  });

  factory Scene.fromJson(Map<String, dynamic> j, {Map<String, dynamic>? source}) {
    final b = (j['bounds'] as List).map(_d).toList();
    return Scene(
      bounds: Rect.fromLTRB(b[0], b[1], b[2], b[3]),
      originX: _d(j['origin_x']),
      sheetCut: (j['sheet_cut'] as num?)?.toDouble(),
      items: [for (final it in j['items'] as List) Item.fromJson(it as Map<String, dynamic>)],
      annots: [
        for (final a in j['annots'] as List)
          AnnotObj(Rect.fromLTRB(_d(a['x0']), _d(a['y0']), _d(a['x1']), _d(a['y1'])),
              base64Decode(a['png'] as String))
      ],
      joints: [
        for (final o in j['joints'] as List)
          JointObj(o['id'] as int, Offset(_d(o['x']), _d(o['y'])), o['rule'] as String,
              o['text'] as String? ?? '', o['negab'] as bool)
      ],
      edges: [
        for (final o in j['edges'] as List)
          EdgeObj(o['id'] as int, Offset(_d(o['x0']), _d(o['y0'])), Offset(_d(o['x1']), _d(o['y1'])))
      ],
      signals: [
        for (final o in j['signals'] as List)
          SignalObj(
              o['id'] as int,
              o['name'] as String,
              o['kind'] as String,
              o['why'] as String,
              o['ordinate'] as int,
              () {
                final bb = (o['box'] as List).map(_d).toList();
                return Rect.fromLTRB(bb[0], bb[1], bb[2], bb[3]);
              }())
      ],
      sections: [
        for (final o in (j['sections'] as List? ?? const []))
          SectionObj.fromJson(o as Map<String, dynamic>)
      ],
      issues: [for (final s in (j['issues'] as List? ?? const [])) s as String],
      source: source ?? (j['source'] as Map?)?.cast<String, dynamic>(),
    );
  }
}
