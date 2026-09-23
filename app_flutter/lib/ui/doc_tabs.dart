import 'package:flutter/gestures.dart' show kMiddleMouseButton, kSecondaryMouseButton;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme.dart';

/// Таб открытой схемы: как в VS Code – у несохранённой точка, при наведении она
/// становится крестиком; средняя кнопка – закрыть, правая – меню, двойной клик – имя.
class DocTab extends StatefulWidget {
  final String title, tooltip, editText;
  final bool project, active, dirty, loading, editing;
  final VoidCallback onTap, onClose, onDoubleTap, onCancelRename;
  final void Function(Offset global) onMenu;
  final void Function(String) onRename;
  const DocTab({
    super.key,
    required this.title,
    required this.tooltip,
    required this.project,
    required this.active,
    required this.dirty,
    required this.loading,
    required this.editing,
    required this.editText,
    required this.onTap,
    required this.onClose,
    required this.onDoubleTap,
    required this.onMenu,
    required this.onRename,
    required this.onCancelRename,
  });

  @override
  State<DocTab> createState() => _DocTabState();
}

class _DocTabState extends State<DocTab> {
  bool _hover = false;
  DateTime? _lastTap; // двойной клик – без задержки обычного клика

  void _tap() {
    final now = DateTime.now();
    final dbl = _lastTap != null && now.difference(_lastTap!) < const Duration(milliseconds: 400);
    _lastTap = dbl ? null : now;
    dbl ? widget.onDoubleTap() : widget.onTap();
  }

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final w = widget;
    final showClose = _hover || (w.active && !w.dirty);
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: Listener(
        onPointerDown: (e) {
          if (e.buttons == kMiddleMouseButton) w.onClose();
          if (e.buttons == kSecondaryMouseButton) w.onMenu(e.position);
        },
        child: Tooltip(
          message: w.tooltip,
          waitDuration: const Duration(milliseconds: 700),
          child: InkWell(
            onTap: _tap,
            hoverColor: Colors.transparent,
            child: Container(
              height: 32,
              constraints: const BoxConstraints(maxWidth: 240),
              padding: const EdgeInsets.only(left: 10, right: 4),
              decoration: BoxDecoration(
                color: w.active || _hover ? t.panel : Colors.transparent,
                border: Border(
                  top: BorderSide(color: w.active ? t.accent : Colors.transparent, width: 2),
                  right: BorderSide(color: t.line),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    w.project ? Icons.description_outlined : Icons.image_outlined,
                    size: 14,
                    color: w.active ? t.accent : t.muted,
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: w.editing
                        ? TabNameField(text: w.editText, onSubmit: w.onRename, onCancel: w.onCancelRename)
                        : Text(
                            w.title,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 12.5,
                              color: w.active ? t.text : t.muted,
                              fontStyle: w.loading ? FontStyle.italic : FontStyle.normal,
                            ),
                          ),
                  ),
                  const SizedBox(width: 4),
                  SizedBox(
                    width: 22,
                    height: 22,
                    child: showClose
                        ? Tooltip(
                            message: 'Закрыть (Ctrl+W)',
                            child: InkWell(
                              onTap: w.onClose,
                              hoverColor: t.panel2,
                              child: Icon(Icons.close, size: 14, color: t.muted),
                            ),
                          )
                        : w.dirty
                        ? Center(
                            child: Container(
                              width: 8,
                              height: 8,
                              decoration: BoxDecoration(color: t.text, shape: BoxShape.circle),
                            ),
                          )
                        : null,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Поле имени прямо в табе: Enter – сохранить, Esc – отмена, клик мимо – сохранить.
class TabNameField extends StatefulWidget {
  final String text;
  final void Function(String) onSubmit;
  final VoidCallback onCancel;
  const TabNameField({super.key, required this.text, required this.onSubmit, required this.onCancel});

  @override
  State<TabNameField> createState() => _TabNameFieldState();
}

class _TabNameFieldState extends State<TabNameField> {
  late final _ctl = TextEditingController(text: widget.text)
    ..selection = TextSelection(baseOffset: 0, extentOffset: widget.text.length);
  final _node = FocusNode();
  bool _done = false;

  @override
  void initState() {
    super.initState();
    _node.addListener(() {
      if (!_node.hasFocus) _finish(true);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _node.requestFocus());
  }

  void _finish(bool save) {
    if (_done) return;
    _done = true;
    save ? widget.onSubmit(_ctl.text) : widget.onCancel();
  }

  @override
  void dispose() {
    _ctl.dispose();
    _node.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final border = OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: t.accent));
    return SizedBox(
      width: 150,
      height: 22,
      child: CallbackShortcuts(
        bindings: {const SingleActivator(LogicalKeyboardKey.escape): () => _finish(false)},
        child: TextField(
          controller: _ctl,
          focusNode: _node,
          onSubmitted: (_) => _finish(true),
          style: TextStyle(fontSize: 12.5, color: t.text),
          cursorWidth: 1.2,
          decoration: InputDecoration(
            isDense: true,
            contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 5),
            filled: true,
            fillColor: t.bg,
            enabledBorder: border,
            focusedBorder: border,
          ),
        ),
      ),
    );
  }
}
