import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Связь с Python-бэкендом (server.py): JSON по строке через stdin/stdout.
///
/// Поиск бэкенда:
///  1. переменная окружения STATION_BACKEND (путь к server.exe или server.py);
///  2. `backend/server.exe` рядом с приложением (сборка для раздачи);
///  3. `server.py` в родительских папках (разработка) – запускается через python.
class Backend {
  Process? _proc;
  int _next = 1;
  final _pending = <int, Completer<Map<String, dynamic>>>{};
  final _log = StringBuffer();
  String? startError;

  String get stderrTail {
    final s = _log.toString();
    return s.length > 2000 ? s.substring(s.length - 2000) : s;
  }

  Future<void> start() async {
    final (exe, args, cwd) = _locate();
    try {
      _proc = await Process.start(
        exe,
        args,
        workingDirectory: cwd,
        environment: {'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
      );
    } on ProcessException catch (e) {
      startError = 'Не удалось запустить бэкенд ($exe): ${e.message}';
      rethrow;
    }
    _proc!.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen(_onLine);
    _proc!.stderr.transform(utf8.decoder).listen(_log.write);
    unawaited(
      _proc!.exitCode.then((code) {
        final err = StateError('Бэкенд завершился (код $code)\n$stderrTail');
        for (final c in _pending.values) {
          if (!c.isCompleted) c.completeError(err);
        }
        _pending.clear();
        _proc = null;
      }),
    );
  }

  (String, List<String>, String?) _locate() {
    final env = Platform.environment['STATION_BACKEND'];
    if (env != null && env.isNotEmpty) {
      return env.toLowerCase().endsWith('.py')
          ? ('python', [env], File(env).parent.path)
          : (env, <String>[], File(env).parent.path);
    }
    final appDir = File(Platform.resolvedExecutable).parent;
    final bundled = File(
      '${appDir.path}${Platform.pathSeparator}backend'
      '${Platform.pathSeparator}server${Platform.isWindows ? '.exe' : ''}',
    );
    if (bundled.existsSync()) return (bundled.path, <String>[], bundled.parent.path);
    // разработка: ищем server.py выше по дереву (от приложения и от текущей папки)
    for (final start in [appDir, Directory.current]) {
      Directory? d = start;
      for (var i = 0; i < 8 && d != null; i++) {
        final py = File('${d.path}${Platform.pathSeparator}server.py');
        if (py.existsSync()) return ('python', [py.path], d.path);
        final parent = d.parent;
        d = parent.path == d.path ? null : parent;
      }
    }
    return ('python', ['server.py'], null);
  }

  void _onLine(String line) {
    if (line.trim().isEmpty) return;
    final Map<String, dynamic> msg;
    try {
      msg = jsonDecode(line) as Map<String, dynamic>;
    } catch (_) {
      _log.writeln('bad line: $line');
      return;
    }
    final c = _pending.remove(msg['id']);
    if (c == null) return;
    if (msg['ok'] == true) {
      c.complete((msg['result'] as Map?)?.cast<String, dynamic>() ?? {});
    } else {
      c.completeError(BackendError(msg['error']?.toString() ?? 'ошибка'));
    }
  }

  Future<Map<String, dynamic>> call(String cmd, [Map<String, dynamic> args = const {}]) {
    final p = _proc;
    if (p == null) return Future.error(StateError(startError ?? 'Бэкенд не запущен'));
    final id = _next++;
    final c = Completer<Map<String, dynamic>>();
    _pending[id] = c;
    p.stdin.writeln(jsonEncode({'id': id, 'cmd': cmd, ...args}));
    return c.future;
  }

  void dispose() {
    _proc?.stdin.close();
    _proc?.kill();
  }
}

class BackendError implements Exception {
  final String message;
  BackendError(this.message);
  @override
  String toString() => message;
}
