import 'dart:convert';
import 'dart:io';

/// Недавние файлы (работы .stj и картинки) – %APPDATA%\StationJoints\recent.json,
/// миниатюры схем – там же, в thumbs\.
class RecentItem {
  final String path, name;
  final DateTime opened;
  final bool project;
  RecentItem(this.path, this.name, this.opened, this.project);

  Map<String, dynamic> toJson() =>
      {'path': path, 'name': name, 'opened': opened.toIso8601String(), 'project': project};

  static RecentItem? fromJson(Object? o) {
    if (o is! Map) return null;
    final p = o['path'], n = o['name'], t = DateTime.tryParse('${o['opened']}');
    if (p is! String || n is! String || t == null) return null;
    return RecentItem(p, n, t, o['project'] == true);
  }

  bool get exists => File(path).existsSync();
  String get thumb => Recent.thumbFor(path);
}

class Recent {
  static const max = 12;

  static String? dirOverride; // для тестов

  static String get dir {
    if (dirOverride != null) return dirOverride!;
    final base = Platform.environment['APPDATA'] ?? Directory.systemTemp.path;
    return '$base${Platform.pathSeparator}StationJoints';
  }

  static File get _file => File('$dir${Platform.pathSeparator}recent.json');

  /// Путь миниатюры: по хэшу пути файла (FNV-1a).
  static String thumbFor(String path) {
    var h = 0x811c9dc5;
    for (final c in path.toLowerCase().codeUnits) {
      h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF;
    }
    return '$dir${Platform.pathSeparator}thumbs${Platform.pathSeparator}'
        '${h.toRadixString(16).padLeft(8, '0')}.png';
  }

  static List<RecentItem> load() {
    try {
      final l = jsonDecode(_file.readAsStringSync()) as List;
      return [for (final o in l) ?RecentItem.fromJson(o)];
    } catch (_) {
      return [];
    }
  }

  static void _save(List<RecentItem> items) {
    try {
      Directory(dir).createSync(recursive: true);
      _file.writeAsStringSync(jsonEncode([for (final i in items) i.toJson()]));
    } catch (_) {
      // список недавних – удобство, ошибки записи не мешают работе
    }
  }

  /// Поднять файл наверх списка. Если та же картинка сохранена как работа –
  /// оставляем только работу.
  static List<RecentItem> touch(String path, String name, {required bool project, String? replaces}) {
    final key = path.toLowerCase(), old = replaces?.toLowerCase();
    final items = load()
        .where((i) => i.path.toLowerCase() != key && i.path.toLowerCase() != old)
        .toList()
      ..insert(0, RecentItem(path, name, DateTime.now(), project));
    if (items.length > max) items.removeRange(max, items.length);
    _save(items);
    return items;
  }

  static List<RecentItem> remove(String path) {
    final items = load().where((i) => i.path.toLowerCase() != path.toLowerCase()).toList();
    _save(items);
    return items;
  }

  static void clear() => _save([]);
}
