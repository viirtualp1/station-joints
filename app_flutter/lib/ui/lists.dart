import 'dart:io';

import 'package:flutter/material.dart';

import '../recent.dart';
import '../scene.dart';
import '../theme.dart';
import 'controls.dart';

/// Строка списка: выделенная – акцентная полоса слева и подложка.
class _ListRow extends StatelessWidget {
  final bool selected;
  final VoidCallback onTap;
  final double? height;
  final Widget child;
  const _ListRow({required this.selected, required this.onTap, required this.child, this.height});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      hoverColor: t.panel2,
      child: Container(
        height: height,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: selected ? t.accentSoft : null,
          border: Border(
            left: BorderSide(color: selected ? t.accent : Colors.transparent, width: 2),
            bottom: BorderSide(color: t.line.withValues(alpha: .6)),
          ),
        ),
        child: child,
      ),
    );
  }
}

/// Заголовок группы в списке.
class GroupHeader extends StatelessWidget {
  final String text;
  const GroupHeader(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Container(
    height: 28,
    padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
    color: Tok.of(context).panel2,
    child: Caption(text),
  );
}

class SignalRow extends StatelessWidget {
  final SignalObj s;
  final bool selected;
  final VoidCallback onTap;
  const SignalRow({super.key, required this.s, required this.selected, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return _ListRow(
      selected: selected,
      onTap: onTap,
      child: Row(
        children: [
          SizedBox(
            width: 44,
            child: Text(
              s.name,
              style: TextStyle(fontFamily: mono, fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
            ),
          ),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(s.kind, style: TextStyle(fontSize: 12, color: t.text), overflow: TextOverflow.ellipsis),
                Text(s.why, style: TextStyle(fontSize: 11, color: t.muted), overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          Text('${s.ordinate}', style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted)),
        ],
      ),
    );
  }
}

class SectionRow extends StatelessWidget {
  final SectionObj s;
  final bool selected;
  final VoidCallback onTap;
  const SectionRow({super.key, required this.s, required this.selected, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final many = s.switches.length > 3;
    final sub = [if (s.switches.isNotEmpty) 'стр. ${s.switches.join(', ')}' else s.kind, '${s.joints} ст.'].join(' · ');
    return _ListRow(
      selected: selected,
      onTap: onTap,
      height: 40,
      child: Row(
        children: [
          SizedBox(
            width: 84,
            child: Text(
              s.name,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontFamily: mono, fontSize: 12.5, fontWeight: FontWeight.w600, color: t.text),
            ),
          ),
          Expanded(
            child: Text(
              sub,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 11.5, color: many ? t.danger : t.muted),
            ),
          ),
          Text('${s.length}', style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted)),
        ],
      ),
    );
  }
}

/// Маршрут: номер, «светофор → куда», стрелки (у вариантного – только определяющие).
class RouteRow extends StatelessWidget {
  final RouteObj r;
  final bool selected;
  final VoidCallback onTap;
  const RouteRow({super.key, required this.r, required this.selected, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final sw = (r.variant ? r.key : r.switches).join(' ');
    return _ListRow(
      selected: selected,
      onTap: onTap,
      height: 44,
      child: Row(
        children: [
          SizedBox(
            width: 30,
            child: Text('${r.no}', style: TextStyle(fontFamily: mono, fontSize: 11.5, color: t.muted)),
          ),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: r.signal,
                        style: TextStyle(fontFamily: mono, fontWeight: FontWeight.w600, color: t.text),
                      ),
                      TextSpan(text: '  ${r.name}'),
                      if (r.note.isNotEmpty) TextSpan(text: ' · ${r.note}', style: TextStyle(color: t.muted)),
                    ],
                  ),
                  style: TextStyle(fontSize: 12, color: t.text),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  sw.isEmpty ? 'без стрелок' : sw,
                  style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          if (r.variant)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(border: Border.all(color: t.line)),
              child: Text('вар.', style: TextStyle(fontSize: 10.5, color: t.muted)),
            ),
        ],
      ),
    );
  }
}

String folderOf(String path) {
  final i = path.lastIndexOf(Platform.pathSeparator);
  return i > 0 ? path.substring(0, i) : path;
}

String ago(DateTime d) {
  final m = DateTime.now().difference(d).inMinutes;
  if (m < 1) return 'только что';
  if (m < 60) return '$m мин назад';
  if (m < 60 * 24) return '${m ~/ 60} ч назад';
  if (m < 60 * 24 * 7) return '${m ~/ (60 * 24)} дн назад';
  return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
}

class RecentCard extends StatelessWidget {
  final RecentItem it;
  final VoidCallback? onTap;
  const RecentCard({super.key, required this.it, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final thumb = File(it.thumb);
    return Tooltip(
      message: it.path,
      waitDuration: const Duration(milliseconds: 600),
      child: InkWell(
        onTap: onTap,
        hoverColor: t.panel2,
        child: Container(
          width: 196,
          decoration: BoxDecoration(
            color: t.panel,
            border: Border.all(color: t.line),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                height: 86,
                color: Colors.white,
                padding: const EdgeInsets.all(4),
                child: thumb.existsSync()
                    ? Image.file(thumb, fit: BoxFit.contain)
                    : Icon(Icons.image_outlined, color: t.muted),
              ),
              Container(height: 1, color: t.line),
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 6, 8, 7),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(it.project ? Icons.description_outlined : Icons.image_outlined, size: 13, color: t.muted),
                        const SizedBox(width: 5),
                        Expanded(
                          child: Text(
                            it.name,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(fontSize: 12, color: t.text),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(ago(it.opened), style: TextStyle(fontSize: 11, color: t.muted)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
