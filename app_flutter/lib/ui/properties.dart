import 'package:flutter/material.dart';

import '../scene.dart';
import '../scheme_view.dart';
import '../theme.dart';
import 'controls.dart';

/// Типы конца пути (правка распознанной схемы).
const endKinds = {'tupik': 'тупик', 'peregon': 'перегон', 'pp': 'подъездной путь'};

String capitalize(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

/// Правки, доступные из панели свойств и контекстных меню. Реализует экран, который
/// знает про бэкенд, историю и выделение; панель только показывает и вызывает.
abstract interface class SchemeActions {
  void toggleNegab(JointObj j);
  void removeJoint(JointObj j);
  void addSignal(JointObj j, int toward);
  void setEnd(NodeObj n, String mark);
  void deleteChain(EdgeHit h);
  void renameSignal(SignalObj s, String name);
  void setSignalKind(SignalObj s, String kind);
  void deleteSignal(SignalObj s);
  void resetSignal(SignalObj s);
}

/// Свойства выбранного объекта (правая панель, вкладка «Свойства»).
class PropertiesPanel extends StatelessWidget {
  final Scene? scene;
  final Hit? selected;
  final SchemeActions actions;
  const PropertiesPanel({super.key, required this.scene, required this.selected, required this.actions});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final s = scene;
    final h = selected;
    if (s == null) return _hint(t, 'Нет схемы');
    return switch (h) {
      JointHit(:final j) => _joint(t, s, j),
      NodeHit(:final n) when n.isSwitch => _switch(t, s, n),
      NodeHit(:final n) => _end(t, n),
      EdgeHit() => _edge(t, h),
      SectionHit(:final sec) => _section(t, sec),
      SignalHit(s: final g) => _signal(t, s, g),
      RouteHit(:final r) => _route(t, r),
      _ => _hint(
        t,
        'Ничего не выбрано.\n\nКлик по стыку, светофору, стрелке или концу пути – свойства.\n'
        'Стык можно потянуть мышью вдоль пути.\n'
        'J – «Стык»: клик по пути ставит стык.\n'
        'T – «Пути»: исправить распознанную схему.\n'
        'F1 – «Объясни»: почему объект стоит именно так.\n'
        'Маршруты приёма, отправления и маневровые – на вкладке «Маршруты».',
      ),
    };
  }

  Widget _hint(Tok t, String text) => Padding(
    padding: const EdgeInsets.all(12),
    child: Text(text, style: TextStyle(fontSize: 12, height: 1.5, color: t.muted)),
  );

  Widget _title(Tok t, String text) =>
      Text(text, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text));

  Widget _note(Tok t, String text) => Text(text, style: TextStyle(fontSize: 11.5, height: 1.4, color: t.muted));

  Widget _list(List<Widget> children) => ListView(padding: const EdgeInsets.all(12), children: children);

  Widget _joint(Tok t, Scene s, JointObj j) {
    final e = s.edges.where((e) => e.id == j.edge).firstOrNull;
    String arrow(Offset to) {
      final d = to - j.pos;
      if (d.dx.abs() >= d.dy.abs()) return d.dx < 0 ? '←' : '→';
      return d.dy < 0 ? '↑' : '↓';
    }

    return _list([
      _title(t, 'Изолирующий стык'),
      const SizedBox(height: 8),
      KeyValue('Правило', '${j.rule}) ${j.text}'),
      KeyValue('Габарит', j.negab ? 'негабаритный' : 'габаритный'),
      KeyValue('Ордината', '${(j.pos.dx - s.originX).toStringAsFixed(0)} мм', monoValue: true),
      const SizedBox(height: 12),
      Row(
        children: [
          TextBtn(j.negab ? 'Габаритный' : 'Негабаритный', 'N', () => actions.toggleNegab(j), outlined: true),
          const SizedBox(width: 6),
          TextBtn('Удалить', 'Del', () => actions.removeJoint(j), outlined: true, danger: true),
        ],
      ),
      if (e != null) ...[
        const SizedBox(height: 14),
        const Caption('Добавить светофор'),
        const SizedBox(height: 6),
        Row(
          children: [
            TextBtn('${arrow(e.a)} движение', null, () => actions.addSignal(j, e.na), outlined: true),
            const SizedBox(width: 6),
            TextBtn('движение ${arrow(e.b)}', null, () => actions.addSignal(j, e.nb), outlined: true),
          ],
        ),
      ],
      const SizedBox(height: 12),
      _note(t, 'Потяните стык мышью – он сдвинется вдоль пути с шагом 5 мм.'),
    ]);
  }

  Widget _switch(Tok t, Scene s, NodeObj n) => _list([
    _title(t, 'Стрелка ${n.label}'),
    const SizedBox(height: 8),
    KeyValue('Ордината', '${(n.pos.dx - s.originX).toStringAsFixed(0)} мм', monoValue: true),
    const SizedBox(height: 10),
    _note(t, 'Номер – по правилам п. 2.3. Нажмите F1, чтобы увидеть объяснение.'),
  ]);

  Widget _end(Tok t, NodeObj n) => _list([
    _title(t, 'Конец пути${n.label.isEmpty ? '' : ' ${n.label}'}'),
    const SizedBox(height: 10),
    Row(
      children: [
        for (final e in endKinds.entries)
          Expanded(
            child: SegButton(
              e.key == 'pp' ? 'п/п' : capitalize(e.value),
              n.mark == e.key,
              n.mark == e.key ? null : () => actions.setEnd(n, e.key),
              monoFont: false,
            ),
          ),
      ],
    ),
    const SizedBox(height: 8),
    _note(t, n.manual ? 'Тип задан вручную.' : 'Тип определён автоматически – если ошибся, выберите нужный.'),
  ]);

  Widget _edge(Tok t, EdgeHit h) => _list([
    _title(t, 'Отрезок пути'),
    const SizedBox(height: 6),
    Text('От стрелки до стрелки или до конца пути, через изломы.', style: TextStyle(fontSize: 12, height: 1.4, color: t.muted)),
    const SizedBox(height: 12),
    Row(children: [TextBtn('Удалить отрезок', 'Del', () => actions.deleteChain(h), outlined: true, danger: true)]),
    const SizedBox(height: 12),
    _note(t, 'Лишний отрезок, распознанный по ошибке, – удалите. Чтобы добавить путь, протяните мышью от узла или пути.'),
  ]);

  Widget _section(Tok t, SectionObj c) => _list([
    _title(t, 'Участок ${c.name}'),
    const SizedBox(height: 8),
    KeyValue('Тип', c.kind),
    KeyValue('Расположение', c.throat),
    KeyValue('Стрелки', c.switches.isEmpty ? '–' : c.switches.join(', ')),
    KeyValue('Стыков', '${c.joints}', monoValue: true),
    KeyValue('Длина', '${c.length} мм на схеме', monoValue: true),
    if (c.switches.length > 3) ...[
      const SizedBox(height: 8),
      Text('Больше трёх стрелок в участке (п. 2.4 и)', style: TextStyle(fontSize: 12, color: t.danger)),
    ],
  ]);

  Widget _signal(Tok t, Scene s, SignalObj g) => _list([
    _title(t, 'Светофор ${g.name}'),
    const SizedBox(height: 8),
    if (g.manual) Text('изменён вручную', style: TextStyle(fontSize: 11.5, color: t.accent)),
    const SizedBox(height: 10),
    SignalNameField(
      key: ValueKey('sig-${g.joint}-${g.toward}-${g.name}'),
      name: g.name,
      onSubmit: (v) {
        if (v.trim().isNotEmpty && v.trim() != g.name) actions.renameSignal(g, v.trim());
      },
    ),
    const SizedBox(height: 8),
    KindPicker(code: g.code, kinds: s.signalKinds, onPick: (c) => actions.setSignalKind(g, c)),
    const SizedBox(height: 10),
    KeyValue('Ордината', '${g.ordinate} мм', monoValue: true),
    KeyValue('Основание', g.why),
    const SizedBox(height: 12),
    Row(
      children: [
        TextBtn('Удалить', 'Del', () => actions.deleteSignal(g), outlined: true, danger: true),
        if (g.manual) ...[
          const SizedBox(width: 6),
          TextBtn('Как по правилам', null, () => actions.resetSignal(g), outlined: true),
        ],
      ],
    ),
  ]);

  Widget _route(Tok t, RouteObj r) => _list([
    _title(t, 'Маршрут ${r.no}: ${r.kind} ${r.name}'),
    const SizedBox(height: 8),
    KeyValue('Светофор', r.signal, monoValue: true),
    KeyValue('Горловина', r.throat),
    if (r.note.isNotEmpty) KeyValue('Путь перегона', r.note),
    KeyValue('Вид', r.variant ? 'вариантный' : 'основной'),
    KeyValue('Стрелки', r.switches.isEmpty ? '–' : r.switches.join('  '), monoValue: true),
    if (r.variant) KeyValue('Определяют', r.key.join('  '), monoValue: true),
    KeyValue('Участки', r.sections.join(', ')),
    const SizedBox(height: 12),
    _note(
      t,
      '«+» – стрелка по прямому ходу, «−» – по ответвлению; стрелки съезда спаренные '
      '(пишутся парой). Охранные стрелки программа не определяет – дополните по табл. 2.1 '
      'пособия. Основной маршрут – с наименьшим числом отклонений (п. 3.1).',
    ),
  ]);
}

/// Имя светофора: Enter – применить.
class SignalNameField extends StatefulWidget {
  final String name;
  final void Function(String) onSubmit;
  const SignalNameField({super.key, required this.name, required this.onSubmit});

  @override
  State<SignalNameField> createState() => _SignalNameFieldState();
}

class _SignalNameFieldState extends State<SignalNameField> {
  late final _ctl = TextEditingController(text: widget.name);

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    OutlineInputBorder border(Color c) => OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: c));
    return Row(
      children: [
        SizedBox(
          width: 92,
          child: Text('Имя', style: TextStyle(fontSize: 12, color: t.muted)),
        ),
        Expanded(
          child: SizedBox(
            height: 28,
            child: TextField(
              controller: _ctl,
              onSubmitted: (v) {
                FocusScope.of(context).unfocus(); // горячие клавиши снова работают
                widget.onSubmit(v);
              },
              style: TextStyle(fontSize: 12.5, fontFamily: mono, color: t.text),
              decoration: InputDecoration(
                isDense: true,
                hintText: 'Enter – применить',
                hintStyle: TextStyle(fontSize: 11.5, color: t.muted),
                contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
                enabledBorder: border(t.line),
                focusedBorder: border(t.accent),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// Тип светофора; список типов приходит от бэкенда вместе со сценой.
class KindPicker extends StatelessWidget {
  final String code;
  final Map<String, String> kinds;
  final void Function(String) onPick;
  const KindPicker({super.key, required this.code, required this.kinds, required this.onPick});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Row(
      children: [
        SizedBox(
          width: 92,
          child: Text('Тип', style: TextStyle(fontSize: 12, color: t.muted)),
        ),
        Expanded(
          child: PopupMenuButton<String>(
            tooltip: 'Тип светофора',
            position: PopupMenuPosition.under,
            shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
            color: t.panel,
            onSelected: (c) {
              if (c != code) onPick(c);
            },
            itemBuilder: (_) => [
              for (final e in kinds.entries)
                PopupMenuItem(
                  value: e.key,
                  height: 30,
                  child: Row(
                    children: [
                      SizedBox(width: 20, child: e.key == code ? Icon(Icons.check, size: 15, color: t.accent) : null),
                      Text(e.value, style: TextStyle(fontSize: 12.5, color: t.text)),
                    ],
                  ),
                ),
            ],
            child: Container(
              height: 28,
              padding: const EdgeInsets.only(left: 8),
              decoration: BoxDecoration(border: Border.all(color: t.line)),
              child: Row(
                children: [
                  Expanded(
                    child: Text(kinds[code] ?? code, style: TextStyle(fontSize: 12.5, color: t.text)),
                  ),
                  Icon(Icons.arrow_drop_down, size: 18, color: t.muted),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// «Объясни»: почему объект стоит именно так (данные – от бэкенда, explain.py).
class ExplainCard extends StatelessWidget {
  final Map<String, dynamic>? data;
  final bool hasSelection;
  final VoidCallback onClose;
  const ExplainCard({super.key, required this.data, required this.hasSelection, required this.onClose});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final d = data;
    final items = [for (final i in (d?['items'] as List? ?? const [])) (i as Map).cast<String, dynamic>()];
    final ref = d?['ref'] as String? ?? '';
    return Container(
      constraints: const BoxConstraints(maxHeight: 420),
      decoration: BoxDecoration(
        color: t.panel,
        border: Border(
          bottom: BorderSide(color: t.line),
          top: BorderSide(color: t.accent, width: 2),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: 30,
            padding: const EdgeInsets.only(left: 12, right: 2),
            color: t.accentSoft,
            child: Row(
              children: [
                Icon(Icons.school_outlined, size: 15, color: t.accent),
                const SizedBox(width: 6),
                Expanded(child: Caption('Объясни', color: t.accent)),
                IconBtn(Icons.close, 'Выключить (F1)', onClose, size: 26),
              ],
            ),
          ),
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: d == null
                  ? Text(
                      hasSelection
                          ? 'Секунду…'
                          : 'Кликните по стыку, светофору, стрелке, концу пути или участку – объясню, '
                                'почему он стоит именно так.',
                      style: TextStyle(fontSize: 12.5, height: 1.45, color: t.muted),
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          d['title'] as String? ?? '',
                          style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: t.text),
                        ),
                        for (final it in items) ...[
                          const SizedBox(height: 9),
                          Text(
                            '${it['h']}'.toUpperCase(),
                            style: TextStyle(fontSize: 10, letterSpacing: 0.5, fontWeight: FontWeight.w600, color: t.muted),
                          ),
                          const SizedBox(height: 2),
                          Text('${it['t']}', style: TextStyle(fontSize: 12.5, height: 1.45, color: t.text)),
                        ],
                        if (ref.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          Container(height: 1, color: t.line),
                          const SizedBox(height: 8),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(Icons.menu_book_outlined, size: 14, color: t.muted),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text('Методичка: $ref', style: TextStyle(fontSize: 11.5, color: t.muted)),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
            ),
          ),
        ],
      ),
    );
  }
}
