import 'dart:convert';
import 'dart:io';

import 'recent.dart';

/// Запись о резервной копии несохранённой схемы.
class AutosaveEntry {
  final String file; // копия .stj
  final String? project; // файл работы, если схема уже сохранялась
  final String? origin; // исходная картинка, если не сохранялась
  final String name;
  final DateTime? saved;
  AutosaveEntry({required this.file, this.project, this.origin, required this.name, this.saved});

  Map<String, dynamic> toJson() => {
    'file': file,
    'project': project,
    'origin': origin,
    'name': name,
    'saved': saved?.toIso8601String(),
  };

  static AutosaveEntry? fromJson(Object? o) {
    if (o is! Map || o['file'] is! String) return null;
    return AutosaveEntry(
      file: o['file'] as String,
      project: o['project'] as String?,
      origin: o['origin'] as String?,
      name: '${o['name'] ?? ''}',
      saved: DateTime.tryParse('${o['saved']}'),
    );
  }
}

/// Резервные копии несохранённых схем: %APPDATA%\StationJoints\autosave\ –
/// файлы doc_N.stj и список autosave.json. Ошибки записи молча пропускаются:
/// резервная копия – страховка, а не главное.
class AutosaveStore {
  final String dir;
  AutosaveStore([String? dir]) : dir = dir ?? '${Recent.dir}${Platform.pathSeparator}autosave';

  File get _meta => File('$dir${Platform.pathSeparator}autosave.json');
  bool get exists => _meta.existsSync();

  String fileFor(int docId) => '$dir${Platform.pathSeparator}doc_$docId.stj';

  List<AutosaveEntry> read() {
    try {
      final j = jsonDecode(_meta.readAsStringSync());
      final list = j is List ? j : [j]; // старый формат – одна запись
      return [for (final e in list) ?AutosaveEntry.fromJson(e)];
    } catch (_) {
      return [];
    }
  }

  /// Записать список; копии, которых в нём нет, удаляются.
  void write(List<AutosaveEntry> entries) {
    try {
      Directory(dir).createSync(recursive: true);
      if (entries.isEmpty) {
        if (_meta.existsSync()) _meta.deleteSync();
      } else {
        _meta.writeAsStringSync(jsonEncode([for (final e in entries) e.toJson()]));
      }
      final keep = {for (final e in entries) e.file.toLowerCase()};
      for (final f in Directory(dir).listSync().whereType<File>()) {
        if (f.path.toLowerCase().endsWith('.stj') && !keep.contains(f.path.toLowerCase())) f.deleteSync();
      }
    } catch (_) {}
  }

  /// Копия этого документа больше не нужна (сохранён, закрыт, правки отброшены).
  void drop(int docId) {
    final file = fileFor(docId).toLowerCase();
    write([
      for (final e in read())
        if (e.file.toLowerCase() != file) e,
    ]);
  }

  void clear() => write([]);

  /// Копии, файлы которых ещё на месте.
  List<AutosaveEntry> pending() => [
    for (final e in read())
      if (File(e.file).existsSync()) e,
  ];
}
