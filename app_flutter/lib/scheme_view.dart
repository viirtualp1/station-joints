import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'scene.dart';
import 'theme.dart';

enum Tool { select, joint }

/// Что под курсором / что выделено.
sealed class Hit {}

class JointHit extends Hit {
  final JointObj j;
  JointHit(this.j);
}

class SignalHit extends Hit {
  final SignalObj s;
  SignalHit(this.s);
}

class SectionHit extends Hit {
  final SectionObj sec;
  SectionHit(this.sec);
}

class EdgeHit extends Hit {
  final EdgeObj e;
  final double t; // расстояние от начала ребра, мм
  final Offset at;
  EdgeHit(this.e, this.t, this.at);
}

/// Управление камерой снаружи (кнопки зума, переход к светофору).
class SchemeController extends ChangeNotifier {
  _SchemeViewState? _s;
  double get zoomPercent => _s?._zoomPercent ?? 100;
  void zoomBy(double f) => _s?._zoomAtCenter(f);
  void fit() => _s?._fit(animate: true);
  void focus(Rect r) => _s?._focus(r);
  void _changed() => notifyListeners();
}

class SchemeView extends StatefulWidget {
  final Scene? scene;
  final bool grid;
  final Tool tool;
  final Hit? selected;
  final SchemeController controller;
  final ValueChanged<Hit?> onSelect;
  final void Function(EdgeHit) onAddJoint;
  final void Function(Hit?, double? ordinate) onHover;
  final void Function(Offset global, Hit hit) onContext;

  const SchemeView({
    super.key,
    required this.scene,
    required this.grid,
    required this.tool,
    required this.selected,
    required this.controller,
    required this.onSelect,
    required this.onAddJoint,
    required this.onHover,
    required this.onContext,
  });

  @override
  State<SchemeView> createState() => _SchemeViewState();
}

class _SchemeViewState extends State<SchemeView> with SingleTickerProviderStateMixin {
  double _k = 4; // px на мм
  Offset _o = Offset.zero; // сдвиг, px
  Size _size = Size.zero;
  bool _fitted = false;
  Hit? _hover;

  ui.Picture? _pic;
  Scene? _picScene;
  final Map<AnnotObj, ui.Image> _annotImg = {};

  late final AnimationController _anim = AnimationController(vsync: this, duration: const Duration(milliseconds: 260));
  double _k0 = 1, _k1 = 1;
  Offset _c0 = Offset.zero, _c1 = Offset.zero; // центр экрана в мм – начало/конец

  Offset? _down; // точка нажатия (для клика против перетаскивания)
  bool _panning = false;
  int _buttons = 0;

  double get _zoomPercent {
    final s = widget.scene;
    if (s == null || _size.isEmpty) return 100;
    return _k / _fitScale(s.bounds) * 100;
  }

  @override
  void initState() {
    super.initState();
    widget.controller._s = this;
    _anim.addListener(_tick);
  }

  @override
  void didUpdateWidget(SchemeView old) {
    super.didUpdateWidget(old);
    widget.controller._s = this;
    if (!identical(old.scene, widget.scene)) {
      _pic = null;
      final boundsChanged =
          old.scene == null || widget.scene == null || (old.scene!.bounds.width - widget.scene!.bounds.width).abs() > 1;
      if (boundsChanged) _fitted = false;
      _loadAnnots();
    }
  }

  @override
  void dispose() {
    _anim.dispose();
    if (widget.controller._s == this) widget.controller._s = null;
    super.dispose();
  }

  Future<void> _loadAnnots() async {
    final s = widget.scene;
    if (s == null) return;
    for (final a in s.annots) {
      if (_annotImg.containsKey(a)) continue;
      final codec = await ui.instantiateImageCodec(a.png);
      final fr = await codec.getNextFrame();
      if (!mounted) return;
      setState(() => _annotImg[a] = fr.image);
    }
  }

  // ---------------------------------------------------------------- камера
  double _fitScale(Rect b) => math.min((_size.width - 48) / b.width, (_size.height - 48) / b.height).clamp(0.05, 400);

  Offset _toModel(Offset p) => (p - _o) / _k;

  void _setCamera(double k, Offset centerMm) {
    _k = k;
    _o = _size.center(Offset.zero) - centerMm * k;
  }

  void _fit({bool animate = false}) {
    final s = widget.scene;
    if (s == null || _size.isEmpty) return;
    final k = _fitScale(s.bounds);
    if (animate) {
      _animateTo(k, s.bounds.center);
    } else {
      setState(() => _setCamera(k, s.bounds.center));
      widget.controller._changed();
    }
  }

  void _zoomAt(Offset p, double f) {
    final s = widget.scene;
    if (s == null) return;
    final fitK = _fitScale(s.bounds);
    final nk = (_k * f).clamp(fitK * 0.4, fitK * 80);
    final m = _toModel(p);
    setState(() {
      _k = nk;
      _o = p - m * nk;
    });
    widget.controller._changed();
  }

  void _zoomAtCenter(double f) => _zoomAt(_size.center(Offset.zero), f);

  void _focus(Rect r) {
    final s = widget.scene;
    if (s == null) return;
    final fitK = _fitScale(s.bounds);
    final k = math.max(math.min(_size.width / 90, _size.height / 55), fitK * 2.5);
    _animateTo(k, r.center);
  }

  void _animateTo(double k, Offset center) {
    _k0 = _k;
    _c0 = _toModel(_size.center(Offset.zero));
    _k1 = k;
    _c1 = center;
    _anim.forward(from: 0);
  }

  void _tick() {
    final e = Curves.easeInOutCubic.transform(_anim.value);
    final k = _k0 * math.pow(_k1 / _k0, e);
    setState(() => _setCamera(k.toDouble(), Offset.lerp(_c0, _c1, e)!));
    widget.controller._changed();
  }

  // ---------------------------------------------------------------- попадание
  Hit? _hitTest(Offset screen, {bool edges = false}) {
    final s = widget.scene;
    if (s == null) return null;
    final m = _toModel(screen);
    final tol = 9 / _k; // 9 px в мм
    JointObj? bj;
    var bd = tol;
    for (final j in s.joints) {
      final d = (j.pos - m).distance;
      if (d < bd) {
        bd = d;
        bj = j;
      }
    }
    if (bj != null && !edges) return JointHit(bj);
    if (!edges) {
      for (final sg in s.signals) {
        if (sg.box.inflate(0.5).contains(m)) return SignalHit(sg);
      }
      // клик по пути – его изолированный участок
      SectionObj? bs;
      var sd = tol * 0.7;
      for (final sec in s.sections) {
        final d = sec.distanceTo(m);
        if (d < sd) {
          sd = d;
          bs = sec;
        }
      }
      if (bs != null) return SectionHit(bs);
    }
    EdgeHit? be;
    var ed = tol;
    for (final e in s.edges) {
      final ab = e.b - e.a;
      final l2 = ab.distanceSquared;
      if (l2 == 0) continue;
      final t = (((m - e.a).dx * ab.dx + (m - e.a).dy * ab.dy) / l2).clamp(0.0, 1.0);
      final p = e.a + ab * t;
      final d = (p - m).distance;
      if (d < ed) {
        ed = d;
        be = EdgeHit(e, t * math.sqrt(l2), p);
      }
    }
    return be;
  }

  // ---------------------------------------------------------------- ввод
  void _onSignal(PointerSignalEvent e) {
    if (e is PointerScrollEvent) {
      _anim.stop();
      _zoomAt(e.localPosition, math.pow(1.0015, -e.scrollDelta.dy).toDouble());
    } else if (e is PointerScaleEvent) {
      _zoomAt(e.localPosition, e.scale);
    }
  }

  void _onDown(PointerDownEvent e) {
    _anim.stop();
    _down = e.localPosition;
    _buttons = e.buttons;
    _panning = e.buttons == kMiddleMouseButton;
  }

  void _onMove(PointerMoveEvent e) {
    if (_down == null) return;
    if (!_panning && (e.localPosition - _down!).distance > 4 && _buttons == kPrimaryButton) {
      _panning = true; // ЛКМ + перетаскивание – двигаем лист
    }
    if (_panning) {
      setState(() => _o += e.delta);
      widget.controller._changed();
    }
  }

  void _onUp(PointerUpEvent e) {
    final wasPan = _panning;
    final down = _down;
    _down = null;
    _panning = false;
    if (wasPan || down == null) return;
    if (_buttons == kSecondaryButton) {
      final h = _hitTest(e.localPosition);
      if (h is JointHit) {
        widget.onSelect(h);
        widget.onContext(e.position, h);
      }
      return;
    }
    if (_buttons != kPrimaryButton) return;
    if (widget.tool == Tool.joint) {
      final h = _hitTest(e.localPosition, edges: true);
      if (h is EdgeHit) widget.onAddJoint(h);
      return;
    }
    final h = _hitTest(e.localPosition);
    widget.onSelect(h is EdgeHit ? null : h);
  }

  void _onHover(PointerHoverEvent e) {
    final h = _hitTest(e.localPosition, edges: widget.tool == Tool.joint);
    final s = widget.scene;
    final ord = s == null ? null : _toModel(e.localPosition).dx - s.originX;
    widget.onHover(h, ord);
    final same = switch ((h, _hover)) {
      (JointHit a, JointHit b) => a.j.id == b.j.id,
      (SignalHit a, SignalHit b) => a.s.id == b.s.id,
      (SectionHit a, SectionHit b) => a.sec.id == b.sec.id,
      (EdgeHit a, EdgeHit b) => a.e.id == b.e.id && (a.at - b.at).distance < 0.2,
      (null, null) => true,
      _ => false,
    };
    if (!same) setState(() => _hover = h);
  }

  MouseCursor get _cursor {
    if (_panning) return SystemMouseCursors.grabbing;
    if (widget.tool == Tool.joint) {
      return _hover is EdgeHit ? SystemMouseCursors.precise : SystemMouseCursors.basic;
    }
    return _hover is JointHit || _hover is SignalHit || _hover is SectionHit
        ? SystemMouseCursors.click
        : SystemMouseCursors.basic;
  }

  @override
  Widget build(BuildContext context) {
    final tok = Tok.of(context);
    return LayoutBuilder(
      builder: (context, c) {
        final size = c.biggest;
        if (size != _size) {
          final center = _size.isEmpty ? null : _toModel(_size.center(Offset.zero));
          _size = size;
          if (center != null && _fitted) _setCamera(_k, center);
        }
        final s = widget.scene;
        if (s != null && !_fitted && !size.isEmpty) {
          _setCamera(_fitScale(s.bounds), s.bounds.center);
          _fitted = true;
          WidgetsBinding.instance.addPostFrameCallback((_) => widget.controller._changed());
        }
        if (s != null && !identical(_picScene, s)) {
          _pic = _record(s);
          _picScene = s;
        }
        return MouseRegion(
          cursor: _cursor,
          onExit: (_) {
            widget.onHover(null, null);
            setState(() => _hover = null);
          },
          child: Listener(
            onPointerSignal: _onSignal,
            onPointerDown: _onDown,
            onPointerMove: _onMove,
            onPointerUp: _onUp,
            onPointerHover: _onHover,
            child: ClipRect(
              child: CustomPaint(
                size: size,
                painter: _Painter(
                  scene: s,
                  picture: _pic,
                  annots: _annotImg,
                  k: _k,
                  o: _o,
                  grid: widget.grid,
                  hover: _hover,
                  selected: widget.selected,
                  tool: widget.tool,
                  tok: tok,
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------- отрисовка

ui.Picture _record(Scene s) {
  final rec = ui.PictureRecorder();
  final c = Canvas(rec);
  for (final it in s.items) {
    switch (it) {
      case LineItem(:final pts, :final color, :final width):
        final p = Paint()
          ..color = color ?? Colors.black
          ..strokeWidth = width
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.butt;
        if (pts.length == 2) {
          c.drawLine(pts[0], pts[1], p);
        } else {
          c.drawPath(Path()..addPolygon(pts, false), p);
        }
      case PolyItem(:final pts, :final fill, :final stroke, :final width):
        final path = Path()..addPolygon(pts, true);
        if (fill != null) c.drawPath(path, Paint()..color = fill);
        if (stroke != null) {
          c.drawPath(
            path,
            Paint()
              ..color = stroke
              ..style = PaintingStyle.stroke
              ..strokeWidth = width,
          );
        }
      case CircleItem(c: final ctr, :final r, :final fill, :final stroke, :final width):
        if (fill != null) c.drawCircle(ctr, r, Paint()..color = fill);
        if (stroke != null) {
          // PIL рисует контур внутрь круга – повторяем, чтобы размеры совпали
          c.drawCircle(
            ctr,
            math.max(0, r - width / 2),
            Paint()
              ..color = stroke
              ..style = PaintingStyle.stroke
              ..strokeWidth = width,
          );
        }
      case TextItem(:final at, :final text, :final size, :final anchor, :final color):
        _drawText(c, at, text, size, anchor, color ?? Colors.black);
    }
  }
  return rec.endRecording();
}

void _drawText(Canvas c, Offset at, String text, double size, String anchor, Color color) {
  final tp = TextPainter(
    text: TextSpan(
      text: text,
      style: TextStyle(fontFamily: 'Arial', fontSize: size, color: color, height: 1.0),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  final h = anchor.isNotEmpty ? anchor[0] : 'l';
  final v = anchor.length > 1 ? anchor[1] : 'a';
  final dx = switch (h) {
    'm' => -tp.width / 2,
    'r' => -tp.width,
    _ => 0.0,
  };
  final base = tp.computeDistanceToActualBaseline(TextBaseline.alphabetic);
  final dy = switch (v) {
    'm' => -base * 0.62, // PIL «middle» – середина между верхом прописных и низом
    'b' || 's' => -base,
    'd' => -tp.height,
    _ => 0.0,
  };
  tp.paint(c, at + Offset(dx, dy));
}

class _Painter extends CustomPainter {
  final Scene? scene;
  final ui.Picture? picture;
  final Map<AnnotObj, ui.Image> annots;
  final double k;
  final Offset o;
  final bool grid;
  final Hit? hover, selected;
  final Tool tool;
  final Tok tok;

  _Painter({
    required this.scene,
    required this.picture,
    required this.annots,
    required this.k,
    required this.o,
    required this.grid,
    required this.hover,
    required this.selected,
    required this.tool,
    required this.tok,
  });

  Offset S(Offset m) => m * k + o;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = tok.paper);
    final s = scene;
    if (s == null) return;
    if (grid) _grid(canvas, size);

    canvas.save();
    canvas.translate(o.dx, o.dy);
    canvas.scale(k);
    for (final a in s.annots) {
      final img = annots[a];
      if (img == null) continue;
      canvas.drawImageRect(
        img,
        Rect.fromLTWH(0, 0, img.width.toDouble(), img.height.toDouble()),
        a.rect,
        Paint()..filterQuality = FilterQuality.medium,
      );
    }
    if (picture != null) canvas.drawPicture(picture!);
    canvas.restore();

    // линия склейки листов
    if (s.sheetCut != null) {
      final x = S(Offset(s.sheetCut!, 0)).dx;
      final p = Paint()
        ..color = const Color(0xFFC0392B)
        ..strokeWidth = 1;
      for (double y = 0; y < size.height; y += 12) {
        canvas.drawLine(Offset(x, y), Offset(x, y + 7), p);
      }
    }

    _mark(canvas, hover, hovered: true);
    _mark(canvas, selected, hovered: false);
  }

  void _mark(Canvas canvas, Hit? h, {required bool hovered}) {
    if (h == null) return;
    final col = hovered ? tok.accent.withValues(alpha: 0.55) : tok.accent;
    final stroke = Paint()
      ..color = col
      ..style = PaintingStyle.stroke
      ..strokeWidth = hovered ? 1 : 1.6;
    switch (h) {
      case JointHit(:final j):
        final c = S(j.pos);
        final r = math.max(7.0, 3.6 * k);
        if (!hovered) canvas.drawCircle(c, r, Paint()..color = tok.accentSoft);
        canvas.drawCircle(c, r, stroke);
      case SectionHit(:final sec):
        final p = Paint()
          ..color = tok.accent.withValues(alpha: hovered ? 0.22 : 0.4)
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = math.max(5.0, 2.2 * k);
        for (final (a, b) in sec.segs) {
          canvas.drawLine(S(a), S(b), p);
        }
      case SignalHit(s: final sg):
        final r = Rect.fromPoints(S(sg.box.topLeft), S(sg.box.bottomRight)).inflate(4);
        if (!hovered) canvas.drawRect(r, Paint()..color = tok.accentSoft);
        canvas.drawRect(r, stroke);
      case EdgeHit(:final at):
        if (tool != Tool.joint) return;
        final c = S(at);
        final hh = math.max(5.0, 1.2 * k);
        final p = Paint()
          ..color = tok.accent
          ..strokeWidth = 1.5;
        canvas.drawLine(c.translate(0, -hh), c.translate(0, hh), p);
        canvas.drawLine(c.translate(-hh * .6, -hh), c.translate(hh * .6, -hh), p);
        canvas.drawLine(c.translate(-hh * .6, hh), c.translate(hh * .6, hh), p);
    }
  }

  /// Миллиметровка 1 / 5 / 10 мм – по экрану, чтобы линии были в 1 px при любом зуме.
  void _grid(Canvas canvas, Size size) {
    final x0 = -o.dx / k, x1 = (size.width - o.dx) / k;
    final y0 = -o.dy / k, y1 = (size.height - o.dy) / k;
    void lines(double step, Color col, double w) {
      final p = Paint()
        ..color = col
        ..strokeWidth = w;
      for (var i = (x0 / step).floor(); i <= (x1 / step).ceil(); i++) {
        final x = i * step * k + o.dx;
        canvas.drawLine(Offset(x, 0), Offset(x, size.height), p);
      }
      for (var i = (y0 / step).floor(); i <= (y1 / step).ceil(); i++) {
        final y = i * step * k + o.dy;
        canvas.drawLine(Offset(0, y), Offset(size.width, y), p);
      }
    }

    if (k >= 6) lines(1, const Color(0xFFF6E7DC), 1);
    if (k >= 2.5) lines(5, const Color(0xFFF0D3BF), 1);
    if (k >= 0.9) {
      lines(10, k >= 2.5 ? const Color(0xFFE7B89A) : const Color(0xFFF3DCCB), 1);
    } else {
      lines(50, const Color(0xFFEFD2BE), 1); // общий вид – клетка 5 см
    }
  }

  @override
  bool shouldRepaint(_Painter old) =>
      old.scene != scene ||
      old.picture != picture ||
      old.k != k ||
      old.o != o ||
      old.grid != grid ||
      old.hover != hover ||
      old.selected != selected ||
      old.tool != tool ||
      old.tok != tok ||
      old.annots.length != annots.length;
}
