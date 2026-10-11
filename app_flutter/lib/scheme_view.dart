import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'scene.dart';
import 'theme.dart';

enum Tool { select, joint, track }

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

class NodeHit extends Hit {
  final NodeObj n;
  NodeHit(this.n);
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

/// Маршрут выбирают в списке; на схеме он подсвечивается целиком.
class RouteHit extends Hit {
  final RouteObj r;
  RouteHit(this.r);
}

/// Управление камерой снаружи (кнопки зума, переход к светофору).
class SchemeController extends ChangeNotifier {
  _SchemeViewState? _s;
  double get zoomPercent => _s?._zoomPercent ?? 100;
  void zoomBy(double f) => _s?._zoomAtCenter(f);
  void fit() => _s?._fit(animate: true);
  void focus(Rect r) => _s?._focus(r);

  /// Точка схемы (мм) -> точка холста (px) – для тестов и подсказок.
  Offset? toScreen(Offset mm) => _s == null ? null : mm * _s!._k + _s!._o;
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
  final void Function(JointObj j, double t)? onMoveJoint;
  final void Function(Map<String, dynamic> a, Map<String, dynamic> b)? onAddSegment;
  final void Function(Offset global, NodeObj n)? onNodeMenu;

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
    this.onMoveJoint,
    this.onAddSegment,
    this.onNodeMenu,
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
  // надписи с картинки: декодированные PNG по содержимому (после правки сцена новая,
  // а надписи те же – не декодируем заново); версия – чтобы холст перерисовался
  final Map<String, ui.Image> _annotImg = {};
  int _annotVersion = 0;

  late final AnimationController _anim = AnimationController(vsync: this, duration: const Duration(milliseconds: 260));
  double _k0 = 1, _k1 = 1;
  Offset _c0 = Offset.zero, _c1 = Offset.zero; // центр экрана в мм – начало/конец

  // перетаскивание стыка вдоль пути
  JointObj? _dragJoint;
  Offset? _dragPos;
  double? _dragT;
  // рисование нового отрезка (инструмент «Пути»)
  (Map<String, dynamic>, Offset)? _segStart, _segEnd;

  Offset? _down; // точка нажатия (для клика против перетаскивания)
  bool _panning = false;
  int _buttons = 0;

  double get _zoomPercent {
    final s = widget.scene;
    if (s == null || _size.isEmpty) return 100;
    return _k / _fitScale(s.bounds) * 100;
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
  void initState() {
    super.initState();
    widget.controller._s = this;
    _anim.addListener(_tick);
    _loadAnnots();
  }

  @override
  void dispose() {
    _anim.dispose();
    if (widget.controller._s == this) widget.controller._s = null;
    for (final img in _annotImg.values) {
      img.dispose();
    }
    super.dispose();
  }

  Future<void> _loadAnnots() async {
    final s = widget.scene;
    final want = {for (final a in s?.annots ?? const <AnnotObj>[]) a.key};
    // надписи, которых в сцене больше нет, – освободить
    for (final k in _annotImg.keys.where((k) => !want.contains(k)).toList()) {
      _annotImg.remove(k)!.dispose();
    }
    for (final a in s?.annots ?? const <AnnotObj>[]) {
      if (_annotImg.containsKey(a.key)) continue;
      final codec = await ui.instantiateImageCodec(a.png);
      final fr = await codec.getNextFrame();
      if (!mounted || !identical(widget.scene, s)) {
        fr.image.dispose();
        return;
      }
      setState(() {
        _annotImg[a.key] = fr.image;
        _annotVersion++;
      });
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
    if (!edges) {
      // светофор – раньше стыка: он рядом со стыком, но его рамка точная
      for (final sg in s.signals) {
        if (sg.box.inflate(0.5).contains(m)) return SignalHit(sg);
      }
    }
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
      final n = _nodeAt(m, 7 / _k);
      if (n != null) return NodeHit(n);
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

  NodeObj? _nodeAt(Offset m, double tol) {
    NodeObj? best;
    var bd = tol;
    for (final n in widget.scene?.nodes ?? const <NodeObj>[]) {
      final d = (n.pos - m).distance;
      if (d < bd) {
        bd = d;
        best = n;
      }
    }
    return best;
  }

  /// Инструмент «Пути»: узел (конец/стрелка) важнее отрезка.
  Hit? _trackHit(Offset screen) {
    final m = _toModel(screen);
    final n = _nodeAt(m, 9 / _k);
    if (n != null) return NodeHit(n);
    final h = _hitTest(screen, edges: true);
    return h is EdgeHit ? h : null;
  }

  static double _snap5(double v) => (v / 5).round() * 5.0;

  /// Точка нового отрезка: узел, точка на пути (делит его) или свободная – по сетке 5 мм.
  (Map<String, dynamic>, Offset) _snapPoint(Offset screen) {
    final m = _toModel(screen);
    final n = _nodeAt(m, 10 / _k);
    if (n != null) return ({'node': n.id}, n.pos);
    final h = _hitTest(screen, edges: true);
    if (h is EdgeHit) {
      final near = h.t < 2 || h.t > h.e.length - 2;
      if (!near) return ({'edge': h.e.id, 't': h.t}, h.at);
    }
    final p = Offset(_snap5(m.dx), _snap5(m.dy));
    return ({'x': p.dx, 'y': p.dy}, p);
  }

  /// Стык тянется вдоль своего отрезка; положение – по сетке 5 мм.
  void _dragJointTo(Offset screen) {
    final s = widget.scene!;
    final j = _dragJoint!;
    final e = s.edges.where((e) => e.id == j.edge).firstOrNull;
    if (e == null) return;
    final m = _toModel(screen);
    final ab = e.b - e.a;
    final L = ab.distance;
    if (L < 1.5) return;
    var f = (((m - e.a).dx * ab.dx + (m - e.a).dy * ab.dy) / ab.distanceSquared).clamp(0.0, 1.0);
    // сетка: по x для пологих отрезков, по y для крутых
    if (ab.dx.abs() >= ab.dy.abs()) {
      final x = _snap5(e.a.dx + ab.dx * f);
      f = (x - e.a.dx) / ab.dx;
    } else {
      final y = _snap5(e.a.dy + ab.dy * f);
      f = (y - e.a.dy) / ab.dy;
    }
    final t = (f * L).clamp(0.5, L - 0.5);
    setState(() {
      _dragT = t;
      _dragPos = e.a + ab * (t / L);
    });
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
    _dragJoint = null;
    _segStart = _segEnd = null;
    if (e.buttons != kPrimaryButton || widget.scene == null) return;
    if (widget.tool == Tool.select && widget.onMoveJoint != null) {
      final h = _hitTest(e.localPosition);
      if (h is JointHit) _dragJoint = h.j; // потянули стык
    } else if (widget.tool == Tool.track && widget.onAddSegment != null) {
      _segStart = _snapPoint(e.localPosition);
    }
  }

  void _onMove(PointerMoveEvent e) {
    if (_down == null) return;
    final moved = (e.localPosition - _down!).distance > 4;
    if (_dragJoint != null && _buttons == kPrimaryButton) {
      if (moved || _dragPos != null) _dragJointTo(e.localPosition);
      return;
    }
    if (_segStart != null && _buttons == kPrimaryButton) {
      if (moved || _segEnd != null) setState(() => _segEnd = _snapPoint(e.localPosition));
      return;
    }
    if (!_panning && moved && _buttons == kPrimaryButton) {
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
    // конец перетаскивания стыка / рисования отрезка
    final dj = _dragJoint, dt = _dragT;
    if (dj != null && dt != null) {
      setState(() {
        _dragJoint = null;
        _dragPos = _dragT = null;
      });
      if ((dt - dj.t).abs() > 0.01) widget.onMoveJoint!(dj, dt);
      return;
    }
    _dragJoint = null;
    final a = _segStart, b = _segEnd;
    if (a != null && b != null) {
      setState(() => _segStart = _segEnd = null);
      if ((a.$2 - b.$2).distance > 1) widget.onAddSegment!(a.$1, b.$1);
      return;
    }
    _segStart = _segEnd = null;
    if (wasPan || down == null) return;
    if (_buttons == kSecondaryButton) {
      final h = _hitTest(e.localPosition);
      if (h is JointHit || h is SignalHit) {
        widget.onSelect(h);
        widget.onContext(e.position, h!);
      }
      return;
    }
    if (_buttons != kPrimaryButton) return;
    if (widget.tool == Tool.track) {
      final h = _trackHit(e.localPosition);
      widget.onSelect(h);
      if (h is NodeHit && h.n.isEnd) widget.onNodeMenu?.call(e.position, h.n);
      return;
    }
    if (widget.tool == Tool.joint) {
      final h = _hitTest(e.localPosition, edges: true);
      if (h is EdgeHit) widget.onAddJoint(h);
      return;
    }
    final h = _hitTest(e.localPosition);
    widget.onSelect(h is EdgeHit ? null : h);
  }

  void _onHover(PointerHoverEvent e) {
    final h = widget.tool == Tool.track
        ? _trackHit(e.localPosition)
        : _hitTest(e.localPosition, edges: widget.tool == Tool.joint);
    final s = widget.scene;
    final ord = s == null ? null : _toModel(e.localPosition).dx - s.originX;
    widget.onHover(h, ord);
    final same = switch ((h, _hover)) {
      (JointHit a, JointHit b) => a.j.id == b.j.id,
      (SignalHit a, SignalHit b) => a.s.id == b.s.id,
      (SectionHit a, SectionHit b) => a.sec.id == b.sec.id,
      (NodeHit a, NodeHit b) => a.n.id == b.n.id,
      (EdgeHit a, EdgeHit b) => a.e.id == b.e.id && (a.at - b.at).distance < 0.2,
      (null, null) => true,
      _ => false,
    };
    if (!same) setState(() => _hover = h);
  }

  MouseCursor get _cursor {
    if (_panning) return SystemMouseCursors.grabbing;
    if (_dragJoint != null && _dragPos != null) return SystemMouseCursors.resizeLeftRight;
    if (widget.tool == Tool.track) return _hover == null ? SystemMouseCursors.precise : SystemMouseCursors.click;
    if (widget.tool == Tool.joint) {
      return _hover is EdgeHit ? SystemMouseCursors.precise : SystemMouseCursors.basic;
    }
    if (_hover is JointHit) return SystemMouseCursors.grab;
    return _hover is SignalHit || _hover is SectionHit || _hover is NodeHit
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
                  annotVersion: _annotVersion,
                  k: _k,
                  o: _o,
                  grid: widget.grid,
                  hover: _hover,
                  selected: widget.selected,
                  tool: widget.tool,
                  tok: tok,
                  dragPos: _dragPos,
                  segA: _segStart?.$2,
                  segB: _segEnd?.$2,
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
  final Map<String, ui.Image> annots;
  final int annotVersion;
  final double k;
  final Offset o;
  final bool grid;
  final Hit? hover, selected;
  final Tool tool;
  final Tok tok;
  final Offset? dragPos, segA, segB;

  _Painter({
    required this.scene,
    required this.picture,
    required this.annots,
    required this.annotVersion,
    required this.k,
    required this.o,
    required this.grid,
    required this.hover,
    required this.selected,
    required this.tool,
    required this.tok,
    this.dragPos,
    this.segA,
    this.segB,
  });

  Offset S(Offset m) => m * k + o;

  /// Тёмная тема: «умная» инверсия чертежа – яркость наоборот, оттенок тот же
  /// (как CSS invert(1) hue-rotate(180deg)): чёрные линии – белые, лист – тёмный,
  /// красные/синие/зелёные элементы остаются красными/синими/зелёными.
  static const _smartInvert = ColorFilter.matrix(<double>[
    0.574, -1.430, -0.144, 0, 255, //
    -0.426, -0.430, -0.144, 0, 255, //
    -0.426, -1.430, 0.856, 0, 255, //
    0, 0, 0, 1, 0,
  ]);

  @override
  void paint(Canvas canvas, Size size) {
    final dark = identical(tok, Tok.dark);
    // лист и миллиметровка – своими цветами; инвертируется только чертёж
    canvas.drawRect(Offset.zero & size, Paint()..color = dark ? const Color(0xFF1C1C1E) : tok.paper);
    final s = scene;
    if (s != null && grid) _grid(canvas, size, dark);
    if (dark) canvas.saveLayer(Offset.zero & size, Paint()..colorFilter = _smartInvert);
    if (s != null) _drawSheet(canvas, size, s);
    if (dark) canvas.restore();
    if (s == null) return;
    if (tool == Tool.track) _ends(canvas, s);
    _mark(canvas, hover, hovered: true);
    _mark(canvas, selected, hovered: false);
    _preview(canvas);
  }

  /// Инструмент «Пути»: концы путей и стрелки – видно, что можно править.
  void _ends(Canvas canvas, Scene s) {
    for (final n in s.nodes) {
      final c = S(n.pos);
      if (n.isSwitch) {
        canvas.drawCircle(c, 3, Paint()..color = tok.muted);
        continue;
      }
      if (!n.isEnd) continue;
      final col = switch (n.mark) {
        'peregon' => const Color(0xFF2F8F4E),
        'pp' => const Color(0xFFB7791F),
        _ => tok.accent,
      };
      canvas.drawRect(Rect.fromCenter(center: c, width: 8, height: 8), Paint()..color = col);
    }
  }

  /// Перетаскиваемый стык и новый отрезок.
  void _preview(Canvas canvas) {
    final p = Paint()
      ..color = tok.accent
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    if (dragPos != null) {
      final c = S(dragPos!);
      canvas.drawCircle(c, math.max(7.0, 3.6 * k), Paint()..color = tok.accentSoft);
      canvas.drawCircle(c, math.max(7.0, 3.6 * k), p);
      canvas.drawLine(c.translate(0, -math.max(6.0, 2.0 * k)), c.translate(0, math.max(6.0, 2.0 * k)), p);
    }
    if (segA != null && segB != null) {
      final a = S(segA!), b = S(segB!);
      final dir = b - a;
      final len = dir.distance;
      if (len > 0) {
        final u = dir / len;
        for (double d = 0; d < len; d += 10) {
          canvas.drawLine(a + u * d, a + u * math.min(d + 6, len), p);
        }
      }
      canvas.drawCircle(a, 4, Paint()..color = tok.accent);
      canvas.drawCircle(b, 4, Paint()..color = tok.accent);
    }
  }

  /// Надписи с картинки, чертёж, линия склейки листов.
  void _drawSheet(Canvas canvas, Size size, Scene s) {
    canvas.save();
    canvas.translate(o.dx, o.dy);
    canvas.scale(k);
    for (final a in s.annots) {
      final img = annots[a.key];
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
      case NodeHit(:final n):
        final c = S(n.pos);
        if (!hovered) canvas.drawCircle(c, 9, Paint()..color = tok.accentSoft);
        canvas.drawCircle(c, 9, stroke);
      case RouteHit(:final r):
        _route(canvas, r);
      case EdgeHit(:final e) when tool == Tool.track:
        // весь отрезок «от стрелки до стрелки»
        final p = Paint()
          ..color = tok.accent.withValues(alpha: hovered ? 0.3 : 0.55)
          ..strokeWidth = math.max(5.0, 2.2 * k)
          ..strokeCap = StrokeCap.round;
        for (final f in scene!.edges) {
          if (f.chain == e.chain) canvas.drawLine(S(f.a), S(f.b), p);
        }
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

  /// Маршрут: полоса по всему пути, кружок у светофора, стрелка в конце.
  void _route(Canvas canvas, RouteObj r) {
    if (r.segs.isEmpty) return;
    final w = math.max(5.0, 2.2 * k);
    final band = Paint()
      ..color = tok.accent.withValues(alpha: 0.45)
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = w;
    for (final (a, b) in r.segs) {
      canvas.drawLine(S(a), S(b), band);
    }
    final solid = Paint()..color = tok.accent;
    canvas.drawCircle(S(r.segs.first.$1), w * 0.9, solid);
    final (a, b) = r.segs.last;
    final d = S(b) - S(a);
    if (d.distance < 1) return;
    final u = d / d.distance, n = Offset(-u.dy, u.dx), tip = S(b);
    canvas.drawPath(
      Path()
        ..moveTo(tip.dx, tip.dy)
        ..lineTo((tip - u * w * 2.2 + n * w * 1.1).dx, (tip - u * w * 2.2 + n * w * 1.1).dy)
        ..lineTo((tip - u * w * 2.2 - n * w * 1.1).dx, (tip - u * w * 2.2 - n * w * 1.1).dy)
        ..close(),
      solid,
    );
  }

  /// Миллиметровка 1 / 5 / 10 мм – по экрану, чтобы линии были в 1 px при любом зуме.
  void _grid(Canvas canvas, Size size, bool dark) {
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

    if (dark) {
      // тёмная тема: едва тёплые линии чуть светлее фона – сетка не спорит с чертежом
      if (k >= 6) lines(1, const Color(0xFF222120), 1);
      if (k >= 2.5) lines(5, const Color(0xFF282624), 1);
      if (k >= 0.9) {
        lines(10, k >= 2.5 ? const Color(0xFF312D2A) : const Color(0xFF262422), 1);
      } else {
        lines(50, const Color(0xFF292725), 1);
      }
      return;
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
      old.dragPos != dragPos ||
      old.segA != segA ||
      old.segB != segB ||
      old.annotVersion != annotVersion;
}
