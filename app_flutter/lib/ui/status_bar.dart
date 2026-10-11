import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../scene.dart';
import '../scheme_view.dart';
import '../theme.dart';
import 'properties.dart' show endKinds;

/// Что под курсором: объект и ордината (мм от левого края схемы).
typedef HoverInfo = ({Hit? hit, double? ordinate});

/// Строка состояния: подсказка по объекту под курсором, ордината, замечания, итоги.
/// Слушает только [hover] – движение мыши не перестраивает весь экран.
class StatusBar extends StatelessWidget {
  final ValueListenable<HoverInfo> hover;
  final Scene? scene;
  final Tool tool;
  final bool ready;
  const StatusBar({super.key, required this.hover, required this.scene, required this.tool, required this.ready});

  String _hint(Hit? h) {
    final s = scene;
    if (h is JointHit) return 'Стык «${h.j.rule}» – ${h.j.text}${h.j.negab ? ' · негабаритный' : ''}';
    if (h is SignalHit) return 'Светофор ${h.s.name} – ${h.s.why} · ПКМ – меню';
    if (h is SectionHit) {
      final sw = h.sec.switches;
      return 'Участок ${h.sec.name} – ${h.sec.kind}${sw.isEmpty ? '' : ', стрелки ${sw.join(', ')}'}';
    }
    if (h is NodeHit) {
      return h.n.isSwitch
          ? 'Стрелка ${h.n.label}'
          : 'Конец пути${h.n.label.isEmpty ? '' : ' ${h.n.label}'} – ${endKinds[h.n.mark] ?? 'тип не задан'}'
                '${tool == Tool.track ? ' · клик – сменить тип' : ''}';
    }
    if (tool == Tool.track) {
      return h is EdgeHit
          ? 'Отрезок пути – клик выбрать, Del удалить · тяните – новый отрезок'
          : 'Пути: тяните от узла или пути – новый отрезок · клик по отрезку – выбрать · Esc – выход';
    }
    if (tool == Tool.joint) return 'Стык: клик по пути ставит стык · Esc – выход';
    if (s == null) return ready ? 'Готово' : 'Запуск движка…';
    return 'Колесо – зум · перетаскивание – сдвиг · ПКМ по стыку или светофору – меню · 0 – вписать';
  }

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final s = scene;
    final st = TextStyle(fontSize: 11.5, color: t.muted);
    return Container(
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(
        color: t.panel,
        border: Border(top: BorderSide(color: t.line)),
      ),
      child: Row(
        children: [
          Expanded(
            child: ValueListenableBuilder<HoverInfo>(
              valueListenable: hover,
              builder: (_, h, _) => Row(
                children: [
                  Expanded(child: Text(_hint(h.hit), style: st, overflow: TextOverflow.ellipsis)),
                  if (h.ordinate != null)
                    Text('x ${h.ordinate!.toStringAsFixed(1).padLeft(6)} мм', style: st.copyWith(fontFamily: mono)),
                ],
              ),
            ),
          ),
          const SizedBox(width: 16),
          if (s != null && s.issues.isNotEmpty) ...[
            Tooltip(
              message: s.issues.join('\n'),
              child: Row(
                children: [
                  Icon(Icons.warning_amber_rounded, size: 14, color: t.danger),
                  const SizedBox(width: 4),
                  Text('замечаний: ${s.issues.length}', style: st.copyWith(color: t.danger)),
                ],
              ),
            ),
            const SizedBox(width: 16),
          ],
          if (s != null)
            Text(
              '${s.joints.length} стыков · ${s.signals.length} светофоров · '
              '${s.sections.length} участков · ${s.routes.length} маршрутов',
              style: st,
            ),
        ],
      ),
    );
  }
}
