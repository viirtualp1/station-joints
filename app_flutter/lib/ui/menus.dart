import 'package:flutter/material.dart';

import '../recent.dart';
import '../theme.dart';
import 'controls.dart';
import 'lists.dart';

/// Кнопка меню панели инструментов: текст и стрелка вниз.
class _MenuButton extends StatelessWidget {
  final String text;
  final bool enabled, outlined;
  const _MenuButton(this.text, {required this.enabled, this.outlined = false});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Container(
      height: 28,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: outlined ? BoxDecoration(border: Border.all(color: t.line)) : null,
      child: Row(
        children: [
          Text(text, style: TextStyle(fontSize: 12.5, color: enabled ? t.text : t.muted)),
          Icon(Icons.arrow_drop_down, size: 18, color: t.muted),
        ],
      ),
    );
  }
}

enum ExportKind { pdf, png, docx }

class ExportMenu extends StatelessWidget {
  final bool enabled;
  final void Function(ExportKind) onPick;
  const ExportMenu({super.key, required this.enabled, required this.onPick});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return PopupMenuButton<ExportKind>(
      enabled: enabled,
      tooltip: 'Экспорт',
      position: PopupMenuPosition.under,
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      elevation: 2,
      onSelected: onPick,
      itemBuilder: (c) => [
        menuItem(c, ExportKind.pdf, 'PDF – два листа, М 1:1', 'Ctrl+P'),
        menuItem(c, ExportKind.png, 'PNG – вся схема', 'Ctrl+E'),
        menuItem(c, ExportKind.docx, 'Ведомость для записки (Word)', ''),
      ],
      child: _MenuButton('Экспорт', enabled: enabled, outlined: true),
    );
  }
}

class FileMenu extends StatelessWidget {
  final bool ready, hasScene;
  final List<RecentItem> recent;
  final VoidCallback onOpen, onSave, onSaveAs, onClear;
  final void Function(RecentItem) onRecent;
  const FileMenu({
    super.key,
    required this.ready,
    required this.hasScene,
    required this.recent,
    required this.onOpen,
    required this.onSave,
    required this.onSaveAs,
    required this.onRecent,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return PopupMenuButton<Object>(
      enabled: ready,
      tooltip: 'Файл',
      position: PopupMenuPosition.under,
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      elevation: 2,
      constraints: const BoxConstraints(minWidth: 280, maxWidth: 360),
      onSelected: (v) => switch (v) {
        'open' => onOpen(),
        'save' => onSave(),
        'saveas' => onSaveAs(),
        'clear' => onClear(),
        RecentItem it => onRecent(it),
        _ => null,
      },
      itemBuilder: (c) => [
        menuItem<Object>(c, 'open', 'Открыть…', 'Ctrl+O'),
        menuItem<Object>(c, 'save', 'Сохранить работу', 'Ctrl+S', enabled: hasScene),
        menuItem<Object>(c, 'saveas', 'Сохранить как…', 'Ctrl+Shift+S', enabled: hasScene),
        if (recent.isNotEmpty) ...[
          const PopupMenuDivider(height: 9),
          const PopupMenuItem<Object>(enabled: false, height: 22, child: Caption('Недавние')),
          for (final it in recent.take(8))
            PopupMenuItem<Object>(
              value: it,
              height: 40,
              child: Row(
                children: [
                  Icon(it.project ? Icons.description_outlined : Icons.image_outlined, size: 16, color: t.muted),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(it.name, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: t.text)),
                        Text(
                          folderOf(it.path),
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 11, color: t.muted),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          const PopupMenuDivider(height: 9),
          menuItem<Object>(c, 'clear', 'Очистить список', ''),
        ],
      ],
      child: _MenuButton('Файл', enabled: ready),
    );
  }
}
