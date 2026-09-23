import 'package:flutter/material.dart';

import '../autosave.dart';
import '../theme.dart';
import '../update.dart';
import 'controls.dart';

/// Диалоги приложения – в одном стиле: рамка 1 px, без теней и скруглений.

Future<T?> _dialog<T>(
  BuildContext context, {
  required String title,
  required Widget content,
  required List<Widget> Function(BuildContext) actions,
  bool dismissible = true,
}) {
  final t = Tok.of(context);
  return showDialog<T>(
    context: context,
    barrierDismissible: dismissible,
    builder: (c) => AlertDialog(
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      backgroundColor: t.panel,
      title: Text(title, style: TextStyle(fontSize: 15, color: t.text)),
      content: content,
      actions: actions(c),
    ),
  );
}

Widget _body(BuildContext context, String text) =>
    Text(text, style: TextStyle(fontSize: 13, height: 1.45, color: Tok.of(context).muted));

enum SaveChoice { save, discard, cancel }

/// Несохранённые изменения: сохранить / не сохранять / отмена.
Future<SaveChoice> askSaveChanges(BuildContext context, String name) async =>
    await _dialog<SaveChoice>(
      context,
      title: 'Сохранить изменения?',
      content: _body(context, 'В схеме «$name» есть несохранённые правки.'),
      actions: (c) => [
        TextBtn('Отмена', null, () => Navigator.pop(c, SaveChoice.cancel)),
        TextBtn('Не сохранять', null, () => Navigator.pop(c, SaveChoice.discard), outlined: true),
        PrimaryBtn('Сохранить', () => Navigator.pop(c, SaveChoice.save)),
      ],
    ) ??
    SaveChoice.cancel;

String _hhmm(DateTime d) =>
    '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')} '
    '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

/// Остались резервные копии (программа закрылась, не сохранив правки): восстановить?
Future<bool> askRestore(BuildContext context, List<AutosaveEntry> entries) async {
  final names = entries.map((e) => '«${e.name}»').join(', ');
  final times = entries.map((e) => e.saved).whereType<DateTime>().toList()..sort();
  final one = entries.length == 1;
  return await _dialog<bool>(
        context,
        dismissible: false,
        title: one ? 'Восстановить работу?' : 'Восстановить работы (${entries.length})?',
        content: _body(
          context,
          'Программа закрылась, не сохранив правки в $names.'
          '${times.isEmpty ? '' : ' Резервная копия: ${_hhmm(times.last)}.'}',
        ),
        actions: (c) => [
          TextBtn(one ? 'Удалить копию' : 'Удалить копии', null, () => Navigator.pop(c, false), outlined: true),
          PrimaryBtn('Восстановить', () => Navigator.pop(c, true)),
        ],
      ) ==
      true;
}

enum UpdateChoice { later, page, install }

Future<UpdateChoice> askUpdate(BuildContext context, Release r) async {
  final t = Tok.of(context);
  return await _dialog<UpdateChoice>(
        context,
        title: 'Доступна версия ${r.version}',
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Text(
              'Установлена $appVersion.${r.notes.isEmpty ? '' : '\n\n${r.notes}'}',
              style: TextStyle(fontSize: 13, height: 1.45, color: t.muted),
            ),
          ),
        ),
        actions: (c) => [
          TextBtn('Позже', null, () => Navigator.pop(c, UpdateChoice.later)),
          TextBtn('Страница выпуска', null, () => Navigator.pop(c, UpdateChoice.page), outlined: true),
          if (r.installer != null) PrimaryBtn('Обновить', () => Navigator.pop(c, UpdateChoice.install)),
        ],
      ) ??
      UpdateChoice.later;
}

/// Экран вместо интерфейса, если движок распознавания не запустился.
class FatalScreen extends StatelessWidget {
  final String text;
  const FatalScreen({super.key, required this.text});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Scaffold(
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Не удалось запустить движок распознавания',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: t.text),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: SingleChildScrollView(
                child: SelectableText(text, style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
