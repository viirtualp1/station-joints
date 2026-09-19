import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:flutter/gestures.dart' show kMiddleMouseButton, kSecondaryMouseButton;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'backend.dart';
import 'file_dialog.dart';
import 'recent.dart';
import 'scene.dart';
import 'scheme_view.dart';
import 'theme.dart';
import 'update.dart';

const _layerNames = {
  'grid': 'Миллиметровка',
  'joints': 'Изолирующие стыки',
  'signals': 'Светофоры',
  'numbers': 'Номера и ось станции',
  'letters': 'Буквы правил у стыков',
  'sections': 'Участки цветом',
  'section_names': 'Имена участков',
  'annots': 'Надписи с картинки',
};

class Home extends StatefulWidget {
  final VoidCallback onToggleTheme;
  final String? initialPath;
  const Home({super.key, required this.onToggleTheme, this.initialPath});

  @override
  State<Home> createState() => _HomeState();
}

/// Открытая схема (таб): своя сессия в бэкенде, своя камера и выделение.
class _Doc {
  final int id; // номер документа в бэкенде
  Scene? scene;
  String? path; // открытый файл: картинка или .stj
  bool dirty = false; // есть несохранённые изменения
  Hit? selected;
  String? name; // имя, заданное пользователем (для ещё не сохранённой схемы)
  bool layersStale = false; // слои меняли, пока таб был неактивен
  final cam = SchemeController();
  _Doc(this.id);
}

class _HomeState extends State<Home> {
  final _backend = Backend();
  final _focus = FocusNode();

  bool _ready = false;
  String? _fatal;
  bool _busy = false;
  String _busyText = '';

  final _docs = <_Doc>[];
  _Doc? _doc; // активный таб
  final _noCam = SchemeController(); // холст без схемы
  _Doc? _renaming; // таб, имя которого сейчас редактируется
  bool _explain = false; // режим «Объясни»
  String? _explainKey; // что сейчас объяснено (объект + версия сцены)
  Map<String, dynamic>? _explainData;

  Scene? get _scene => _doc?.scene;
  String? get _path => _doc?.path;
  set _path(String? v) => _doc?.path = v;
  bool get _dirty => _doc?.dirty ?? false;
  set _dirty(bool v) => _doc?.dirty = v;
  Hit? get _selected => _doc?.selected;
  set _selected(Hit? v) => _doc?.selected = v;
  SchemeController get _cam => _doc?.cam ?? _noCam;

  Tool _tool = Tool.select;
  Hit? _hover;
  double? _ordinate;
  int _tab = 0; // 0 свойства, 1 светофоры, 2 участки
  List<RecentItem> _recent = Recent.load();
  bool _left = true, _right = true;

  final _layers = <String, bool>{
    'grid': true,
    'joints': true,
    'signals': true,
    'numbers': true,
    'letters': false,
    'sections': false,
    'section_names': false,
    'annots': true,
  };
  bool _twoSheets = false; // режим «Два листа» – по желанию
  String _fmt = 'A3';
  bool _oddRight = true; // нечётная горловина справа (нечёт – справа налево)

  String? _toast;
  Timer? _toastTimer;

  Timer? _autosaveTimer;
  late final AppLifecycleListener _life;
  Release? _update; // найденная новая версия
  String? _pendingOpen; // файл от повторного запуска, пришедший до готовности движка
  static const _instance = MethodChannel('station_joints/instance');

  @override
  void initState() {
    super.initState();
    // закрытие окна: спросить про несохранённые правки
    _life = AppLifecycleListener(onExitRequested: _onExitRequested);
    _autosaveTimer = Timer.periodic(const Duration(seconds: 30), (_) => _autosave());
    // повторный запуск программы (двойной щелчок по .stj) – открыть файл здесь
    _instance.setMethodCallHandler((call) async {
      if (call.method == 'open' && call.arguments is String) await _openExternal(call.arguments as String);
    });
    _start();
  }

  Future<void> _openExternal(String path) async {
    if (path.isEmpty) return;
    if (!_ready || _busy) {
      _pendingOpen = path;
      return;
    }
    if (!File(path).existsSync()) {
      _say('Файл не найден: $path', error: true);
      return;
    }
    await _load(path);
  }

  // ------------------------------------------------------------------ табы
  /// Команда бэкенду для документа (по умолчанию – активного таба).
  Future<Map<String, dynamic>> _call(String cmd, [Map<String, dynamic>? args, _Doc? doc]) =>
      _backend.call(cmd, {...?args, 'doc': (doc ?? _doc)!.id});

  Future<_Doc> _newDoc() async {
    final r = await _backend.call('new_doc');
    final d = _Doc(r['doc'] as int);
    d.cam.addListener(() {
      if (mounted && identical(d, _doc)) setState(() {});
    });
    setState(() => _docs.add(d));
    return d;
  }

  _Doc? _findOpen(String path) {
    final key = path.toLowerCase();
    for (final d in _docs) {
      final src = d.scene?.source;
      final paths = [d.path, src?['project'], src?['path']];
      if (paths.any((p) => p is String && p.toLowerCase() == key)) return d;
    }
    return null;
  }

  Future<void> _activate(_Doc? d) async {
    if (_busy && d != _doc) return; // пока идёт операция – не переключаемся
    setState(() {
      _doc = d;
      _hover = null;
      _ordinate = null;
    });
    if (d == null) return;
    _syncSettings();
    if (d.layersStale && d.scene != null) {
      d.layersStale = false;
      final lay = Map.of(_layers)..remove('grid');
      _apply(await _call('scene', {'layers': lay}, d), keepSelection: true, doc: d);
    }
  }

  void _cycleTab(int step) {
    if (_docs.length < 2 || _doc == null) return;
    final i = _docs.indexOf(_doc!);
    _activate(_docs[(i + step) % _docs.length]);
  }

  /// Убрать таб (без вопросов): бэкенд забывает документ, активным становится сосед.
  Future<void> _dropDoc(_Doc d, {_Doc? fallback}) async {
    final i = _docs.indexOf(d);
    if (i < 0) return;
    _dropAutosave(d);
    setState(() => _docs.removeAt(i));
    try {
      await _backend.call('close_doc', {'doc': d.id});
    } catch (_) {}
    if (identical(_doc, d)) {
      final next = fallback != null && _docs.contains(fallback)
          ? fallback
          : (_docs.isEmpty ? null : _docs[i.clamp(0, _docs.length - 1)]);
      await _activate(next);
    }
  }

  /// Закрыть таб: при несохранённых правках – спросить.
  Future<void> _closeTab(_Doc d) async {
    if (_busy) return;
    if (d.dirty) {
      await _activate(d);
      if (!await _confirmDiscard()) return;
    }
    await _dropDoc(d);
  }

  // ------------------------------------------------------------------ переименование
  Future<void> _startRename(_Doc d) async {
    if (_busy || d.scene == null) return;
    await _activate(d);
    setState(() => _renaming = d);
  }

  void _endRename() {
    setState(() => _renaming = null);
    _focus.requestFocus(); // вернуть горячие клавиши
  }

  /// Новое имя таба. Несохранённая схема – имя для будущего сохранения;
  /// сохранённая работа – файл .stj переименовывается на диске.
  Future<void> _commitRename(_Doc d, String raw) async {
    if (!identical(_renaming, d)) return;
    _endRename();
    var name = raw.trim().replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_');
    if (name.toLowerCase().endsWith('.stj')) name = name.substring(0, name.length - 4).trim();
    if (name.isEmpty || name == _baseOf(d)) return;
    final project = d.scene?.source?['project'] as String?;
    if (project == null) {
      setState(() => d.name = name);
      _say('Имя «$name» – будет предложено при сохранении (Ctrl+S)');
      return;
    }
    final sep = Platform.pathSeparator;
    final dir = project.substring(0, project.lastIndexOf(sep));
    final target = '$dir$sep$name.stj';
    if (target.toLowerCase() != project.toLowerCase() && File(target).existsSync()) {
      _say('Файл «$name.stj» уже есть в этой папке', error: true);
      return;
    }
    try {
      File(project).renameSync(target);
      final r = await _call('set_project', {'path': target}, d);
      setState(() {
        d.scene!.source = (r['source'] as Map).cast<String, dynamic>();
        d.path = target;
        d.name = null;
        _recent = Recent.remove(project);
      });
      await _remember(target, project: true, doc: d);
      _say('Переименовано: $name.stj');
    } catch (e) {
      _say('Не удалось переименовать: $e', error: true);
    }
  }

  Future<void> _tabMenu(_Doc d, Offset global) async {
    final t = Tok.of(context);
    PopupMenuItem<String> item(String v, String text, String key, {bool enabled = true}) => PopupMenuItem(
      value: v,
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
            key,
            style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
          ),
        ],
      ),
    );
    final v = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(global.dx, global.dy, global.dx, global.dy),
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      items: [
        item('rename', 'Переименовать', 'F2', enabled: d.scene != null),
        item('close', 'Закрыть', 'Ctrl+W'),
        item('others', 'Закрыть остальные', '', enabled: _docs.length > 1),
      ],
    );
    switch (v) {
      case 'rename':
        await _startRename(d);
      case 'close':
        await _closeTab(d);
      case 'others':
        for (final o in List.of(_docs)) {
          if (!identical(o, d)) await _closeTab(o);
        }
        await _activate(d);
    }
  }

  /// Спросить про все табы с несохранёнными правками (выход, обновление).
  Future<bool> _confirmAll() async {
    for (final d in List.of(_docs)) {
      if (!d.dirty) continue;
      await _activate(d);
      if (!await _confirmDiscard()) return false;
    }
    return true;
  }

  String _baseOf(_Doc? d) {
    if (d?.name != null) return d!.name!;
    final src = d?.scene?.source;
    final n =
        (src?['project'] as String?)?.split(Platform.pathSeparator).last ??
        src?['name'] as String? ??
        d?.path?.split(Platform.pathSeparator).last ??
        'схема';
    final i = n.lastIndexOf('.');
    return i > 0 ? n.substring(0, i) : n;
  }

  Future<void> _start() async {
    try {
      await _backend.start();
      await _backend.call('ping');
      setState(() => _ready = true);
      final restored = await _offerRestore();
      final p = widget.initialPath;
      if (!restored && p != null && File(p).existsSync()) await _load(p);
      final pending = _pendingOpen;
      _pendingOpen = null;
      if (pending != null) await _openExternal(pending);
    } catch (e) {
      setState(() => _fatal = '$e\n\n${_backend.stderrTail}');
    }
    unawaited(_checkUpdate());
  }

  @override
  void dispose() {
    _life.dispose();
    _instance.setMethodCallHandler(null);
    _autosaveTimer?.cancel();
    _backend.dispose();
    _toastTimer?.cancel();
    super.dispose();
  }

  Future<AppExitResponse> _onExitRequested() async {
    if (!await _confirmAll()) return AppExitResponse.cancel;
    _clearAutosave();
    return AppExitResponse.exit;
  }

  // ------------------------------------------------------------------ автосохранение
  static String get _autoDir => '${Recent.dir}${Platform.pathSeparator}autosave';
  static File get _autoMeta => File('$_autoDir${Platform.pathSeparator}autosave.json');
  static String _autoFileFor(_Doc d) => '$_autoDir${Platform.pathSeparator}doc_${d.id}.stj';
  bool _autosaving = false;

  List<Map<String, dynamic>> _readAutoMeta() {
    try {
      final j = jsonDecode(_autoMeta.readAsStringSync());
      final list = j is List ? j : [j]; // старый формат – одна запись
      return [for (final e in list) (e as Map).cast<String, dynamic>()];
    } catch (_) {
      return [];
    }
  }

  void _writeAutoMeta(List<Map<String, dynamic>> entries) {
    try {
      Directory(_autoDir).createSync(recursive: true);
      if (entries.isEmpty) {
        if (_autoMeta.existsSync()) _autoMeta.deleteSync();
      } else {
        _autoMeta.writeAsStringSync(jsonEncode(entries));
      }
      // копии, которых нет в списке, – больше не нужны
      final keep = {for (final e in entries) '${e['file']}'.toLowerCase()};
      for (final f in Directory(_autoDir).listSync().whereType<File>()) {
        if (f.path.toLowerCase().endsWith('.stj') && !keep.contains(f.path.toLowerCase())) f.deleteSync();
      }
    } catch (_) {}
  }

  /// Раз в 30 с – резервные копии всех табов с несохранёнными правками.
  Future<void> _autosave() async {
    if (_busy || _autosaving) return;
    if (!_docs.any((d) => d.dirty) && !_autoMeta.existsSync()) return;
    _autosaving = true;
    try {
      final entries = <Map<String, dynamic>>[];
      for (final d in List.of(_docs)) {
        if (!d.dirty || d.scene == null) continue;
        final file = _autoFileFor(d);
        await _call('save_project', {'path': file, 'autosave': true}, d);
        final src = d.scene?.source ?? const {};
        entries.add({
          'file': file,
          'project': src['project'],
          'origin': src['project'] == null ? d.path : null,
          'name': _baseOf(d),
          'saved': DateTime.now().toIso8601String(),
        });
      }
      _writeAutoMeta(entries);
    } catch (_) {
      // резервная копия – не критично
    } finally {
      _autosaving = false;
    }
  }

  /// Копия этого таба больше не нужна (сохранён, закрыт, правки отброшены).
  void _dropAutosave(_Doc d) {
    final file = _autoFileFor(d).toLowerCase();
    _writeAutoMeta([
      for (final e in _readAutoMeta())
        if ('${e['file']}'.toLowerCase() != file) e,
    ]);
  }

  void _clearAutosave() => _writeAutoMeta([]);

  /// При запуске: остались резервные копии (программа закрылась, не сохранив правки)?
  Future<bool> _offerRestore() async {
    final entries = [
      for (final e in _readAutoMeta())
        if (e['file'] is String && File(e['file'] as String).existsSync()) e,
    ];
    if (entries.isEmpty) {
      _clearAutosave();
      return false;
    }
    if (!mounted) return false;
    final names = entries.map((e) => '«${e['name']}»').join(', ');
    final times = entries.map((e) => DateTime.tryParse('${e['saved']}')).whereType<DateTime>().toList()..sort();
    final t = Tok.of(context);
    final v = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (c) => AlertDialog(
        shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
        backgroundColor: t.panel,
        title: Text(
          entries.length == 1 ? 'Восстановить работу?' : 'Восстановить работы (${entries.length})?',
          style: TextStyle(fontSize: 15, color: t.text),
        ),
        content: Text(
          'Программа закрылась, не сохранив правки в $names.'
          '${times.isEmpty ? '' : ' Резервная копия: ${_hhmm(times.last)}.'}',
          style: TextStyle(fontSize: 13, color: t.muted),
        ),
        actions: [
          _TextBtn(
            entries.length == 1 ? 'Удалить копию' : 'Удалить копии',
            null,
            () => Navigator.pop(c, false),
            outlined: true,
          ),
          _PrimaryBtn('Восстановить', () => Navigator.pop(c, true)),
        ],
      ),
    );
    if (v != true) {
      _clearAutosave();
      return false;
    }
    var any = false;
    for (final e in entries) {
      final d = await _newDoc();
      await _activate(d);
      final res = await _run(
        'Восстановление…',
        () => _call('restore', {'path': e['file'], 'project_path': e['project'], 'origin': e['origin']}, d),
      );
      if (res == null) {
        await _dropDoc(d);
        continue;
      }
      d.path = (e['project'] ?? e['origin']) as String?;
      _apply(res, doc: d);
      _syncSettings();
      setState(() => d.dirty = true);
      any = true;
    }
    if (any) _say('Работа восстановлена – не забудьте сохранить (Ctrl+S)');
    return any;
  }

  String _hhmm(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')} '
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

  /// Настройки листа и направления – как у открытой схемы.
  void _syncSettings() {
    final src = _scene?.source ?? const {};
    setState(() {
      final sh = src['sheets'] as String?;
      _twoSheets = sh != null;
      if (sh != null) _fmt = sh;
      _oddRight = src['odd_right'] as bool? ?? _oddRight;
    });
  }

  // ------------------------------------------------------------------ обновления
  Future<void> _checkUpdate() async {
    final r = await checkUpdate();
    if (r != null && mounted) setState(() => _update = r);
  }

  Future<void> _showUpdate() async {
    final r = _update;
    if (r == null) return;
    final t = Tok.of(context);
    final v = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
        backgroundColor: t.panel,
        title: Text('Доступна версия ${r.version}', style: TextStyle(fontSize: 15, color: t.text)),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Text(
              'Установлена $appVersion.${r.notes.isEmpty ? '' : '\n\n${r.notes}'}',
              style: TextStyle(fontSize: 13, height: 1.45, color: t.muted),
            ),
          ),
        ),
        actions: [
          _TextBtn('Позже', null, () => Navigator.pop(c)),
          _TextBtn('Страница выпуска', null, () => Navigator.pop(c, 'page'), outlined: true),
          if (r.installer != null) _PrimaryBtn('Обновить', () => Navigator.pop(c, 'install')),
        ],
      ),
    );
    if (v == 'page') openUrl(r.page);
    if (v == 'install') await _install(r);
  }

  /// Скачать установщик, запустить его и закрыть программу (установщик заменит файлы).
  Future<void> _install(Release r) async {
    if (!await _confirmAll()) return;
    final path = await _run(
      'Загрузка обновления…',
      () => downloadInstaller(r, (p) {
        if (mounted) setState(() => _busyText = 'Загрузка обновления… ${(p * 100).round()}%');
      }),
    );
    if (path == null) return;
    await Process.start(path, ['/SILENT', '/NORESTART'], mode: ProcessStartMode.detached);
    _clearAutosave();
    _backend.dispose();
    exit(0);
  }

  // ------------------------------------------------------------------ действия
  Future<T?> _run<T>(String text, Future<T> Function() f) async {
    setState(() {
      _busy = true;
      _busyText = text;
    });
    try {
      return await f();
    } catch (e) {
      _say('Ошибка: $e', error: true);
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _say(String text, {bool error = false}) {
    _toastTimer?.cancel();
    setState(() => _toast = text);
    _toastTimer = Timer(Duration(milliseconds: error ? 5000 : 2200), () {
      if (mounted) setState(() => _toast = null);
    });
  }

  void _apply(Map<String, dynamic>? res, {bool keepSelection = false, _Doc? doc}) {
    final d = doc ?? _doc;
    if (res == null || d == null) return;
    setState(() {
      // сведения об исходнике приходят только при загрузке – потом переносим старые
      final src = (res['source'] as Map?)?.cast<String, dynamic>() ?? d.scene?.source;
      d.scene = Scene.fromJson(res, source: src);
      if (!keepSelection) d.selected = null;
    });
  }

  Future<void> _open() async {
    final f = pickOpen();
    if (f != null) await _load(f);
  }

  Future<void> _openRecent(RecentItem it) async {
    if (!it.exists) {
      setState(() => _recent = Recent.remove(it.path));
      _say('Файл не найден: ${it.name}', error: true);
      return;
    }
    await _load(it.path);
  }

  /// Несохранённые изменения: сохранить / не сохранять / отмена.
  Future<bool> _confirmDiscard() async {
    if (!_dirty || _scene == null) return true;
    final t = Tok.of(context);
    final v = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
        backgroundColor: t.panel,
        title: Text('Сохранить изменения?', style: TextStyle(fontSize: 15, color: t.text)),
        content: Text('В схеме «$_base» есть несохранённые правки.', style: TextStyle(fontSize: 13, color: t.muted)),
        actions: [
          _TextBtn('Отмена', null, () => Navigator.pop(c, 'cancel')),
          _TextBtn('Не сохранять', null, () => Navigator.pop(c, 'discard'), outlined: true),
          _PrimaryBtn('Сохранить', () => Navigator.pop(c, 'save')),
        ],
      ),
    );
    if (v == 'discard') {
      if (_doc != null) _dropAutosave(_doc!);
      return true;
    }
    if (v == 'save') return await _save();
    return false;
  }

  /// Сохранить работу (.stj). Возвращает true, если сохранено.
  Future<bool> _save({bool as = false}) async {
    if (_scene == null) return false;
    final src = _scene!.source ?? const {};
    final old = src['project'] as String?;
    var path = as ? null : old;
    if (path == null) {
      final picked = pickSave('$_base.stj', 'Работа «Стыки»', 'stj');
      if (picked == null) return false;
      path = picked.toLowerCase().endsWith('.stj') ? picked : '$picked.stj';
    }
    final target = path;
    final r = await _run('Сохранение…', () => _call('save_project', {'path': target}));
    if (r == null) return false;
    setState(() {
      _scene!.source = (r['source'] as Map).cast<String, dynamic>();
      _path = target;
      _dirty = false;
    });
    _dropAutosave(_doc!);
    await _remember(target, project: true, replaces: old == null ? src['path'] as String? : null);
    _say('Работа сохранена: ${target.split(Platform.pathSeparator).last}');
    return true;
  }

  /// В список недавних + миниатюра.
  Future<void> _remember(String path, {required bool project, String? replaces, _Doc? doc}) async {
    final thumb = Recent.thumbFor(path);
    try {
      await _call('thumb', {'path': thumb}, doc);
      await FileImage(File(thumb)).evict();
    } catch (_) {}
    if (!mounted) return;
    setState(
      () => _recent = Recent.touch(path, path.split(Platform.pathSeparator).last, project: project, replaces: replaces),
    );
  }

  Future<void> _openSample() async {
    final r = await _backend.call('sample');
    await _load(r['path'] as String);
  }

  /// Открыть файл в новом табе (уже открытый – просто показать).
  Future<void> _load(String path) async {
    if (_busy) return;
    final open = _findOpen(path);
    if (open != null) {
      await _activate(open);
      if (_docs.length > 1) _say('Этот файл уже открыт');
      return;
    }
    final project = path.toLowerCase().endsWith('.stj');
    final prev = _doc;
    final d = await _newDoc();
    d.path = path;
    await _activate(d);
    final res = await _run(
      project ? 'Открываю работу…' : 'Распознаю схему…',
      () => _call('load', {
        'path': path,
        // у работы свои настройки листа и направления – берём из файла
        if (!project) 'sheets': _twoSheets ? _fmt : null,
        if (!project) 'odd_right': _oddRight,
        'layers': _layers,
      }, d),
    );
    if (res == null) {
      await _dropDoc(d, fallback: prev);
      return;
    }
    _apply(res, doc: d);
    _syncSettings();
    setState(() => d.dirty = false);
    await _remember(path, project: project, doc: d);
  }

  Future<void> _relayout() async {
    if (_path == null) return;
    final res = await _run(
      'Перекомпоновка…',
      () => _call('relayout', {'sheets': _twoSheets ? _fmt : null, 'odd_right': _oddRight}),
    );
    _apply(res);
    if (res != null) setState(() => _dirty = true);
    final kept = (res?['kept'] as int?) ?? 0;
    if (kept > 0) _say('Ручные правки стыков перенесены ($kept)');
  }

  Future<void> _setLayer(String k, bool v) async {
    setState(() => _layers[k] = v);
    if (_scene == null) return;
    if (k == 'grid') return; // сетку рисует клиент
    for (final d in _docs) {
      if (!identical(d, _doc)) d.layersStale = true; // обновятся при переключении
    }
    _apply(
      await _call('scene', {
        'layers': {k: v},
      }),
      keepSelection: true,
    );
  }

  Future<void> _undo() async {
    if (_scene?.undo == null || _busy) return;
    final res = await _call('undo');
    _apply(res);
    _syncSettings();
    setState(() => _dirty = true);
    _say('Отменено: ${res['done']}');
  }

  Future<void> _redo() async {
    if (_scene?.redo == null || _busy) return;
    final res = await _call('redo');
    _apply(res);
    _syncSettings();
    setState(() => _dirty = true);
    _say('Повторено: ${res['done']}');
  }

  Future<void> _recompute() async {
    if (_scene == null) return;
    _apply(await _run('Расстановка…', () => _call('recompute')));
    _dirty = true;
    _say('Стыки и светофоры расставлены заново');
  }

  Future<void> _addJoint(EdgeHit h) async {
    _apply(await _call('add_joint', {'edge': h.e.id, 't': h.t}));
    _dirty = true;
    _say('Стык добавлен');
  }

  Future<void> _removeJoint(JointObj j) async {
    _apply(await _call('remove_joint', {'joint': j.id}));
    _dirty = true;
    _say('Стык удалён');
  }

  Future<void> _toggleNegab(JointObj j) async {
    final res = await _call('toggle_negab', {'joint': j.id});
    _apply(res);
    _dirty = true;
    final nj = _scene!.joints.firstWhere((x) => x.id == j.id, orElse: () => j);
    setState(() => _selected = JointHit(nj));
    _say(nj.negab ? 'Стык негабаритный' : 'Стык габаритный');
  }

  String get _base => _baseOf(_doc);

  // ------------------------------------------------------------------ ручные правки
  /// Команда правки: пересчёт схемы, отметка «не сохранено», короткое сообщение.
  Future<Map<String, dynamic>?> _edit(String cmd, Map<String, dynamic> args, String ok) async {
    if (_scene == null) return null;
    if (_renaming == null) _focus.requestFocus(); // горячие клавиши – снова к схеме
    final res = await _run('Пересчёт…', () => _call(cmd, args));
    if (res == null) return null;
    _apply(res);
    setState(() => _dirty = true);
    _say(ok);
    return res;
  }

  Future<void> _moveJoint(JointObj j, double t) async {
    if (await _edit('move_joint', {'joint': j.id, 't': t}, 'Стык перенесён') == null) return;
    final nj = _scene!.joints.where((x) => x.id == j.id).firstOrNull;
    if (nj != null) setState(() => _selected = JointHit(nj));
  }

  Future<void> _addSegment(Map<String, dynamic> a, Map<String, dynamic> b) =>
      _edit('edit_track', {'op': 'add_edge', 'a': a, 'b': b}, 'Отрезок добавлен – схема перестроена');

  Future<void> _deleteChain(EdgeHit h) =>
      _edit('edit_track', {'op': 'delete_edge', 'edge': h.e.id}, 'Отрезок удалён – схема перестроена');

  static const _endNames = {'tupik': 'тупик', 'peregon': 'перегон', 'pp': 'подъездной путь'};

  Future<void> _setEnd(NodeObj n, String mark) =>
      _edit('edit_track', {'op': 'set_end', 'node': n.id, 'mark': mark}, 'Конец пути: ${_endNames[mark]}');

  Future<void> _nodeMenu(Offset global, NodeObj n) async {
    final t = Tok.of(context);
    final v = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(global.dx, global.dy, global.dx, global.dy),
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      items: [
        PopupMenuItem<String>(
          enabled: false,
          height: 26,
          child: Text(
            'ТИП КОНЦА ПУТИ',
            style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
          ),
        ),
        for (final e in _endNames.entries)
          PopupMenuItem<String>(
            value: e.key,
            height: 32,
            child: Row(
              children: [
                SizedBox(width: 20, child: n.mark == e.key ? Icon(Icons.check, size: 15, color: t.accent) : null),
                Text(e.value[0].toUpperCase() + e.value.substring(1), style: TextStyle(fontSize: 13, color: t.text)),
              ],
            ),
          ),
      ],
    );
    if (v != null && v != n.mark) await _setEnd(n, v);
  }

  Future<void> _editSignal(SignalObj g, {String? name, String? kind, bool delete = false}) async {
    await _edit('edit_signal', {
      'signal': g.id,
      'name': ?name,
      'kind': ?kind,
      if (delete) 'delete': true,
    }, delete ? 'Светофор ${g.name} удалён' : 'Светофор изменён');
    if (!delete) _reselectSignal(g.joint, g.toward);
  }

  Future<void> _resetSignal(SignalObj g) async {
    await _edit('reset_signal', {'signal': g.id}, 'Светофор – как по правилам');
    _reselectSignal(g.joint, g.toward);
  }

  Future<void> _addSignal(JointObj j, int toward) async {
    if (await _edit('add_signal', {'joint': j.id, 'toward': toward}, 'Светофор добавлен – задайте имя и тип') == null) {
      return;
    }
    _reselectSignal(j.id, toward);
  }

  /// После пересчёта номера светофоров меняются – выбрать тот же по стыку и направлению.
  void _reselectSignal(int joint, int toward) {
    final g = _scene?.signals.where((x) => x.joint == joint && x.toward == toward).firstOrNull;
    if (g != null) {
      setState(() {
        _selected = SignalHit(g);
        _tab = 0;
      });
    }
  }

  // ------------------------------------------------------------------ «Объясни»
  static String? _hitKey(Hit? h) => switch (h) {
    JointHit(:final j) => 'joint:${j.id}',
    SignalHit(:final s) => 'signal:${s.id}',
    SectionHit(:final sec) => 'section:${sec.name}',
    NodeHit(:final n) => 'node:${n.id}',
    _ => null,
  };

  /// Выделили объект в режиме «Объясни» – запросить объяснение (один раз на объект и сцену).
  void _syncExplain() {
    if (!_explain) return;
    final what = _hitKey(_selected);
    final key = what == null ? null : '$what@${identityHashCode(_scene)}';
    if (key == _explainKey) return;
    _explainKey = key;
    _explainData = null; // выбрали другое – не показываем объяснение прошлого
    if (what == null) return;
    final i = what.indexOf(':');
    _call('explain', {'what': what.substring(0, i), 'target': what.substring(i + 1)})
        .then((r) {
          if (mounted && _explainKey == key) setState(() => _explainData = r);
        })
        .catchError((Object e) {
          if (mounted && _explainKey == key) {
            setState(
              () => _explainData = {
                'title': 'Не получилось объяснить',
                'items': [
                  {'h': 'Ошибка', 't': '$e'},
                ],
              },
            );
          }
        });
  }

  void _toggleExplain() => setState(() {
    _explain = !_explain;
    _explainKey = null;
    _explainData = null;
    if (_explain) {
      _right = true; // объяснение – в правой панели
      _tab = 0;
    }
  });

  Widget _explainCard(Tok t) {
    final d = _explainData;
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
                Expanded(
                  child: Text(
                    'ОБЪЯСНИ',
                    style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.accent),
                  ),
                ),
                _IconBtn(Icons.close, 'Выключить (F1)', _toggleExplain, size: 26),
              ],
            ),
          ),
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: d == null
                  ? Text(
                      _selected == null
                          ? 'Кликните по стыку, светофору, стрелке, концу пути или участку – объясню, '
                                'почему он стоит именно так.'
                          : 'Секунду…',
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
                            style: TextStyle(
                              fontSize: 10,
                              letterSpacing: 0.5,
                              fontWeight: FontWeight.w600,
                              color: t.muted,
                            ),
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

  Future<void> _export(String kind) async {
    if (_scene == null) return;
    final (ext, label, suffix, cmd) = switch (kind) {
      'png' => ('png', 'PNG', '_стыки', 'export_png'),
      'pdf' => ('pdf', 'PDF', '_листы', 'export_pdf'),
      _ => ('docx', 'Документ Word', '_ведомость', 'export_docx'),
    };
    final picked = pickSave('$_base$suffix.$ext', label, ext);
    if (picked == null) return;
    var path = picked;
    if (!path.toLowerCase().endsWith('.$ext')) path = '$path.$ext';
    final r = await _run('Сохранение…', () => _call(cmd, {'path': path, 'title': _base}));
    if (r != null) _say('Сохранено: ${path.split(Platform.pathSeparator).last}');
  }

  void _selectSignal(SignalObj s) {
    setState(() => _selected = SignalHit(s)); // остаёмся в списке – удобно листать
    _cam.focus(s.box);
  }

  void _selectSection(SectionObj s) {
    setState(() => _selected = SectionHit(s));
    _cam.focus(s.box);
  }

  // ------------------------------------------------------------------ клавиши
  KeyEventResult _onKey(FocusNode n, KeyEvent e) {
    if (e is! KeyDownEvent) return KeyEventResult.ignored;
    // печатают в поле (имя таба, имя светофора) – горячие клавиши молчат
    final pf = FocusManager.instance.primaryFocus;
    if (_renaming != null || pf?.context?.findAncestorWidgetOfExactType<EditableText>() != null) {
      return KeyEventResult.ignored;
    }
    final ctrl = HardwareKeyboard.instance.isControlPressed;
    final shift = HardwareKeyboard.instance.isShiftPressed;
    final k = e.logicalKey;
    if (k == LogicalKeyboardKey.f1) {
      if (_scene != null) _toggleExplain();
    } else if (k == LogicalKeyboardKey.keyT && !ctrl) {
      if (_scene != null) setState(() => _tool = Tool.track);
    } else if (k == LogicalKeyboardKey.f2) {
      if (_doc != null) _startRename(_doc!);
    } else if (ctrl && k == LogicalKeyboardKey.tab) {
      _cycleTab(shift ? -1 : 1);
    } else if (ctrl && k == LogicalKeyboardKey.keyW) {
      if (_doc != null) _closeTab(_doc!);
    } else if (ctrl && k == LogicalKeyboardKey.keyO) {
      if (_ready) _open();
    } else if (ctrl && k == LogicalKeyboardKey.keyS) {
      _save(as: shift);
    } else if (ctrl && (k == LogicalKeyboardKey.keyY || (shift && k == LogicalKeyboardKey.keyZ))) {
      _redo();
    } else if (ctrl && k == LogicalKeyboardKey.keyZ) {
      _undo();
    } else if (ctrl && k == LogicalKeyboardKey.keyE) {
      _export('png');
    } else if (ctrl && k == LogicalKeyboardKey.keyP) {
      _export('pdf');
    } else if (ctrl && k == LogicalKeyboardKey.keyR) {
      _recompute();
    } else if (k == LogicalKeyboardKey.keyV) {
      setState(() => _tool = Tool.select);
    } else if (k == LogicalKeyboardKey.keyJ) {
      setState(() => _tool = Tool.joint);
    } else if (k == LogicalKeyboardKey.escape) {
      setState(() {
        _selected = null;
        _tool = Tool.select;
      });
    } else if ((k == LogicalKeyboardKey.delete || k == LogicalKeyboardKey.backspace) && _selected is JointHit) {
      _removeJoint((_selected as JointHit).j);
    } else if ((k == LogicalKeyboardKey.delete || k == LogicalKeyboardKey.backspace) && _selected is SignalHit) {
      _editSignal((_selected as SignalHit).s, delete: true);
    } else if ((k == LogicalKeyboardKey.delete || k == LogicalKeyboardKey.backspace) &&
        _selected is EdgeHit &&
        _tool == Tool.track) {
      _deleteChain(_selected as EdgeHit);
    } else if (k == LogicalKeyboardKey.keyN && _selected is JointHit) {
      _toggleNegab((_selected as JointHit).j);
    } else if (k == LogicalKeyboardKey.digit0 || k == LogicalKeyboardKey.numpad0) {
      _cam.fit();
    } else if (k == LogicalKeyboardKey.equal || k == LogicalKeyboardKey.numpadAdd) {
      _cam.zoomBy(1.4);
    } else if (k == LogicalKeyboardKey.minus || k == LogicalKeyboardKey.numpadSubtract) {
      _cam.zoomBy(1 / 1.4);
    } else {
      return KeyEventResult.ignored;
    }
    return KeyEventResult.handled;
  }

  // ------------------------------------------------------------------ заголовок окна
  String? _title;

  /// «файл – Стыки X.Y.Z»: версия видна сразу (та же, что сверяется с релизами).
  void _syncTitle() {
    final app = 'Стыки $appVersion';
    final d = _doc;
    final title = d == null ? app : '${d.dirty ? '● ' : ''}${_tabTitle(d)} — $app';
    if (title == _title) return;
    _title = title;
    _instance.invokeMethod('setTitle', title).catchError((_) => null); // в тестах окна нет
  }

  // ------------------------------------------------------------------ разметка
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    if (_fatal != null) return _FatalScreen(text: _fatal!);
    _syncTitle();
    _syncExplain();
    return Focus(
      focusNode: _focus,
      autofocus: true,
      onKeyEvent: _onKey,
      child: Scaffold(
        body: Column(
          children: [
            _toolbar(t),
            if (_docs.isNotEmpty) _tabBar(t),
            SizedBox(
              height: 2,
              child: _busy
                  ? LinearProgressIndicator(minHeight: 2, color: t.accent, backgroundColor: t.panel)
                  : Container(color: t.line, height: 1, margin: const EdgeInsets.only(bottom: 1)),
            ),
            Expanded(
              child: Row(
                children: [
                  if (_left) _leftPanel(t),
                  Expanded(child: _canvas(t)),
                  if (_right && _scene != null) _rightPanel(t),
                ],
              ),
            ),
            _statusBar(t),
          ],
        ),
      ),
    );
  }

  Widget _toolbar(Tok t) {
    final has = _scene != null;
    return Container(
      height: 40,
      color: t.panel,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          _IconBtn(
            Icons.view_sidebar_outlined,
            'Левая панель',
            () => setState(() => _left = !_left),
            active: _left,
            flip: true,
          ),
          const _Sep(),
          _FileMenu(
            ready: _ready,
            hasScene: has,
            recent: _recent,
            onOpen: _open,
            onSave: () => _save(),
            onSaveAs: () => _save(as: true),
            onRecent: _openRecent,
            onClear: () => setState(() {
              Recent.clear();
              _recent = [];
            }),
          ),
          const _Sep(),
          _IconBtn(
            Icons.undo,
            _scene?.undo == null ? 'Отменить (Ctrl+Z)' : 'Отменить: ${_scene!.undo} (Ctrl+Z)',
            _scene?.undo == null ? null : _undo,
          ),
          _IconBtn(
            Icons.redo,
            _scene?.redo == null ? 'Повторить (Ctrl+Y)' : 'Повторить: ${_scene!.redo} (Ctrl+Y)',
            _scene?.redo == null ? null : _redo,
          ),
          const _Sep(),
          _ToolBtn(
            Icons.near_me_outlined,
            'Выбор',
            'V',
            _tool == Tool.select,
            () => setState(() => _tool = Tool.select),
          ),
          _ToolBtn(
            Icons.add_road,
            'Стык',
            'J',
            _tool == Tool.joint,
            has ? () => setState(() => _tool = Tool.joint) : null,
          ),
          _ToolBtn(
            Icons.timeline,
            'Пути',
            'T',
            _tool == Tool.track,
            has ? () => setState(() => _tool = Tool.track) : null,
          ),
          const _Sep(),
          _ToolBtn(Icons.school_outlined, 'Объясни', 'F1', _explain, has ? _toggleExplain : null),
          const _Sep(),
          _TextBtn('Расставить заново', 'Ctrl+R', has ? _recompute : null),
          const Spacer(),
          if (_update != null) ...[
            _UpdateChip(version: _update!.version, onTap: _showUpdate),
            const SizedBox(width: 8),
          ],
          _ExportMenu(enabled: has, onPick: _export),
          const SizedBox(width: 4),
          _IconBtn(
            Theme.of(context).brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
            'Тема',
            widget.onToggleTheme,
          ),
          if (has)
            _IconBtn(
              Icons.view_sidebar_outlined,
              'Правая панель',
              () => setState(() => _right = !_right),
              active: _right,
            ),
        ],
      ),
    );
  }

  Widget _tabBar(Tok t) {
    return Container(
      height: 32,
      decoration: BoxDecoration(
        color: t.panel2,
        border: Border(top: BorderSide(color: t.line)),
      ),
      child: Row(
        children: [
          Flexible(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final d in _docs)
                    _DocTab(
                      title: _tabTitle(d),
                      tooltip: d.scene?.source?['project'] as String? ?? d.path ?? '',
                      project: d.scene?.source?['project'] != null || (d.path?.toLowerCase().endsWith('.stj') ?? false),
                      active: identical(d, _doc),
                      dirty: d.dirty,
                      loading: d.scene == null,
                      editing: identical(d, _renaming),
                      editText: _baseOf(d),
                      onTap: () => _activate(d),
                      onClose: () => _closeTab(d),
                      onDoubleTap: () => _startRename(d),
                      onMenu: (p) => _tabMenu(d, p),
                      onRename: (v) => _commitRename(d, v),
                      onCancelRename: _endRename,
                    ),
                ],
              ),
            ),
          ),
          _IconBtn(Icons.add, 'Открыть в новом табе (Ctrl+O)', _ready && !_busy ? _open : null, size: 32),
        ],
      ),
    );
  }

  String _tabTitle(_Doc d) {
    if (d.name != null) return d.name!;
    final src = d.scene?.source;
    if (src?['project'] != null) return '${_baseOf(d)}.stj';
    return (src?['name'] as String?) ?? d.path?.split(Platform.pathSeparator).last ?? 'схема';
  }

  Widget _canvas(Tok t) {
    return Container(
      decoration: BoxDecoration(
        border: Border.symmetric(vertical: BorderSide(color: t.line)),
      ),
      child: Stack(
        children: [
          // у каждого таба свой холст: зум и положение сохраняются при переключении;
          // клик по схеме возвращает горячие клавиши (если фокус был в поле ввода)
          Positioned.fill(
            child: Listener(
              onPointerDown: (_) {
                if (!_focus.hasPrimaryFocus && _renaming == null) _focus.requestFocus();
              },
              child: _docs.isEmpty
                  ? _schemeView(null)
                  : IndexedStack(
                      index: _doc == null ? 0 : _docs.indexOf(_doc!),
                      children: [for (final d in _docs) _schemeView(d)],
                    ),
            ),
          ),
          if (_scene == null) Positioned.fill(child: _empty(t)),
          if (_scene != null) Positioned(right: 10, bottom: 10, child: _zoomBox(t)),
          if (_toast != null)
            Positioned(
              left: 0,
              right: 0,
              bottom: 14,
              child: Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  decoration: BoxDecoration(color: t.text, borderRadius: BorderRadius.circular(2)),
                  child: Text(_toast!, style: TextStyle(color: t.panel, fontSize: 12)),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _schemeView(_Doc? d) {
    return SchemeView(
      key: ValueKey(d?.id ?? 0),
      scene: d?.scene,
      grid: _layers['grid']!,
      tool: _tool,
      selected: d?.selected,
      controller: d?.cam ?? _noCam,
      onSelect: (h) => setState(() {
        _selected = h;
        if (h != null) _tab = 0;
      }),
      onAddJoint: _addJoint,
      onHover: (h, ord) => setState(() {
        _hover = h;
        _ordinate = ord;
      }),
      onContext: _contextMenu,
      onMoveJoint: _moveJoint,
      onAddSegment: _addSegment,
      onNodeMenu: _nodeMenu,
    );
  }

  Widget _empty(Tok t) {
    return ColoredBox(
      color: t.bg,
      child: Center(
        child: SizedBox(
          width: 3 * 196 + 20,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Схема станции',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: t.text),
              ),
              const SizedBox(height: 8),
              Text(
                _busy
                    ? _busyText
                    : 'Откройте фото или скан однониточной схемы из задания. '
                          'Программа перечертит её на миллиметровке и расставит '
                          'изолирующие стыки и светофоры по методичке.',
                style: TextStyle(fontSize: 13, height: 1.45, color: t.muted),
              ),
              const SizedBox(height: 18),
              if (!_busy)
                Row(
                  children: [
                    _PrimaryBtn('Открыть схему…', _ready ? _open : null),
                    const SizedBox(width: 8),
                    _TextBtn('Пример', null, _ready ? _openSample : null, outlined: true),
                  ],
                ),
              if (!_ready) ...[
                const SizedBox(height: 12),
                Text('Запуск движка…', style: TextStyle(fontSize: 12, color: t.muted)),
              ],
              if (!_busy && _recent.isNotEmpty) ...[
                const SizedBox(height: 28),
                Text(
                  'НЕДАВНИЕ',
                  style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final it in _recent.take(6)) _RecentCard(it: it, onTap: _ready ? () => _openRecent(it) : null),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _zoomBox(Tok t) {
    return Container(
      height: 28,
      decoration: BoxDecoration(
        color: t.panel,
        border: Border.all(color: t.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _IconBtn(Icons.remove, 'Отдалить (−)', () => _cam.zoomBy(1 / 1.4), size: 26),
          SizedBox(
            width: 52,
            child: Text(
              '${_cam.zoomPercent.round()}%',
              textAlign: TextAlign.center,
              style: TextStyle(fontFamily: mono, fontSize: 12, color: t.text),
            ),
          ),
          _IconBtn(Icons.add, 'Приблизить (+)', () => _cam.zoomBy(1.4), size: 26),
          Container(width: 1, height: 16, color: t.line),
          _IconBtn(Icons.fit_screen_outlined, 'Вписать (0)', _cam.fit, size: 26),
        ],
      ),
    );
  }

  Future<void> _contextMenu(Offset global, Hit h) async {
    if (h is! JointHit) return;
    final v = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(global.dx, global.dy, global.dx, global.dy),
      shape: const RoundedRectangleBorder(),
      items: [
        PopupMenuItem(
          value: 'negab',
          height: 30,
          child: Text(
            h.j.negab ? 'Сделать габаритным   N' : 'Сделать негабаритным   N',
            style: const TextStyle(fontSize: 13),
          ),
        ),
        const PopupMenuItem(
          value: 'del',
          height: 30,
          child: Text('Удалить стык   Del', style: TextStyle(fontSize: 13)),
        ),
      ],
    );
    if (v == 'negab') _toggleNegab(h.j);
    if (v == 'del') _removeJoint(h.j);
  }

  // ------------------------------------------------------------------ панели
  Widget _leftPanel(Tok t) {
    final src = _scene?.source;
    return Container(
      width: 244,
      color: t.panel,
      child: ListView(
        padding: EdgeInsets.zero,
        children: [
          _Section(
            'Исходник',
            trailing: _IconBtn(
              Icons.folder_open_outlined,
              'Открыть другую схему (Ctrl+O)',
              _ready ? _open : null,
              size: 24,
            ),
            children: [
              if (src?['image'] case final String img)
                Container(
                  height: 110,
                  decoration: BoxDecoration(
                    color: t.paper,
                    border: Border.all(color: t.line),
                  ),
                  child: Image.file(File(img), fit: BoxFit.contain),
                )
              else
                Text('Не загружена', style: TextStyle(fontSize: 12, color: t.muted)),
              if (src != null) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        _base + (src['project'] != null ? '.stj' : ''),
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, color: t.text),
                      ),
                    ),
                    if (_dirty)
                      Tooltip(
                        message: 'Есть несохранённые изменения (Ctrl+S)',
                        child: Text('не сохранено', style: TextStyle(fontSize: 11, color: t.accent)),
                      ),
                  ],
                ),
                if (src['project'] != null)
                  Text(
                    'исходник: ${src['name']}',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 11, color: t.muted),
                  ),
                Text(
                  'наклон исправлен на ${((src['angle'] as num?) ?? 0).toStringAsFixed(1)}°',
                  style: TextStyle(fontSize: 11, color: t.muted),
                ),
              ],
            ],
          ),
          // настройки схемы – только когда схема открыта
          if (_scene != null) ...[
            _Section(
              'Лист',
              children: [
                _Check('Два листа (горловины раздельно)', _twoSheets, (v) {
                  setState(() => _twoSheets = v);
                  _relayout();
                }),
                const SizedBox(height: 6),
                Opacity(
                  opacity: _twoSheets ? 1 : 0.4,
                  child: Row(
                    children: [
                      for (final f in const ['A4', 'A3', 'A2'])
                        Expanded(
                          child: _Seg(
                            f,
                            _fmt == f,
                            _twoSheets
                                ? () {
                                    setState(() => _fmt = f);
                                    _relayout();
                                  }
                                : null,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
            _Section(
              'Движение',
              children: [
                Text('Нечётная горловина', style: TextStyle(fontSize: 12, color: t.muted)),
                const SizedBox(height: 6),
                Row(
                  children: [
                    for (final (label, right) in const [('Слева', false), ('Справа', true)])
                      Expanded(
                        child: _Seg(label, _oddRight == right, () {
                          if (_oddRight == right) return;
                          setState(() => _oddRight = right);
                          _relayout();
                        }),
                      ),
                  ],
                ),
              ],
            ),
            _Section(
              'Слои',
              children: [
                for (final e in _layerNames.entries) _Check(e.value, _layers[e.key]!, (v) => _setLayer(e.key, v)),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _rightPanel(Tok t) {
    return Container(
      width: 300,
      color: t.panel,
      child: Column(
        children: [
          Container(
            height: 34,
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: t.line)),
            ),
            child: Row(
              children: [
                for (final (i, n) in const ['Свойства', 'Светофоры', 'Участки'].indexed)
                  _Tab(n, _tab == i, () => setState(() => _tab = i)),
              ],
            ),
          ),
          if (_explain && _scene != null) _explainCard(t),
          Expanded(
            child: switch (_tab) {
              0 => _props(t),
              1 => _signals(t),
              _ => _sections(t),
            },
          ),
        ],
      ),
    );
  }

  Widget _props(Tok t) {
    final s = _selected;
    Widget kv(String k, String v, {bool monoV = false}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 92,
            child: Text(k, style: TextStyle(fontSize: 12, color: t.muted)),
          ),
          Expanded(
            child: Text(
              v,
              style: TextStyle(fontSize: 12, color: t.text, fontFamily: monoV ? mono : null),
            ),
          ),
        ],
      ),
    );
    if (s is JointHit) {
      final j = s.j;
      return ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'Изолирующий стык',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
          ),
          const SizedBox(height: 8),
          kv('Правило', '${j.rule}) ${j.text}'),
          kv('Габарит', j.negab ? 'негабаритный' : 'габаритный'),
          kv('Ордината', '${(j.pos.dx - _scene!.originX).toStringAsFixed(0)} мм', monoV: true),
          const SizedBox(height: 12),
          Row(
            children: [
              _TextBtn(j.negab ? 'Габаритный' : 'Негабаритный', 'N', () => _toggleNegab(j), outlined: true),
              const SizedBox(width: 6),
              _TextBtn('Удалить', 'Del', () => _removeJoint(j), outlined: true, danger: true),
            ],
          ),
          ..._jointSignalButtons(t, j),
          const SizedBox(height: 12),
          Text(
            'Потяните стык мышью – он сдвинется вдоль пути с шагом 5 мм.',
            style: TextStyle(fontSize: 11.5, height: 1.4, color: t.muted),
          ),
        ],
      );
    }
    if (s is NodeHit) {
      final n = s.n;
      if (n.isSwitch) {
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Text(
              'Стрелка ${n.label}',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
            ),
            const SizedBox(height: 8),
            kv('Ордината', '${(n.pos.dx - _scene!.originX).toStringAsFixed(0)} мм', monoV: true),
            const SizedBox(height: 10),
            Text(
              'Номер – по правилам п. 2.3. Нажмите F1, чтобы увидеть объяснение.',
              style: TextStyle(fontSize: 11.5, height: 1.4, color: t.muted),
            ),
          ],
        );
      }
      return ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'Конец пути${n.label.isEmpty ? '' : ' ${n.label}'}',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              for (final e in _endNames.entries)
                Expanded(
                  child: _Seg(
                    e.key == 'pp' ? 'п/п' : e.value[0].toUpperCase() + e.value.substring(1),
                    n.mark == e.key,
                    n.mark == e.key ? null : () => _setEnd(n, e.key),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            n.manual ? 'Тип задан вручную.' : 'Тип определён автоматически – если ошибся, выберите нужный.',
            style: TextStyle(fontSize: 11.5, height: 1.4, color: t.muted),
          ),
        ],
      );
    }
    if (s is EdgeHit) {
      return ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'Отрезок пути',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
          ),
          const SizedBox(height: 6),
          Text(
            'От стрелки до стрелки или до конца пути, через изломы.',
            style: TextStyle(fontSize: 12, height: 1.4, color: t.muted),
          ),
          const SizedBox(height: 12),
          Row(children: [_TextBtn('Удалить отрезок', 'Del', () => _deleteChain(s), outlined: true, danger: true)]),
          const SizedBox(height: 12),
          Text(
            'Лишний отрезок, распознанный по ошибке, – удалите. Чтобы добавить путь, '
            'протяните мышью от узла или пути.',
            style: TextStyle(fontSize: 11.5, height: 1.4, color: t.muted),
          ),
        ],
      );
    }
    if (s is SectionHit) {
      final c = s.sec;
      return ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'Участок ${c.name}',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
          ),
          const SizedBox(height: 8),
          kv('Тип', c.kind),
          kv('Расположение', c.throat),
          kv('Стрелки', c.switches.isEmpty ? '–' : c.switches.join(', ')),
          kv('Стыков', '${c.joints}', monoV: true),
          kv('Длина', '${c.length} мм на схеме', monoV: true),
          if (c.switches.length > 3) ...[
            const SizedBox(height: 8),
            Text('Больше трёх стрелок в участке (п. 2.4 и)', style: TextStyle(fontSize: 12, color: t.danger)),
          ],
        ],
      );
    }
    if (s is SignalHit) {
      final g = s.s;
      return ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'Светофор ${g.name}',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: t.text),
          ),
          const SizedBox(height: 8),
          if (g.manual) Text('изменён вручную', style: TextStyle(fontSize: 11.5, color: t.accent)),
          const SizedBox(height: 10),
          _SignalNameField(
            key: ValueKey('sig-${g.joint}-${g.toward}-${g.name}'),
            name: g.name,
            onSubmit: (v) {
              if (v.trim().isNotEmpty && v.trim() != g.name) _editSignal(g, name: v.trim());
            },
          ),
          const SizedBox(height: 8),
          _KindPicker(
            code: g.code,
            onPick: (c) => _editSignal(g, kind: c),
          ),
          const SizedBox(height: 10),
          kv('Ордината', '${g.ordinate} мм', monoV: true),
          kv('Основание', g.why),
          const SizedBox(height: 12),
          Row(
            children: [
              _TextBtn('Удалить', 'Del', () => _editSignal(g, delete: true), outlined: true, danger: true),
              if (g.manual) ...[
                const SizedBox(width: 6),
                _TextBtn('Как по правилам', null, () => _resetSignal(g), outlined: true),
              ],
            ],
          ),
        ],
      );
    }
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Text(
        _scene == null
            ? 'Нет схемы'
            : 'Ничего не выбрано.\n\nКлик по стыку, светофору, стрелке или концу пути – свойства.\n'
                  'Стык можно потянуть мышью вдоль пути.\n'
                  'J – «Стык»: клик по пути ставит стык.\n'
                  'T – «Пути»: исправить распознанную схему.\n'
                  'F1 – «Объясни»: почему объект стоит именно так.',
        style: TextStyle(fontSize: 12, height: 1.5, color: t.muted),
      ),
    );
  }

  /// Кнопки «добавить светофор» у стыка: в обе стороны по пути.
  List<Widget> _jointSignalButtons(Tok t, JointObj j) {
    final e = _scene!.edges.where((e) => e.id == j.edge).firstOrNull;
    if (e == null) return const [];
    String arrow(Offset to) {
      final d = to - j.pos;
      if (d.dx.abs() >= d.dy.abs()) return d.dx < 0 ? '←' : '→';
      return d.dy < 0 ? '↑' : '↓';
    }

    return [
      const SizedBox(height: 14),
      Text(
        'ДОБАВИТЬ СВЕТОФОР',
        style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
      ),
      const SizedBox(height: 6),
      Row(
        children: [
          _TextBtn('${arrow(e.a)} движение', null, () => _addSignal(j, e.na), outlined: true),
          const SizedBox(width: 6),
          _TextBtn('движение ${arrow(e.b)}', null, () => _addSignal(j, e.nb), outlined: true),
        ],
      ),
    ];
  }

  Widget _signals(Tok t) {
    final list = _scene?.signals ?? const <SignalObj>[];
    final sel = _selected is SignalHit ? (_selected as SignalHit).s.id : -1;
    return ListView.builder(
      itemCount: list.length,
      itemExtent: 44,
      itemBuilder: (c, i) {
        final s = list[i];
        return _SignalRow(s: s, selected: s.id == sel, onTap: () => _selectSignal(s));
      },
    );
  }

  Widget _sections(Tok t) {
    final list = _scene?.sections ?? const <SectionObj>[];
    final sel = _selected is SectionHit ? (_selected as SectionHit).sec.id : -1;
    // строки с заголовками групп: горловины и пути станции
    final rows = <Object>[];
    String? group;
    for (final s in list) {
      if (s.throat != group) {
        group = s.throat;
        rows.add(group);
      }
      rows.add(s);
    }
    return ListView.builder(
      itemCount: rows.length,
      itemBuilder: (c, i) {
        final r = rows[i];
        if (r is String) {
          return Container(
            height: 28,
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            color: t.panel2,
            child: Text(
              r.toUpperCase(),
              style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
            ),
          );
        }
        final s = r as SectionObj;
        return _SectionRow(s: s, selected: s.id == sel, onTap: () => _selectSection(s));
      },
    );
  }

  Widget _statusBar(Tok t) {
    String hint;
    final h = _hover;
    if (h is JointHit) {
      hint = 'Стык «${h.j.rule}» – ${h.j.text}${h.j.negab ? ' · негабаритный' : ''}';
    } else if (h is SignalHit) {
      hint = 'Светофор ${h.s.name} – ${h.s.why}';
    } else if (h is SectionHit) {
      final sw = h.sec.switches;
      hint = 'Участок ${h.sec.name} – ${h.sec.kind}${sw.isEmpty ? '' : ', стрелки ${sw.join(', ')}'}';
    } else if (h is NodeHit) {
      hint = h.n.isSwitch
          ? 'Стрелка ${h.n.label}'
          : 'Конец пути${h.n.label.isEmpty ? '' : ' ${h.n.label}'} – ${_endNames[h.n.mark] ?? 'тип не задан'}'
                '${_tool == Tool.track ? ' · клик – сменить тип' : ''}';
    } else if (_tool == Tool.track) {
      hint = h is EdgeHit
          ? 'Отрезок пути – клик выбрать, Del удалить · тяните – новый отрезок'
          : 'Пути: тяните от узла или пути – новый отрезок · клик по отрезку – выбрать · Esc – выход';
    } else if (_tool == Tool.joint) {
      hint = 'Стык: клик по пути ставит стык · Esc – выход';
    } else {
      hint = _scene == null
          ? (_ready ? 'Готово' : 'Запуск движка…')
          : 'Колесо – зум · перетаскивание – сдвиг · ПКМ по стыку – меню · 0 – вписать';
    }
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
            child: Text(hint, style: st, overflow: TextOverflow.ellipsis),
          ),
          if (_ordinate != null)
            Text('x ${_ordinate!.toStringAsFixed(1).padLeft(6)} мм', style: st.copyWith(fontFamily: mono)),
          const SizedBox(width: 16),
          if (_scene != null && _scene!.issues.isNotEmpty) ...[
            Tooltip(
              message: _scene!.issues.join('\n'),
              child: Row(
                children: [
                  Icon(Icons.warning_amber_rounded, size: 14, color: t.danger),
                  const SizedBox(width: 4),
                  Text('замечаний: ${_scene!.issues.length}', style: st.copyWith(color: t.danger)),
                ],
              ),
            ),
            const SizedBox(width: 16),
          ],
          if (_scene != null)
            Text(
              '${_scene!.joints.length} стыков · ${_scene!.signals.length} светофоров · '
              '${_scene!.sections.length} участков',
              style: st,
            ),
        ],
      ),
    );
  }
}

// ==================================================================== элементы

class _Sep extends StatelessWidget {
  const _Sep();
  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 20, margin: const EdgeInsets.symmetric(horizontal: 8), color: Tok.of(context).line);
}

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final String tip;
  final VoidCallback? onTap;
  final bool active, flip;
  final double size;
  const _IconBtn(this.icon, this.tip, this.onTap, {this.active = false, this.flip = false, this.size = 30});

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

class _TextBtn extends StatelessWidget {
  final String text;
  final String? key_;
  final VoidCallback? onTap;
  final bool outlined, danger;
  const _TextBtn(this.text, this.key_, this.onTap, {this.outlined = false, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final col = onTap == null ? t.muted.withValues(alpha: .5) : (danger ? t.danger : t.text);
    final child = Container(
      height: 28,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: outlined
          ? BoxDecoration(
              border: Border.all(color: t.line),
              color: t.panel,
            )
          : null,
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
            if (key_ != null) ...[
              const SizedBox(width: 6),
              Text(
                key_!,
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

class _PrimaryBtn extends StatelessWidget {
  final String text;
  final VoidCallback? onTap;
  const _PrimaryBtn(this.text, this.onTap);
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

class _ToolBtn extends StatelessWidget {
  final IconData icon;
  final String name, key_;
  final bool on;
  final VoidCallback? onTap;
  const _ToolBtn(this.icon, this.name, this.key_, this.on, this.onTap);
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final col = onTap == null ? t.muted.withValues(alpha: .5) : (on ? t.accent : t.text);
    return Tooltip(
      message: '$name ($key_)',
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

class _ExportMenu extends StatelessWidget {
  final bool enabled;
  final void Function(String) onPick;
  const _ExportMenu({required this.enabled, required this.onPick});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    PopupMenuItem<String> item(String v, String text, String key) => PopupMenuItem(
      value: v,
      height: 32,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
          Text(
            key,
            style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
          ),
        ],
      ),
    );
    return PopupMenuButton<String>(
      enabled: enabled,
      tooltip: 'Экспорт',
      position: PopupMenuPosition.under,
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      elevation: 2,
      onSelected: onPick,
      itemBuilder: (_) => [
        item('pdf', 'PDF – два листа, М 1:1', 'Ctrl+P'),
        item('png', 'PNG – вся схема', 'Ctrl+E'),
        item('docx', 'Ведомость для записки (Word)', ''),
      ],
      child: Container(
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(border: Border.all(color: t.line)),
        child: Row(
          children: [
            Text('Экспорт', style: TextStyle(fontSize: 12.5, color: enabled ? t.text : t.muted)),
            Icon(Icons.arrow_drop_down, size: 18, color: t.muted),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final Widget? trailing;
  final List<Widget> children;
  const _Section(this.title, {this.trailing, required this.children});
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
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    title.toUpperCase(),
                    style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
                  ),
                ),
                ?trailing,
              ],
            ),
          ),
          const SizedBox(height: 4),
          ...children,
        ],
      ),
    );
  }
}

class _Check extends StatelessWidget {
  final String text;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _Check(this.text, this.value, this.onChanged);
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: () => onChanged(!value),
      hoverColor: t.panel2,
      child: SizedBox(
        height: 26,
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
              child: Text(text, style: TextStyle(fontSize: 12.5, color: t.text)),
            ),
          ],
        ),
      ),
    );
  }
}

class _Seg extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback? onTap;
  const _Seg(this.text, this.on, this.onTap);
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
          style: TextStyle(fontSize: 12, fontFamily: mono, color: on ? Colors.white : t.text),
        ),
      ),
    );
  }
}

class _Tab extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback onTap;
  const _Tab(this.text, this.on, this.onTap);
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      hoverColor: t.panel2,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: on ? t.accent : Colors.transparent, width: 2)),
        ),
        child: Text(
          text,
          style: TextStyle(
            fontSize: 12.5,
            color: on ? t.text : t.muted,
            fontWeight: on ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }
}

class _SignalRow extends StatelessWidget {
  final SignalObj s;
  final bool selected;
  final VoidCallback onTap;
  const _SignalRow({required this.s, required this.selected, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return InkWell(
      onTap: onTap,
      hoverColor: t.panel2,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: selected ? t.accentSoft : null,
          border: Border(
            left: BorderSide(color: selected ? t.accent : Colors.transparent, width: 2),
            bottom: BorderSide(color: t.line.withValues(alpha: .6)),
          ),
        ),
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
                  Text(
                    s.kind,
                    style: TextStyle(fontSize: 12, color: t.text),
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    s.why,
                    style: TextStyle(fontSize: 11, color: t.muted),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            Text(
              '${s.ordinate}',
              style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionRow extends StatelessWidget {
  final SectionObj s;
  final bool selected;
  final VoidCallback onTap;
  const _SectionRow({required this.s, required this.selected, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    final many = s.switches.length > 3;
    final sub = [if (s.switches.isNotEmpty) 'стр. ${s.switches.join(', ')}' else s.kind, '${s.joints} ст.'].join(' · ');
    return InkWell(
      onTap: onTap,
      hoverColor: t.panel2,
      child: Container(
        height: 40,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: selected ? t.accentSoft : null,
          border: Border(
            left: BorderSide(color: selected ? t.accent : Colors.transparent, width: 2),
            bottom: BorderSide(color: t.line.withValues(alpha: .6)),
          ),
        ),
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
            Text(
              '${s.length}',
              style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _FileMenu extends StatelessWidget {
  final bool ready, hasScene;
  final List<RecentItem> recent;
  final VoidCallback onOpen, onSave, onSaveAs, onClear;
  final void Function(RecentItem) onRecent;
  const _FileMenu({
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
    PopupMenuItem<Object> item(Object v, String text, String key, {bool enabled = true}) => PopupMenuItem(
      value: v,
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
            key,
            style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted),
          ),
        ],
      ),
    );
    return PopupMenuButton<Object>(
      enabled: ready,
      tooltip: 'Файл',
      position: PopupMenuPosition.under,
      shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
      color: t.panel,
      elevation: 2,
      constraints: const BoxConstraints(minWidth: 280, maxWidth: 360),
      onSelected: (v) {
        switch (v) {
          case 'open':
            onOpen();
          case 'save':
            onSave();
          case 'saveas':
            onSaveAs();
          case 'clear':
            onClear();
          case RecentItem it:
            onRecent(it);
        }
      },
      itemBuilder: (_) => [
        item('open', 'Открыть…', 'Ctrl+O'),
        item('save', 'Сохранить работу', 'Ctrl+S', enabled: hasScene),
        item('saveas', 'Сохранить как…', 'Ctrl+Shift+S', enabled: hasScene),
        if (recent.isNotEmpty) ...[
          const PopupMenuDivider(height: 9),
          PopupMenuItem<Object>(
            enabled: false,
            height: 22,
            child: Text(
              'НЕДАВНИЕ',
              style: TextStyle(fontSize: 10.5, letterSpacing: 0.6, fontWeight: FontWeight.w600, color: t.muted),
            ),
          ),
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
                        Text(
                          it.name,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 13, color: t.text),
                        ),
                        Text(
                          _folder(it.path),
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
          item('clear', 'Очистить список', ''),
        ],
      ],
      child: Container(
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Row(
          children: [
            Text('Файл', style: TextStyle(fontSize: 12.5, color: ready ? t.text : t.muted)),
            Icon(Icons.arrow_drop_down, size: 18, color: t.muted),
          ],
        ),
      ),
    );
  }
}

String _folder(String path) {
  final i = path.lastIndexOf(Platform.pathSeparator);
  return i > 0 ? path.substring(0, i) : path;
}

String _ago(DateTime d) {
  final m = DateTime.now().difference(d).inMinutes;
  if (m < 1) return 'только что';
  if (m < 60) return '$m мин назад';
  if (m < 60 * 24) return '${m ~/ 60} ч назад';
  if (m < 60 * 24 * 7) return '${m ~/ (60 * 24)} дн назад';
  return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';
}

class _RecentCard extends StatelessWidget {
  final RecentItem it;
  final VoidCallback? onTap;
  const _RecentCard({required this.it, required this.onTap});
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
                    Text(_ago(it.opened), style: TextStyle(fontSize: 11, color: t.muted)),
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

class _DocTab extends StatefulWidget {
  final String title, tooltip, editText;
  final bool project, active, dirty, loading, editing;
  final VoidCallback onTap, onClose, onDoubleTap, onCancelRename;
  final void Function(Offset global) onMenu;
  final void Function(String) onRename;
  const _DocTab({
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
  State<_DocTab> createState() => _DocTabState();
}

class _DocTabState extends State<_DocTab> {
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
    // как в VS Code: у несохранённого – точка, при наведении она становится крестиком
    final showClose = _hover || (w.active && !w.dirty);
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: Listener(
        // средняя кнопка мыши – закрыть
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
                color: w.active ? t.panel : (_hover ? t.panel : Colors.transparent),
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
                        ? _TabNameField(text: w.editText, onSubmit: w.onRename, onCancel: w.onCancelRename)
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
class _TabNameField extends StatefulWidget {
  final String text;
  final void Function(String) onSubmit;
  final VoidCallback onCancel;
  const _TabNameField({required this.text, required this.onSubmit, required this.onCancel});

  @override
  State<_TabNameField> createState() => _TabNameFieldState();
}

class _TabNameFieldState extends State<_TabNameField> {
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
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.zero,
              borderSide: BorderSide(color: t.accent),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.zero,
              borderSide: BorderSide(color: t.accent),
            ),
          ),
        ),
      ),
    );
  }
}

/// Имя светофора: Enter – применить.
class _SignalNameField extends StatefulWidget {
  final String name;
  final void Function(String) onSubmit;
  const _SignalNameField({super.key, required this.name, required this.onSubmit});

  @override
  State<_SignalNameField> createState() => _SignalNameFieldState();
}

class _SignalNameFieldState extends State<_SignalNameField> {
  late final _ctl = TextEditingController(text: widget.name);

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
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
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.zero,
                  borderSide: BorderSide(color: t.line),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.zero,
                  borderSide: BorderSide(color: t.accent),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// Тип светофора.
class _KindPicker extends StatelessWidget {
  static const kinds = {
    'entry': 'входной мачтовый',
    'exit_mast': 'выходной мачтовый',
    'exit_dwarf': 'выходной карликовый',
    'man_dwarf': 'маневровый карликовый',
    'man_mast': 'маневровый мачтовый',
  };
  final String code;
  final void Function(String) onPick;
  const _KindPicker({required this.code, required this.onPick});

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

class _UpdateChip extends StatelessWidget {
  final String version;
  final VoidCallback onTap;
  const _UpdateChip({required this.version, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    return Tooltip(
      message: 'Доступна новая версия',
      child: InkWell(
        onTap: onTap,
        child: Container(
          height: 26,
          padding: const EdgeInsets.symmetric(horizontal: 9),
          decoration: BoxDecoration(
            color: t.accentSoft,
            border: Border.all(color: t.accent),
          ),
          child: Row(
            children: [
              Icon(Icons.system_update_alt, size: 14, color: t.accent),
              const SizedBox(width: 6),
              Text('Обновление $version', style: TextStyle(fontSize: 12, color: t.accent)),
            ],
          ),
        ),
      ),
    );
  }
}

class _FatalScreen extends StatelessWidget {
  final String text;
  const _FatalScreen({required this.text});
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
                child: SelectableText(
                  text,
                  style: TextStyle(fontFamily: mono, fontSize: 12, color: t.muted),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
