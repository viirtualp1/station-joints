import 'package:flutter/material.dart';

import '../theme.dart';

/// Мелкие элементы интерфейса в инженерном стиле: плоские, линии 1 px, один акцент.

class Sep extends StatelessWidget {
  const Sep({super.key});
  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 20, margin: const EdgeInsets.symmetric(horizontal: 8), color: Tok.of(context).line);
}

/// Заголовок группы: мелкие прописные серым.
class Caption extends StatelessWidget {
  final String text;
  final Color? color;
  const Caption(this.text, {super.key, this.color});
  @override
  Widget build(BuildContext context) => Text(
    text.toUpperCase(),
    style: TextStyle(
      fontSize: 10.5,
      letterSpacing: 0.6,
      fontWeight: FontWeight.w600,
      color: color ?? Tok.of(context).muted,
    ),
  );
}

class IconBtn extends StatelessWidget {
  final IconData icon;
  final String tip;
  final VoidCallback? onTap;
  final bool active, flip;
  final double size;
  const IconBtn(this.icon, this.tip, this.onTap, {super.key, this.active = false, this.flip = false, this.size = 30});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    Widget ic = Icon(
      icon,
      size: 17,
      color: onTap == null ? t.muted.withValues(alpha: .5) : (active ? t.text : t.muted),
    );
    if (flip) ic = Transform.flip(flipX: true, child: ic);
    return Tooltip(
      message: tip,
      child: InkWell(
        onTap: onTap,
        hoverColor: t.panel2,
        child: SizedBox(
          width: size,
          height: size,
          child: Center(child: ic),
        ),
      ),
    );
  }
}

class TextBtn extends StatelessWidget {
  final String text;
  final String? shortcut;
  final VoidCallback? onTap;
  final bool outlined, danger;
  const TextBtn(this.text, this.shortcut, this.onTap, {super.key, this.outlined = false, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final col = onTap == null ? t.muted.withValues(alpha: .5) : (danger ? t.danger : t.text);
    final child = Container(
      height: 28,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: outlined ? BoxDecoration(border: Border.all(color: t.line), color: t.panel) : null,
      // по центру по высоте, по ширине – как содержимое (widthFactor: 1)
      child: Align(
        widthFactor: 1,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          // шрифты разные (Segoe UI и Consolas) – выравниваем по базовой линии, не по центру
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(text, style: TextStyle(fontSize: 12.5, color: col)),
            if (shortcut != null) ...[
              const SizedBox(width: 6),
              Text(
                shortcut!,
                style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
              ),
            ],
          ],
        ),
      ),
    );
    return InkWell(onTap: onTap, hoverColor: t.panel2, child: child);
  }
}

class PrimaryBtn extends StatelessWidget {
  final String text;
  final VoidCallback? onTap;
  const PrimaryBtn(this.text, this.onTap, {super.key});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      child: Container(
        height: 30,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        color: onTap == null ? t.muted : t.accent,
        child: Align(
          widthFactor: 1, // ширина – по тексту (в диалогах кнопки не растягиваются)
          child: Text(
            text,
            style: const TextStyle(fontSize: 12.5, color: Colors.white, fontWeight: FontWeight.w600),
          ),
        ),
      ),
    );
  }
}

/// Инструмент панели: иконка, имя, клавиша в подсказке; активный – подчёркнут акцентом.
class ToolBtn extends StatelessWidget {
  final IconData icon;
  final String name, shortcut;
  final bool on;
  final VoidCallback? onTap;
  const ToolBtn(this.icon, this.name, this.shortcut, this.on, this.onTap, {super.key});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final col = onTap == null ? t.muted.withValues(alpha: .5) : (on ? t.accent : t.text);
    return Tooltip(
      message: '$name ($shortcut)',
      child: InkWell(
        onTap: onTap,
        hoverColor: t.panel2,
        child: Container(
          height: 28,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            color: on ? t.accentSoft : null,
            border: Border(bottom: BorderSide(color: on ? t.accent : Colors.transparent, width: 2)),
          ),
          child: Row(
            children: [
              Icon(icon, size: 16, color: col),
              const SizedBox(width: 5),
              Text(name, style: TextStyle(fontSize: 12.5, color: col)),
            ],
          ),
        ),
      ),
    );
  }
}

/// Раздел боковой панели: заголовок, необязательная кнопка справа, содержимое.
class PanelSection extends StatelessWidget {
  final String title;
  final Widget? trailing;
  final List<Widget> children;
  const PanelSection(this.title, {super.key, this.trailing, required this.children});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Container(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: t.line)),
      ),
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: 24,
            child: Row(children: [Expanded(child: Caption(title)), ?trailing]),
          ),
          const SizedBox(height: 4),
          ...children,
        ],
      ),
    );
  }
}

/// Флажок с подписью; длинная подпись переносится, а не обрезается.
class CheckRow extends StatelessWidget {
  final String text;
  final bool value;
  final ValueChanged<bool>? onChanged;
  const CheckRow(this.text, this.value, this.onChanged, {super.key});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final on = onChanged;
    return InkWell(
      onTap: on == null ? null : () => on(!value),
      hoverColor: t.panel2,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 26),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  color: value ? t.accent : t.paper,
                  border: Border.all(color: value ? t.accent : t.muted, width: 1),
                ),
                child: value ? const Icon(Icons.check, size: 12, color: Colors.white) : null,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(text, style: TextStyle(fontSize: 12.5, height: 1.3, color: on == null ? t.muted : t.text)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Кнопка сегментированного переключателя.
class SegButton extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback? onTap;
  final bool monoFont;
  const SegButton(this.text, this.on, this.onTap, {super.key, this.monoFont = true});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      child: Container(
        height: 26,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? t.accent : t.panel2,
          border: Border.all(color: on ? t.accent : t.line),
        ),
        child: Text(
          text,
          style: TextStyle(
            fontSize: 12,
            fontFamily: monoFont ? mono : null,
            color: on ? Colors.white : (onTap == null ? t.muted : t.text),
          ),
        ),
      ),
    );
  }
}

/// Вкладка панели: подчёркнутая акцентом, если выбрана. Не шире отведённого места –
/// длинная подпись обрезается (шрифт в системе может быть шире ожидаемого).
class TabButton extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback onTap;
  const TabButton(this.text, this.on, this.onTap, {super.key});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      hoverColor: t.panel2,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: on ? t.accent : Colors.transparent, width: 2)),
        ),
        child: Text(
          text,
          maxLines: 1,
          softWrap: false,
          overflow: TextOverflow.fade,
          style: TextStyle(
            fontSize: 12,
            color: on ? t.text : t.muted,
            fontWeight: on ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }
}

/// Строка «ключ – значение» в панели свойств.
class KeyValue extends StatelessWidget {
  final String k, v;
  final bool monoValue;
  const KeyValue(this.k, this.v, {super.key, this.monoValue = false});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 92,
            child: Text(k, style: TextStyle(fontSize: 12, color: t.muted)),
          ),
          Expanded(
            child: Text(v, style: TextStyle(fontSize: 12, color: t.text, fontFamily: monoValue ? mono : null)),
          ),
        ],
      ),
    );
  }
}

/// Пункт выпадающего меню: текст и клавиша справа.
PopupMenuItem<T> menuItem<T>(BuildContext context, T value, String text, String shortcut, {bool enabled = true}) {
  final t = Tok.of(context);
  return PopupMenuItem<T>(
    value: value,
    height: 32,
    enabled: enabled,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        Expanded(
          child: Text(text, style: TextStyle(fontSize: 13, color: enabled ? t.text : t.muted)),
        ),
        Text(
          shortcut,
          style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
        ),
      ],
    ),
  );
}

/// Контекстное меню в точке [global] в стиле приложения.
Future<T?> showAppMenu<T>(BuildContext context, Offset global, List<PopupMenuEntry<T>> items) {
  final t = Tok.of(context);
  return showMenu<T>(
    context: context,
    position: RelativeRect.fromLTRB(global.dx, global.dy, global.dx, global.dy),
    shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
    color: t.panel,
    items: items,
  );
}
