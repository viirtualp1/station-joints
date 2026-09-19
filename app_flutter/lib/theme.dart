import 'package:flutter/material.dart';

/// Инженерный (CAD) стиль: нейтральные серые поверхности, линии 1 px вместо теней,
/// один приглушённый акцент – только для выделения и активного инструмента.
class Tok {
  final Color bg, panel, panel2, line, text, muted, accent, accentSoft, danger, paper;
  const Tok({
    required this.bg,
    required this.panel,
    required this.panel2,
    required this.line,
    required this.text,
    required this.muted,
    required this.accent,
    required this.accentSoft,
    required this.danger,
    required this.paper,
  });

  static const light = Tok(
    bg: Color(0xFFE6E7E9),
    panel: Color(0xFFF5F5F6),
    panel2: Color(0xFFEBECEE),
    line: Color(0xFFD2D4D8),
    text: Color(0xFF1B1D21),
    muted: Color(0xFF6A6F78),
    accent: Color(0xFF2F5FA8),
    accentSoft: Color(0x222F5FA8),
    danger: Color(0xFFB3261E),
    paper: Color(0xFFFFFFFF),
  );

  static const dark = Tok(
    bg: Color(0xFF151618),
    panel: Color(0xFF1E1F22),
    panel2: Color(0xFF26282B),
    line: Color(0xFF34363A),
    text: Color(0xFFDADCE0),
    muted: Color(0xFF8B9098),
    accent: Color(0xFF6D9BE0),
    accentSoft: Color(0x336D9BE0),
    danger: Color(0xFFE5736B),
    paper: Color(0xFFFBFBFA), // лист остаётся бумажным и в тёмной теме
  );

  static Tok of(BuildContext c) =>
      Theme.of(c).brightness == Brightness.dark ? dark : light;
}

const mono = 'Consolas';

ThemeData buildTheme(Brightness b) {
  final t = b == Brightness.dark ? Tok.dark : Tok.light;
  final base = ThemeData(
    brightness: b,
    useMaterial3: true,
    fontFamily: 'Segoe UI',
    visualDensity: VisualDensity.compact,
    colorScheme: ColorScheme.fromSeed(seedColor: t.accent, brightness: b).copyWith(
      primary: t.accent,
      surface: t.panel,
      onSurface: t.text,
      outline: t.line,
    ),
    scaffoldBackgroundColor: t.bg,
    dividerColor: t.line,
    splashFactory: NoSplash.splashFactory,
    tooltipTheme: TooltipThemeData(
      waitDuration: const Duration(milliseconds: 500),
      textStyle: TextStyle(fontSize: 12, color: t.panel),
      decoration: BoxDecoration(color: t.text, borderRadius: BorderRadius.circular(2)),
    ),
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: t.text, displayColor: t.text),
  );
}
