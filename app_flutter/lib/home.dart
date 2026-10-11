import 'dart:async';
import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'autosave.dart';
import 'backend.dart';
import 'document.dart';
import 'file_dialog.dart';
import 'recent.dart';
import 'scene.dart';
import 'scheme_view.dart';
import 'theme.dart';
import 'ui/controls.dart';
import 'ui/dialogs.dart';
import 'ui/doc_tabs.dart';
import 'ui/lists.dart';
import 'ui/menus.dart';
import 'ui/properties.dart';
import 'ui/status_bar.dart';
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

enum _Panel { props, signals, sections, routes }

const _panelNames = {
  _Panel.props: 'Свойства',
  _Panel.signals: 'Светофоры',
  _Panel.sections: 'Участки',
  _Panel.routes: 'Маршруты',
};

/// Главный экран: табы открытых схем, холст, панели. Здесь – только оркестрация:
/// команды бэкенду, выделение, горячие клавиши; виджеты панелей – в ui/.
class Home extends StatefulWidget {
  final VoidCallback onToggleTheme;
  final String? initialPath;
  const Home({super.key, required this.onToggleTheme, this.initialPath});

  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> implements SchemeActions {
  final _backend = Backend();
  final _autosaves = AutosaveStore();
  final _focus = FocusNode();
  final _hover = ValueNotifier<HoverInfo>((hit: null, ordinate: null));

  bool _ready = false;
  String? _fatal;
  bool _busy = false;
  String _busyText = '';

  final _docs = <Doc>[];
  Doc? _doc; // активный таб
  final _noCam = SchemeController(); // холст без схемы
  Doc? _renaming; // таб, имя которого сейчас редактируется

  bool _explain = false; // режим «Объясни»
  String? _explainKey; // что сейчас объяснено (объект + версия сцены)
  Map<String, dynamic>? _explainData;

  Scene? get _scene => _doc?.scene;
  Hit? get _selected => _doc?.selected;
  SchemeController get _cam => _doc?.cam ?? _noCam;

  Tool _tool = Tool.select;
  _Panel _panel = _Panel.props;
  bool _trainRoutes = true; // вкладка «Маршруты»: поездные или маневровые
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
  bool _autosaving = false;
  late final AppLifecycleListener _life;
  Release? _update; // найденная новая версия
  String? _pendingOpen; // файл от повторного запуска, пришедший, пока движок занят
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

  @override
  void dispose() {
    _life.dispose();
    _instance.setMethodCallHandler(null);
    _autosaveTimer?.cancel();
    _backend.dispose();
    _toastTimer?.cancel();
    _hover.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      await _backend.start();
      await _backend.call('ping');
      setState(() => _ready = true);
      final restored = await _offerRestore();
      final p = widget.initialPath;
      if (!restored && p != null && File(p).existsSync()) await _load(p);
      await _openPending();
    } catch (e) {
      setState(() => _fatal = '$e\n\n${_backend.stderrTail}');
    }
    unawaited(_checkUpdate());
  }

  Future<void> _openExternal(String path) async {
    if (path.isEmpty) return;
    if (!_ready || _busy) {
      _pendingOpen = path; // откроем, как только движок освободится
      return;
    }
    if (!File(path).existsSync()) {
      _say('Файл не найден: $path', error: true);
      return;
    }
    await _load(path);
  }

  Future<void> _openPending() async {
    final p = _pendingOpen;
    _pendingOpen = null;
    if (p != null) await _openExternal(p);
  }

  // ------------------------------------------------------------------ табы
  /// Команда бэкенду для документа (по умолчанию – активного таба).
  Future<Map<String, dynamic>> _call(String cmd, [Map<String, dynamic>? args, Doc? doc]) =>
      _backend.call(cmd, {...?args, 'doc': (doc ?? _doc)!.id});

  Future<Doc> _newDoc() async {
    final r = await _backend.call('new_doc');
    final d = Doc(r['doc'] as int);
    setState(() => _docs.add(d));
    return d;
  }

  Doc? _findOpen(String path) {
    final key = path.toLowerCase();
    for (final d in _docs) {
      final paths = [d.path, d.project, d.source?['path']];
      if (paths.any((p) => p is String && p.toLowerCase() == key)) return d;
    }
    return null;
  }

  Future<void> _activate(Doc? d) async {
    if (_busy && d != _doc) return; // пока идёт операция – не переключаемся
    setState(() => _doc = d);
    _hover.value = (hit: null, ordinate: null);
    if (d == null) return;
    _syncSettings();
    _syncExplain();
    if (d.layersStale && d.scene != null) {
      d.layersStale = false;
      final lay = Map.of(_layers)..remove('grid');
      try {
        _apply(await _call('scene', {'layers': lay}, d), keepSelection: true, doc: d);
      } catch (e) {
        _say('Ошибка: $e', error: true);
      }
    }
  }

  void _cycleTab(int step) {
    if (_docs.length < 2 || _doc == null) return;
    final i = _docs.indexOf(_doc!);
    _activate(_docs[(i + step) % _docs.length]);
  }

  /// Убрать таб (без вопросов): бэкенд забывает документ, активным становится сосед.
  Future<void> _dropDoc(Doc d, {Doc? fallback}) async {
    final i = _docs.indexOf(d);
    if (i < 0) return;
    _autosaves.drop(d.id);
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
  Future<void> _closeTab(Doc d) async {
    if (_busy) return;
    if (d.dirty) {
      await _activate(d);
      if (!await _confirmDiscard()) return;
    }
    await _dropDoc(d);
  }

  // ------------------------------------------------------------------ переименование
  Future<void> _startRename(Doc d) async {
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
  Future<void> _commitRename(Doc d, String raw) async {
    if (!identical(_renaming, d)) return;
    _endRename();
    var name = raw.trim().replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_');
    if (name.toLowerCase().endsWith('.stj')) name = name.substring(0, name.length - 4).trim();
    if (name.isEmpty || name == _baseOf(d)) return;
    final project = d.project;
    if (project == null) {
      setState(() => d.name = name);
      _say('Имя «$name» – будет предложено при сохранении (Ctrl+S)');
      return;
    }
    final sep = Platform.pathSeparator;
    final target = '${project.substring(0, project.lastIndexOf(sep))}$sep$name.stj';
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

  Future<void> _tabMenu(Doc d, Offset global) async {
    final v = await showAppMenu<String>(context, global, [
      menuItem(context, 'rename', 'Переименовать', 'F2', enabled: d.scene != null),
      menuItem(context, 'close', 'Закрыть', 'Ctrl+W'),
      menuItem(context, 'others', 'Закрыть остальные', '', enabled: _docs.length > 1),
    ]);
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

  String _baseOf(Doc? d) {
    if (d?.name != null) return d!.name!;
    final n =
        d?.project?.split(Platform.pathSeparator).last ??
        d?.source?['name'] as String? ??
        d?.path?.split(Platform.pathSeparator).last ??
        'схема';
    final i = n.lastIndexOf('.');
    return i > 0 ? n.substring(0, i) : n;
  }

  String get _base => _baseOf(_doc);

  String _tabTitle(Doc d) {
    if (d.name != null) return d.name!;
    if (d.project != null) return '${_baseOf(d)}.stj';
    return (d.source?['name'] as String?) ?? d.path?.split(Platform.pathSeparator).last ?? 'схема';
  }

  Future<AppExitResponse> _onExitRequested() async {
    if (!await _confirmAll()) return AppExitResponse.cancel;
    _autosaves.clear();
    return AppExitResponse.exit;
  }

  // ------------------------------------------------------------------ автосохранение
  /// Раз в 30 с – резервные копии всех табов с несохранёнными правками.
  Future<void> _autosave() async {
    if (_busy || _autosaving) return;
    if (!_docs.any((d) => d.dirty) && !_autosaves.exists) return;
    _autosaving = true;
    try {
      final entries = <AutosaveEntry>[];
      for (final d in List.of(_docs)) {
        if (!d.dirty || d.scene == null) continue;
        final file = _autosaves.fileFor(d.id);
        await _call('save_project', {'path': file, 'autosave': true}, d);
        entries.add(
          AutosaveEntry(
            file: file,
            project: d.project,
            origin: d.project == null ? d.path : null,
            name: _baseOf(d),
            saved: DateTime.now(),
          ),
        );
      }
      _autosaves.write(entries);
    } catch (_) {
      // резервная копия – не критично
    } finally {
      _autosaving = false;
    }
  }

  /// При запуске: остались резервные копии (программа закрылась, не сохранив правки)?
  Future<bool> _offerRestore() async {
    final entries = _autosaves.pending();
    if (entries.isEmpty) {
      _autosaves.clear();
      return false;
    }
    if (!mounted || !await askRestore(context, entries)) {
      _autosaves.clear();
      return false;
    }
    var any = false;
    for (final e in entries) {
      final d = await _newDoc();
      await _activate(d);
      final res = await _run(
        'Восстановление…',
        () => _call('restore', {'path': e.file, 'project_path': e.project, 'origin': e.origin}, d),
      );
      if (res == null) {
        await _dropDoc(d);
        continue;
      }
      d.path = e.project ?? e.origin;
      _apply(res, doc: d);
      _syncSettings();
      any = true;
    }
    if (any) _say('Работа восстановлена – не забудьте сохранить (Ctrl+S)');
    return any;
  }

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
    final choice = await askUpdate(context, r);
    switch (choice) {
      case UpdateChoice.page:
        openUrl(r.page);
      case UpdateChoice.install:
        await _install(r);
      case UpdateChoice.later:
        break;
    }
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
    _autosaves.clear();
    _backend.dispose();
    exit(0);
  }

  // ------------------------------------------------------------------ действия
  /// Долгая операция: полоса прогресса, ошибка – сообщением, после – отложенное открытие.
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
      if (_pendingOpen != null) scheduleMicrotask(_openPending);
    }
  }

  void _say(String text, {bool error = false}) {
    _toastTimer?.cancel();
    setState(() => _toast = text);
    _toastTimer = Timer(Duration(milliseconds: error ? 5000 : 2200), () {
      if (mounted) setState(() => _toast = null);
    });
  }

  /// Новая сцена от бэкенда: сведения об исходнике переносятся, «не сохранено» –
  /// как решил бэкенд (он помнит, какой шаг истории совпадает с файлом).
  void _apply(Map<String, dynamic>? res, {bool keepSelection = false, Doc? doc}) {
    final d = doc ?? _doc;
    if (res == null || d == null) return;
    setState(() {
      final src = (res['source'] as Map?)?.cast<String, dynamic>() ?? d.scene?.source;
      d.scene = Scene.fromJson(res, source: src);
      d.dirty = d.scene!.dirty ?? d.dirty;
      if (!keepSelection) d.selected = null;
    });
    if (identical(d, _doc)) _syncExplain();
  }

  void _select(Hit? h, {_Panel? panel}) {
    setState(() {
      _doc?.selected = h;
      if (panel != null) _panel = panel;
    });
    _syncExplain();
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
    final d = _doc;
    if (d == null || !d.dirty || d.scene == null) return true;
    switch (await askSaveChanges(context, _base)) {
      case SaveChoice.discard:
        _autosaves.drop(d.id);
        return true;
      case SaveChoice.save:
        return await _save();
      case SaveChoice.cancel:
        return false;
    }
  }

  /// Сохранить работу (.stj). Возвращает true, если сохранено.
  Future<bool> _save({bool as = false}) async {
    final d = _doc;
    if (d == null || d.scene == null || _busy) return false;
    final old = d.project;
    var path = as ? null : old;
    if (path == null) {
      final picked = pickSave('$_base.stj', 'Работа «Стыки»', 'stj');
      if (picked == null) return false;
      path = picked.toLowerCase().endsWith('.stj') ? picked : '$picked.stj';
    }
    final target = path;
    final r = await _run('Сохранение…', () => _call('save_project', {'path': target}, d));
    if (r == null) return false;
    final replaces = old == null ? (d.source?['path'] as String?) : null;
    setState(() {
      d.scene!.source = (r['source'] as Map).cast<String, dynamic>();
      d.path = target;
      d.dirty = (r['history'] as Map?)?['dirty'] as bool? ?? false;
    });
    _autosaves.drop(d.id);
    await _remember(target, project: true, replaces: replaces, doc: d);
    _say('Работа сохранена: ${target.split(Platform.pathSeparator).last}');
    return true;
  }

  /// В список недавних + миниатюра.
  Future<void> _remember(String path, {required bool project, String? replaces, Doc? doc}) async {
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
    if (_busy) {
      _pendingOpen = path;
      _say('Откроется после текущей операции');
      return;
    }
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
    await _remember(path, project: project, doc: d);
  }

  /// Правка схемы: одна операция за раз (номера стыков и светофоров в запросе – из
  /// текущей сцены, двойное нажатие не должно попасть в соседний объект), ошибка –
  /// сообщением, результат – новая сцена.
  Future<Map<String, dynamic>?> _edit(String cmd, Map<String, dynamic> args, {String? ok, String busy = 'Пересчёт…'}) async {
    if (_scene == null || _busy) return null;
    if (_renaming == null) _focus.requestFocus(); // горячие клавиши – снова к схеме
    final res = await _run(busy, () => _call(cmd, args));
    if (res == null) return null;
    _apply(res);
    if (ok != null) _say(ok);
    return res;
  }

  Future<void> _relayout() async {
    final res = await _edit('relayout', {'sheets': _twoSheets ? _fmt : null, 'odd_right': _oddRight}, busy: 'Перекомпоновка…');
    if (res == null) {
      _syncSettings(); // не получилось – переключатели как у схемы
      return;
    }
    final kept = (res['kept'] as int?) ?? 0;
    if (kept > 0) _say('Ручные правки стыков перенесены ($kept)');
  }

  Future<void> _setLayer(String k, bool v) async {
    setState(() => _layers[k] = v);
    if (_scene == null || k == 'grid') return; // сетку рисует клиент
    for (final d in _docs) {
      if (!identical(d, _doc)) d.layersStale = true; // обновятся при переключении
    }
    try {
      _apply(
        await _call('scene', {
          'layers': {k: v},
        }),
        keepSelection: true,
      );
    } catch (e) {
      _say('Ошибка: $e', error: true);
    }
  }

  Future<void> _undo() async {
    if (_scene?.undo == null) return;
    final res = await _edit('undo', {}, busy: 'Отмена…');
    if (res == null) return;
    _syncSettings();
    _say('Отменено: ${res['done']}');
  }

  Future<void> _redo() async {
    if (_scene?.redo == null) return;
    final res = await _edit('redo', {}, busy: 'Повтор…');
    if (res == null) return;
    _syncSettings();
    _say('Повторено: ${res['done']}');
  }

  Future<void> _recompute() => _edit('recompute', {}, ok: 'Стыки и светофоры расставлены заново', busy: 'Расстановка…');

  Future<void> _addJoint(EdgeHit h) => _edit('add_joint', {'edge': h.e.id, 't': h.t}, ok: 'Стык добавлен');

  Future<void> _moveJoint(JointObj j, double t) async {
    if (await _edit('move_joint', {'joint': j.id, 't': t}, ok: 'Стык перенесён') == null) return;
    final nj = _scene!.joints.where((x) => x.id == j.id).firstOrNull;
    if (nj != null) _select(JointHit(nj));
  }

  Future<void> _addSegment(Map<String, dynamic> a, Map<String, dynamic> b) =>
      _edit('edit_track', {'op': 'add_edge', 'a': a, 'b': b}, ok: 'Отрезок добавлен – схема перестроена');

  /// После пересчёта номера светофоров меняются – выбрать тот же по стыку и направлению.
  void _reselectSignal(int joint, int toward) {
    final g = _scene?.signals.where((x) => x.joint == joint && x.toward == toward).firstOrNull;
    if (g != null) _select(SignalHit(g), panel: _Panel.props);
  }

  // --- SchemeActions: правки из панели свойств и контекстных меню -----------------
  @override
  Future<void> toggleNegab(JointObj j) async {
    if (await _edit('toggle_negab', {'joint': j.id}) == null) return;
    final nj = _scene!.joints.where((x) => x.id == j.id).firstOrNull;
    if (nj == null) return;
    _select(JointHit(nj));
    _say(nj.negab ? 'Стык негабаритный' : 'Стык габаритный');
  }

  @override
  Future<void> removeJoint(JointObj j) => _edit('remove_joint', {'joint': j.id}, ok: 'Стык удалён');

  @override
  Future<void> addSignal(JointObj j, int toward) async {
    if (await _edit('add_signal', {'joint': j.id, 'toward': toward}, ok: 'Светофор добавлен – задайте имя и тип') == null) {
      return;
    }
    _reselectSignal(j.id, toward);
  }

  @override
  Future<void> setEnd(NodeObj n, String mark) =>
      _edit('edit_track', {'op': 'set_end', 'node': n.id, 'mark': mark}, ok: 'Конец пути: ${endKinds[mark]}');

  @override
  Future<void> deleteChain(EdgeHit h) =>
      _edit('edit_track', {'op': 'delete_edge', 'edge': h.e.id}, ok: 'Отрезок удалён – схема перестроена');

  Future<void> _editSignal(SignalObj g, Map<String, dynamic> change, String ok, {bool reselect = true}) async {
    if (await _edit('edit_signal', {'signal': g.id, ...change}, ok: ok) == null) return;
    if (reselect) _reselectSignal(g.joint, g.toward);
  }

  @override
  Future<void> renameSignal(SignalObj s, String name) => _editSignal(s, {'name': name}, 'Светофор изменён');

  @override
  Future<void> setSignalKind(SignalObj s, String kind) => _editSignal(s, {'kind': kind}, 'Светофор изменён');

  @override
  Future<void> deleteSignal(SignalObj s) =>
      _editSignal(s, {'delete': true}, 'Светофор ${s.name} удалён', reselect: false);

  @override
  Future<void> resetSignal(SignalObj s) async {
    if (await _edit('reset_signal', {'signal': s.id}, ok: 'Светофор – как по правилам') == null) return;
    _reselectSignal(s.joint, s.toward);
  }

  // --- меню на схеме --------------------------------------------------------------
  Future<void> _nodeMenu(Offset global, NodeObj n) async {
    final t = Tok.of(context);
    final v = await showAppMenu<String>(context, global, [
      const PopupMenuItem<String>(enabled: false, height: 26, child: Caption('Тип конца пути')),
      for (final e in endKinds.entries)
        PopupMenuItem<String>(
          value: e.key,
          height: 32,
          child: Row(
            children: [
              SizedBox(width: 20, child: n.mark == e.key ? Icon(Icons.check, size: 15, color: t.accent) : null),
              Text(capitalize(e.value), style: TextStyle(fontSize: 13, color: t.text)),
            ],
          ),
        ),
    ]);
    if (v != null && v != n.mark) await setEnd(n, v);
  }

  /// ПКМ по стыку или светофору.
  Future<void> _contextMenu(Offset global, Hit h) async {
    switch (h) {
      case JointHit(:final j):
        final v = await showAppMenu<String>(context, global, [
          menuItem(context, 'negab', j.negab ? 'Сделать габаритным' : 'Сделать негабаритным', 'N'),
          menuItem(context, 'explain', 'Объяснить', 'F1'),
          menuItem(context, 'del', 'Удалить стык', 'Del'),
        ]);
        if (v == 'negab') await toggleNegab(j);
        if (v == 'del') await removeJoint(j);
        if (v == 'explain' && !_explain) _toggleExplain();
      case SignalHit(:final s):
        final v = await showAppMenu<String>(context, global, [
          menuItem(context, 'props', 'Имя и тип…', ''),
          menuItem(context, 'explain', 'Объяснить', 'F1'),
          if (s.manual) menuItem(context, 'reset', 'Как по правилам', ''),
          menuItem(context, 'del', 'Удалить светофор', 'Del'),
        ]);
        if (v == 'props') setState(() => _panel = _Panel.props);
        if (v == 'reset') await resetSignal(s);
        if (v == 'del') await deleteSignal(s);
        if (v == 'explain' && !_explain) _toggleExplain();
      default:
        break;
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
    if (!_explain || _doc == null) return;
    final what = _hitKey(_selected);
    final key = what == null ? null : '$what@${identityHashCode(_scene)}';
    if (key == _explainKey) return;
    setState(() {
      _explainKey = key;
      _explainData = null; // выбрали другое – не показываем объяснение прошлого
    });
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

  void _toggleExplain() {
    setState(() {
      _explain = !_explain;
      _explainKey = null;
      _explainData = null;
      if (_explain) {
        _right = true; // объяснение – в правой панели
        _panel = _Panel.props;
      }
    });
    _syncExplain();
  }

  Future<void> _export(ExportKind kind) async {
    if (_scene == null || _busy) return;
    final (ext, label, suffix, cmd) = switch (kind) {
      ExportKind.png => ('png', 'PNG', '_стыки', 'export_png'),
      ExportKind.pdf => ('pdf', 'PDF', '_листы', 'export_pdf'),
      ExportKind.docx => ('docx', 'Документ Word', '_ведомость', 'export_docx'),
    };
    final picked = pickSave('$_base$suffix.$ext', label, ext);
    if (picked == null) return;
    final path = picked.toLowerCase().endsWith('.$ext') ? picked : '$picked.$ext';
    final r = await _run('Сохранение…', () => _call(cmd, {'path': path, 'title': _base}));
    if (r != null) _say('Сохранено: ${path.split(Platform.pathSeparator).last}');
  }

  void _selectSignal(SignalObj s) {
    _select(SignalHit(s)); // остаёмся в списке – удобно листать
    _cam.focus(s.box);
  }

  void _selectSection(SectionObj s) {
    _select(SectionHit(s));
    _cam.focus(s.box);
  }

  void _selectRoute(RouteObj r) {
    _select(RouteHit(r));
    _cam.focus(r.box);
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
    final has = _scene != null;
    final del = k == LogicalKeyboardKey.delete || k == LogicalKeyboardKey.backspace;
    final sel = _selected;
    if (k == LogicalKeyboardKey.f1) {
      if (has) _toggleExplain();
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
      _export(ExportKind.png);
    } else if (ctrl && k == LogicalKeyboardKey.keyP) {
      _export(ExportKind.pdf);
    } else if (ctrl && k == LogicalKeyboardKey.keyR) {
      _recompute();
    } else if (ctrl) {
      return KeyEventResult.ignored;
    } else if (k == LogicalKeyboardKey.keyV) {
      setState(() => _tool = Tool.select);
    } else if (k == LogicalKeyboardKey.keyJ) {
      if (has) setState(() => _tool = Tool.joint);
    } else if (k == LogicalKeyboardKey.keyT) {
      if (has) setState(() => _tool = Tool.track);
    } else if (k == LogicalKeyboardKey.escape) {
      setState(() => _tool = Tool.select);
      _select(null);
    } else if (del && sel is JointHit) {
      removeJoint(sel.j);
    } else if (del && sel is SignalHit) {
      deleteSignal(sel.s);
    } else if (del && sel is EdgeHit && _tool == Tool.track) {
      deleteChain(sel);
    } else if (k == LogicalKeyboardKey.keyN && sel is JointHit) {
      toggleNegab(sel.j);
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
    if (_fatal != null) return FatalScreen(text: _fatal!);
    _syncTitle();
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
            StatusBar(hover: _hover, scene: _scene, tool: _tool, ready: _ready),
          ],
        ),
      ),
    );
  }

  Widget _toolbar(Tok t) {
    final has = _scene != null;
    final s = _scene;
    return Container(
      height: 40,
      color: t.panel,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          IconBtn(Icons.view_sidebar_outlined, 'Левая панель', () => setState(() => _left = !_left), active: _left, flip: true),
          const Sep(),
          FileMenu(
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
          const Sep(),
          IconBtn(
            Icons.undo,
            s?.undo == null ? 'Отменить (Ctrl+Z)' : 'Отменить: ${s!.undo} (Ctrl+Z)',
            s?.undo == null || _busy ? null : _undo,
          ),
          IconBtn(
            Icons.redo,
            s?.redo == null ? 'Повторить (Ctrl+Y)' : 'Повторить: ${s!.redo} (Ctrl+Y)',
            s?.redo == null || _busy ? null : _redo,
          ),
          const Sep(),
          ToolBtn(Icons.near_me_outlined, 'Выбор', 'V', _tool == Tool.select, () => setState(() => _tool = Tool.select)),
          ToolBtn(Icons.add_road, 'Стык', 'J', _tool == Tool.joint, has ? () => setState(() => _tool = Tool.joint) : null),
          ToolBtn(Icons.timeline, 'Пути', 'T', _tool == Tool.track, has ? () => setState(() => _tool = Tool.track) : null),
          const Sep(),
          ToolBtn(Icons.school_outlined, 'Объясни', 'F1', _explain, has ? _toggleExplain : null),
          const Sep(),
          TextBtn('Расставить заново', 'Ctrl+R', has && !_busy ? _recompute : null),
          const Spacer(),
          if (_update != null) ...[
            _UpdateChip(version: _update!.version, onTap: _showUpdate),
            const SizedBox(width: 8),
          ],
          ExportMenu(enabled: has && !_busy, onPick: _export),
          const SizedBox(width: 4),
          IconBtn(
            Theme.of(context).brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
            'Тема',
            widget.onToggleTheme,
          ),
          if (has) IconBtn(Icons.view_sidebar_outlined, 'Правая панель', () => setState(() => _right = !_right), active: _right),
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
                    DocTab(
                      title: _tabTitle(d),
                      tooltip: d.project ?? d.path ?? '',
                      project: d.project != null || (d.path?.toLowerCase().endsWith('.stj') ?? false),
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
          IconBtn(Icons.add, 'Открыть в новом табе (Ctrl+O)', _ready && !_busy ? _open : null, size: 32),
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
          if (_scene == null) Positioned.fill(child: _startScreen(t)),
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

  Widget _schemeView(Doc? d) {
    return SchemeView(
      key: ValueKey(d?.id ?? 0),
      scene: d?.scene,
      grid: _layers['grid']!,
      tool: _tool,
      selected: d?.selected,
      controller: d?.cam ?? _noCam,
      onSelect: (h) => _select(h, panel: h == null ? null : _Panel.props),
      onAddJoint: _addJoint,
      onHover: (h, ord) => _hover.value = (hit: h, ordinate: ord),
      onContext: _contextMenu,
      onMoveJoint: _moveJoint,
      onAddSegment: _addSegment,
      onNodeMenu: _nodeMenu,
    );
  }

  Widget _startScreen(Tok t) {
    return ColoredBox(
      color: t.bg,
      child: Center(
        child: SizedBox(
          width: 3 * 196 + 20,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Схема станции', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: t.text)),
              const SizedBox(height: 8),
              Text(
                _busy
                    ? _busyText
                    : 'Откройте фото или скан однониточной схемы из задания. '
                          'Программа перечертит её на миллиметровке, расставит '
                          'изолирующие стыки и светофоры по методичке и составит таблицы маршрутов.',
                style: TextStyle(fontSize: 13, height: 1.45, color: t.muted),
              ),
              const SizedBox(height: 18),
              if (!_busy)
                Row(
                  children: [
                    PrimaryBtn('Открыть схему…', _ready ? _open : null),
                    const SizedBox(width: 8),
                    TextBtn('Пример', null, _ready ? _openSample : null, outlined: true),
                  ],
                ),
              if (!_ready) ...[
                const SizedBox(height: 12),
                Text('Запуск движка…', style: TextStyle(fontSize: 12, color: t.muted)),
              ],
              if (!_busy && _recent.isNotEmpty) ...[
                const SizedBox(height: 28),
                const Caption('Недавние'),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final it in _recent.take(6)) RecentCard(it: it, onTap: _ready ? () => _openRecent(it) : null),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  /// Масштаб: слушает камеру сам – при зуме и сдвиге не перестраивается весь экран.
  Widget _zoomBox(Tok t) {
    final cam = _cam;
    return Container(
      height: 28,
      decoration: BoxDecoration(
        color: t.panel,
        border: Border.all(color: t.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconBtn(Icons.remove, 'Отдалить (−)', () => cam.zoomBy(1 / 1.4), size: 26),
          SizedBox(
            width: 52,
            child: ListenableBuilder(
              listenable: cam,
              builder: (_, _) => Text(
                '${cam.zoomPercent.round()}%',
                textAlign: TextAlign.center,
                style: TextStyle(fontFamily: mono, fontSize: 12, color: t.text),
              ),
            ),
          ),
          IconBtn(Icons.add, 'Приблизить (+)', () => cam.zoomBy(1.4), size: 26),
          Container(width: 1, height: 16, color: t.line),
          IconBtn(Icons.fit_screen_outlined, 'Вписать (0)', cam.fit, size: 26),
        ],
      ),
    );
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
          PanelSection(
            'Исходник',
            trailing: IconBtn(Icons.folder_open_outlined, 'Открыть другую схему (Ctrl+O)', _ready ? _open : null, size: 24),
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
                    if (_doc?.dirty ?? false)
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
            PanelSection(
              'Лист',
              children: [
                CheckRow('Два листа (горловины раздельно)', _twoSheets, _busy
                    ? null
                    : (v) {
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
                          child: SegButton(
                            f,
                            _fmt == f,
                            _twoSheets && !_busy && _fmt != f
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
            PanelSection(
              'Движение',
              children: [
                Text('Нечётная горловина', style: TextStyle(fontSize: 12, color: t.muted)),
                const SizedBox(height: 6),
                Row(
                  children: [
                    for (final (label, right) in const [('Слева', false), ('Справа', true)])
                      Expanded(
                        child: SegButton(
                          label,
                          _oddRight == right,
                          _oddRight == right || _busy
                              ? null
                              : () {
                                  setState(() => _oddRight = right);
                                  _relayout();
                                },
                          monoFont: false,
                        ),
                      ),
                  ],
                ),
              ],
            ),
            PanelSection(
              'Слои',
              children: [for (final e in _layerNames.entries) CheckRow(e.value, _layers[e.key]!, (v) => _setLayer(e.key, v))],
            ),
          ],
        ],
      ),
    );
  }

  Widget _rightPanel(Tok t) {
    return Container(
      width: 352,
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
                for (final p in _Panel.values)
                  Expanded(child: TabButton(_panelNames[p]!, _panel == p, () => setState(() => _panel = p))),
              ],
            ),
          ),
          if (_explain && _scene != null)
            ExplainCard(data: _explainData, hasSelection: _selected != null, onClose: _toggleExplain),
          Expanded(
            child: switch (_panel) {
              _Panel.props => PropertiesPanel(scene: _scene, selected: _selected, actions: this),
              _Panel.signals => _signals(),
              _Panel.sections => _sections(),
              _Panel.routes => _routes(t),
            },
          ),
        ],
      ),
    );
  }

  Widget _signals() {
    final list = _scene?.signals ?? const <SignalObj>[];
    final sel = _selected is SignalHit ? (_selected as SignalHit).s.id : -1;
    return ListView.builder(
      itemCount: list.length,
      itemExtent: 44,
      itemBuilder: (c, i) => SignalRow(s: list[i], selected: list[i].id == sel, onTap: () => _selectSignal(list[i])),
    );
  }

  /// Строки списка с заголовками групп (группа меняется – вставляется заголовок).
  static List<Object> _grouped<T>(List<T> items, String Function(T) group) {
    final rows = <Object>[];
    String? current;
    for (final it in items) {
      final g = group(it);
      if (g != current) rows.add(current = g);
      rows.add(it as Object);
    }
    return rows;
  }

  Widget _sections() {
    final rows = _grouped(_scene?.sections ?? const <SectionObj>[], (s) => s.throat);
    final sel = _selected is SectionHit ? (_selected as SectionHit).sec.id : -1;
    return ListView.builder(
      itemCount: rows.length,
      itemBuilder: (c, i) => switch (rows[i]) {
        final String g => GroupHeader(g),
        final SectionObj s => SectionRow(s: s, selected: s.id == sel, onTap: () => _selectSection(s)),
        _ => const SizedBox.shrink(),
      },
    );
  }

  Widget _routes(Tok t) {
    final all = _scene?.routes ?? const <RouteObj>[];
    final list = [for (final r in all) if (r.train == _trainRoutes) r];
    final rows = _grouped(list, (r) => '${r.variant ? 'вариантные' : 'основные'} · ${r.throat}');
    final sel = _selected is RouteHit ? (_selected as RouteHit).r.id : -1;
    final trains = all.where((r) => r.train).length;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
          child: Row(
            children: [
              Expanded(child: SegButton('Поездные ($trains)', _trainRoutes, () => setState(() => _trainRoutes = true), monoFont: false)),
              Expanded(
                child: SegButton(
                  'Маневровые (${all.length - trains})',
                  !_trainRoutes,
                  () => setState(() => _trainRoutes = false),
                  monoFont: false,
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: list.isEmpty
              ? Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('Маршрутов нет.', style: TextStyle(fontSize: 12, color: t.muted)),
                )
              : ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (c, i) => switch (rows[i]) {
                    final String g => GroupHeader(g),
                    final RouteObj r => RouteRow(r: r, selected: r.id == sel, onTap: () => _selectRoute(r)),
                    _ => const SizedBox.shrink(),
                  },
                ),
        ),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 8),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: t.line))),
          child: Text(
            '+ по прямому ходу, − по ответвлению. Охранные стрелки не определяются.',
            style: TextStyle(fontSize: 11, color: t.muted),
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
