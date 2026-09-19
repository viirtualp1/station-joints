import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show AppExitResponse;

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

class _HomeState extends State<Home> {
  final _backend = Backend();
  final _cam = SchemeController();
  final _focus = FocusNode();

  bool _ready = false;
  String? _fatal;
  bool _busy = false;
  String _busyText = '';
  Scene? _scene;
  String? _path;

  Tool _tool = Tool.select;
  Hit? _selected;
  Hit? _hover;
  double? _ordinate;
  int _tab = 0; // 0 свойства, 1 светофоры, 2 участки
  List<RecentItem> _recent = Recent.load();
  bool _dirty = false; // есть несохранённые изменения
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

  @override
  void initState() {
    super.initState();
    _cam.addListener(() => setState(() {}));
    // закрытие окна: спросить про несохранённые правки
    _life = AppLifecycleListener(onExitRequested: _onExitRequested);
    _autosaveTimer = Timer.periodic(const Duration(seconds: 30), (_) => _autosave());
    _start();
  }

  Future<void> _start() async {
    try {
      await _backend.start();
      await _backend.call('ping');
      setState(() => _ready = true);
      final restored = await _offerRestore();
      final p = widget.initialPath;
      if (!restored && p != null && File(p).existsSync()) await _load(p);
    } catch (e) {
      setState(() => _fatal = '$e\n\n${_backend.stderrTail}');
    }
    unawaited(_checkUpdate());
  }

  @override
  void dispose() {
    _life.dispose();
    _autosaveTimer?.cancel();
    _backend.dispose();
    _toastTimer?.cancel();
    super.dispose();
  }

  Future<AppExitResponse> _onExitRequested() async {
    if (!await _confirmDiscard()) return AppExitResponse.cancel;
    _clearAutosave();
    return AppExitResponse.exit;
  }

  // ------------------------------------------------------------------ автосохранение
  static String get _autoDir => '${Recent.dir}${Platform.pathSeparator}autosave';
  static File get _autoMeta => File('$_autoDir${Platform.pathSeparator}autosave.json');
  static String get _autoFile => '$_autoDir${Platform.pathSeparator}autosave.stj';
  bool _autosaving = false;

  /// Раз в 30 с, если есть несохранённые правки, – резервная копия работы.
  Future<void> _autosave() async {
    if (!_dirty || _scene == null || _busy || _autosaving) return;
    _autosaving = true;
    try {
      await _backend.call('save_project', {'path': _autoFile, 'autosave': true});
      final src = _scene?.source ?? const {};
      _autoMeta.writeAsStringSync(
        jsonEncode({
          'project': src['project'],
          'origin': src['project'] == null ? _path : null,
          'name': _base,
          'saved': DateTime.now().toIso8601String(),
        }),
      );
    } catch (_) {
      // резервная копия – не критично
    } finally {
      _autosaving = false;
    }
  }

  void _clearAutosave() {
    for (final f in [_autoMeta, File(_autoFile)]) {
      try {
        if (f.existsSync()) f.deleteSync();
      } catch (_) {}
    }
  }

  /// При запуске: осталась резервная копия (программа закрылась, не сохранив правки)?
  Future<bool> _offerRestore() async {
    Map<String, dynamic> meta;
    try {
      if (!_autoMeta.existsSync() || !File(_autoFile).existsSync()) return false;
      meta = (jsonDecode(_autoMeta.readAsStringSync()) as Map).cast<String, dynamic>();
    } catch (_) {
      _clearAutosave();
      return false;
    }
    if (!mounted) return false;
    final when = DateTime.tryParse('${meta['saved']}');
    final t = Tok.of(context);
    final v = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (c) => AlertDialog(
        shape: RoundedRectangleBorder(side: BorderSide(color: t.line)),
        backgroundColor: t.panel,
        title: Text('Восстановить работу?', style: TextStyle(fontSize: 15, color: t.text)),
        content: Text(
          'Программа закрылась, не сохранив правки в «${meta['name']}».'
          '${when == null ? '' : ' Резервная копия: ${_hhmm(when)}.'}',
          style: TextStyle(fontSize: 13, color: t.muted),
        ),
        actions: [
          _TextBtn('Удалить копию', null, () => Navigator.pop(c, false), outlined: true),
          _PrimaryBtn('Восстановить', () => Navigator.pop(c, true)),
        ],
      ),
    );
    if (v != true) {
      _clearAutosave();
      return false;
    }
    final res = await _run(
      'Восстановление…',
      () => _backend.call('restore', {'path': _autoFile, 'project_path': meta['project'], 'origin': meta['origin']}),
    );
    if (res == null) return false;
    _path = (meta['project'] ?? meta['origin']) as String?;
    _apply(res);
    _syncSettings();
    setState(() => _dirty = true);
    _say('Работа восстановлена – не забудьте сохранить (Ctrl+S)');
    return true;
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
    if (!await _confirmDiscard()) return;
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

  void _apply(Map<String, dynamic>? res, {bool keepSelection = false}) {
    if (res == null) return;
    setState(() {
      // сведения об исходнике приходят только при загрузке – потом переносим старые
      final src = (res['source'] as Map?)?.cast<String, dynamic>() ?? _scene?.source;
      _scene = Scene.fromJson(res, source: src);
      if (!keepSelection) _selected = null;
    });
  }

  Future<void> _open() async {
    if (!await _confirmDiscard()) return;
    final f = pickOpen();
    if (f != null) await _load(f);
  }

  Future<void> _openRecent(RecentItem it) async {
    if (!it.exists) {
      setState(() => _recent = Recent.remove(it.path));
      _say('Файл не найден: ${it.name}', error: true);
      return;
    }
    if (!await _confirmDiscard()) return;
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
      _clearAutosave();
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
    final r = await _run('Сохранение…', () => _backend.call('save_project', {'path': target}));
    if (r == null) return false;
    setState(() {
      _scene!.source = (r['source'] as Map).cast<String, dynamic>();
      _path = target;
      _dirty = false;
    });
    _clearAutosave();
    await _remember(target, project: true, replaces: old == null ? src['path'] as String? : null);
    _say('Работа сохранена: ${target.split(Platform.pathSeparator).last}');
    return true;
  }

  /// В список недавних + миниатюра.
  Future<void> _remember(String path, {required bool project, String? replaces}) async {
    final thumb = Recent.thumbFor(path);
    try {
      await _backend.call('thumb', {'path': thumb});
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

  Future<void> _load(String path) async {
    final project = path.toLowerCase().endsWith('.stj');
    final res = await _run(
      project ? 'Открываю работу…' : 'Распознаю схему…',
      () => _backend.call('load', {
        'path': path,
        // у работы свои настройки листа и направления – берём из файла
        if (!project) 'sheets': _twoSheets ? _fmt : null,
        if (!project) 'odd_right': _oddRight,
        'layers': _layers,
      }),
    );
    if (res == null) return;
    _path = path;
    _apply(res);
    _syncSettings();
    setState(() => _dirty = false);
    _clearAutosave();
    await _remember(path, project: project);
  }

  Future<void> _relayout() async {
    if (_path == null) return;
    final hadEdits = _scene?.source?['edited'] == true;
    final res = await _run(
      'Перекомпоновка…',
      () => _backend.call('relayout', {'sheets': _twoSheets ? _fmt : null, 'odd_right': _oddRight}),
    );
    _apply(res);
    if (res != null) setState(() => _dirty = true);
    if (res != null && hadEdits) _say('Стыки расставлены по правилам заново – ручные правки сброшены');
  }

  Future<void> _setLayer(String k, bool v) async {
    setState(() => _layers[k] = v);
    if (_scene == null) return;
    if (k == 'grid') return; // сетку рисует клиент
    _apply(
      await _backend.call('scene', {
        'layers': {k: v},
      }),
      keepSelection: true,
    );
  }

  Future<void> _undo() async {
    if (_scene?.undo == null || _busy) return;
    final res = await _backend.call('undo');
    _apply(res);
    _syncSettings();
    setState(() => _dirty = true);
    _say('Отменено: ${res['done']}');
  }

  Future<void> _redo() async {
    if (_scene?.redo == null || _busy) return;
    final res = await _backend.call('redo');
    _apply(res);
    _syncSettings();
    setState(() => _dirty = true);
    _say('Повторено: ${res['done']}');
  }

  Future<void> _recompute() async {
    if (_scene == null) return;
    _apply(await _run('Расстановка…', () => _backend.call('recompute')));
    _dirty = true;
    _say('Стыки и светофоры расставлены заново');
  }

  Future<void> _addJoint(EdgeHit h) async {
    _apply(await _backend.call('add_joint', {'edge': h.e.id, 't': h.t}));
    _dirty = true;
    _say('Стык добавлен');
  }

  Future<void> _removeJoint(JointObj j) async {
    _apply(await _backend.call('remove_joint', {'joint': j.id}));
    _dirty = true;
    _say('Стык удалён');
  }

  Future<void> _toggleNegab(JointObj j) async {
    final res = await _backend.call('toggle_negab', {'joint': j.id});
    _apply(res);
    _dirty = true;
    final nj = _scene!.joints.firstWhere((x) => x.id == j.id, orElse: () => j);
    setState(() => _selected = JointHit(nj));
    _say(nj.negab ? 'Стык негабаритный' : 'Стык габаритный');
  }

  String get _base {
    final src = _scene?.source;
    final n = (src?['project'] as String?)?.split(Platform.pathSeparator).last ?? src?['name'] as String? ?? 'схема';
    final i = n.lastIndexOf('.');
    return i > 0 ? n.substring(0, i) : n;
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
    final r = await _run('Сохранение…', () => _backend.call(cmd, {'path': path, 'title': _base}));
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
    final ctrl = HardwareKeyboard.instance.isControlPressed;
    final shift = HardwareKeyboard.instance.isShiftPressed;
    final k = e.logicalKey;
    if (ctrl && k == LogicalKeyboardKey.keyO) {
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

  // ------------------------------------------------------------------ разметка
  @override
  Widget build(BuildContext context) {
    final t = Tok.of(context);
    if (_fatal != null) return _FatalScreen(text: _fatal!);
    return Focus(
      focusNode: _focus,
      autofocus: true,
      onKeyEvent: _onKey,
      child: Scaffold(
        body: Column(
          children: [
            _toolbar(t),
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

  Widget _canvas(Tok t) {
    return Container(
      decoration: BoxDecoration(
        border: Border.symmetric(vertical: BorderSide(color: t.line)),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: SchemeView(
              scene: _scene,
              grid: _layers['grid']!,
              tool: _tool,
              selected: _selected,
              controller: _cam,
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
          kv('Тип', g.kind),
          kv('Ордината', '${g.ordinate} мм', monoV: true),
          kv('Основание', g.why),
        ],
      );
    }
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Text(
        _scene == null
            ? 'Нет схемы'
            : 'Ничего не выбрано.\n\nКлик по стыку или светофору – свойства.\n'
                  'J – инструмент «Стык»: клик по пути ставит стык.\n'
                  'Del – удалить выбранный стык, N – габарит/негабарит.',
        style: TextStyle(fontSize: 12, height: 1.5, color: t.muted),
      ),
    );
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
              Text(key_!, style: TextStyle(fontSize: 11, fontFamily: mono, color: t.muted)),
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
