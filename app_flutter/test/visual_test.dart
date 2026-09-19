import 'dart:async';
// Визуальная проверка без экрана: полный интерфейс рисуется в памяти (flutter test),
// с настоящим Python-бэкендом и системными шрифтами, снимки – в PNG.
//
//   flutter test test/visual_test.dart --dart-define=SHOTS=<папка>
//
// Ни окон, ни движений мыши – можно запускать, пока компьютер занят другим.
import 'dart:io';
import 'dart:ui' as ui;
import 'dart:ui' show AppExitResponse;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:station_joints/main.dart';
import 'package:station_joints/recent.dart';
import 'package:station_joints/scheme_view.dart';

const shots = String.fromEnvironment('SHOTS');
const stj = String.fromEnvironment('STJ'); // файл работы для проверки открытия
final _sample = '${Directory.current.parent.path}${Platform.pathSeparator}samples'
    '${Platform.pathSeparator}var96_photo.jpg';

Future<void> _font(String family, List<String> files) async {
  final l = FontLoader(family);
  for (final f in files) {
    final b = File(f).readAsBytesSync();
    l.addFont(Future.value(ByteData.view(b.buffer)));
  }
  await l.load();
}

final _boundary = GlobalKey();

Future<void> _shot(WidgetTester t, String name) async {
  if (shots.isEmpty) return;
  await t.pump(const Duration(milliseconds: 400));
  await t.runAsync(() async {
    final ro = _boundary.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final img = await ro.toImage(pixelRatio: 1);
    final png = await img.toByteData(format: ui.ImageByteFormat.png);
    File('$shots/$name.png').writeAsBytesSync(png!.buffer.asUint8List());
  });
}

Future<void> _waitFor(WidgetTester t, Finder f, {int seconds = 40}) async {
  for (var i = 0; i < seconds * 5; i++) {
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    await t.pump(const Duration(milliseconds: 50));
    if (f.evaluate().isNotEmpty) return;
  }
  fail('не дождались: $f');
}

void main() {
  setUpAll(() async {
    // недавние – во временную папку, не в профиль пользователя
    Recent.dirOverride = Directory.systemTemp.createTempSync('sj_recent').path;
    const fonts = r'C:\Windows\Fonts';
    await _font('Arial', ['$fonts\\arial.ttf']);
    await _font('Segoe UI', ['$fonts\\segoeui.ttf', '$fonts\\segoeuib.ttf']);
    await _font('Consolas', ['$fonts\\consola.ttf', '$fonts\\consolab.ttf']);
    final flutterRoot = Platform.environment['FLUTTER_ROOT'] ?? r'C:\src\flutter';
    await _font('MaterialIcons',
        ['$flutterRoot\\bin\\cache\\artifacts\\material_fonts\\MaterialIcons-Regular.otf']);
  });

  testWidgets('интерфейс: загрузка, зум, светофор, тёмная тема', (t) async {
    t.view.physicalSize = const Size(1480, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);

    await t.pumpWidget(RepaintBoundary(key: _boundary, child: StationApp(initialPath: _sample)));
    await _waitFor(t, find.textContaining('светофоров'));
    await _shot(t, '1_loaded');

    // зум колесом к узлу левой горловины
    final canvas = t.getCenter(find.byType(CustomPaint).last);
    final p = TestPointer(1, PointerDeviceKind.mouse);
    final at = Offset(canvas.dx - 250, canvas.dy);
    await t.sendEventToBinding(p.hover(at));
    for (var i = 0; i < 8; i++) {
      await t.sendEventToBinding(p.scroll(const Offset(0, -120)));
    }
    await _shot(t, '2_zoom');

    // вкладка «Светофоры» -> клик по строке -> плавный переход и выделение
    await t.tap(find.text('Светофоры').last);
    await t.pump();
    await t.tap(find.text('ЧД').last);
    await t.pump(const Duration(milliseconds: 300));
    await _shot(t, '3_signal');

    // тёмная тема
    await t.tap(find.byTooltip('Тема'));
    await t.pump(const Duration(milliseconds: 300));
    await _shot(t, '4_dark');

    // вкладка «Участки» -> клик по участку -> подсветка
    await t.tap(find.text('Участки').last);
    await t.pump();
    await t.tap(find.text('2-18СП').last);
    await t.pump(const Duration(milliseconds: 300));
    await _shot(t, '5_sections');

    // меню «Файл» с недавними
    await t.tap(find.text('Файл'));
    await t.pump(const Duration(milliseconds: 300));
    await _shot(t, '6_file_menu');
    await t.tapAt(const Offset(700, 450));
    await t.pump(const Duration(milliseconds: 300));

    // переименование несохранённой схемы: F2 -> имя -> Enter
    await t.sendKeyEvent(LogicalKeyboardKey.f2);
    await t.pump(const Duration(milliseconds: 100));
    await t.enterText(find.byType(TextField), 'Станция А');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await t.pump(const Duration(milliseconds: 200));
    expect(find.text('Станция А'), findsWidgets);
    await _shot(t, '4b_renamed');

    // выход: гасим бэкенд
    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
  });

  testWidgets('работа .stj и стартовый экран с недавними', (t) async {
    t.view.physicalSize = const Size(1480, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    if (stj.isNotEmpty) {
      final dir = Directory.systemTemp.createTempSync('sj_rename');
      final copy = '${dir.path}${Platform.pathSeparator}var91.stj';
      File(stj).copySync(copy);
      await t.pumpWidget(RepaintBoundary(key: _boundary, child: StationApp(initialPath: copy)));
      await _waitFor(t, find.textContaining('светофоров'));
      await t.sendKeyEvent(LogicalKeyboardKey.f2);
      await t.pump(const Duration(milliseconds: 100));
      await t.enterText(find.byType(TextField), 'var91 финал');
      await t.testTextInput.receiveAction(TextInputAction.done);
      await _waitFor(t, find.textContaining('Переименовано'));
      expect(File('${dir.path}${Platform.pathSeparator}var91 финал.stj').existsSync(), isTrue);
      expect(File(copy).existsSync(), isFalse);
      await t.pumpWidget(const SizedBox());
      await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));

      await t.pumpWidget(RepaintBoundary(key: _boundary, child: StationApp(initialPath: stj)));
      await _waitFor(t, find.textContaining('светофоров'));
      expect(find.textContaining('.stj'), findsWidgets);
      // повторный запуск программы с другим файлом – открывается в этом окне
      unawaited(t.binding.defaultBinaryMessenger.handlePlatformMessage(
        'station_joints/instance',
        const StandardMethodCodec().encodeMethodCall(MethodCall('open', _sample)),
        (_) {},
      ));
      await _waitFor(t, find.text('var96_photo'));
      unawaited(t.binding.defaultBinaryMessenger.handlePlatformMessage(
        'station_joints/instance',
        const StandardMethodCodec().encodeMethodCall(MethodCall('open', stj)),
        (_) {},
      ));
      // уже открыт – не дублируется, просто становится активным
      await _waitFor(t, find.text('Этот файл уже открыт'));
      expect(find.text('var91.stj'), findsWidgets);
      expect(find.text('var96_photo.jpg'), findsOneWidget);
      await _shot(t, '7b_tabs');
      // Ctrl+Tab – следующий таб, Ctrl+W – закрыть
      await t.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await t.sendKeyEvent(LogicalKeyboardKey.tab);
      await t.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      await t.pump(const Duration(milliseconds: 200));
      await _waitFor(t, find.text('var96_photo'));
      await t.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await t.sendKeyEvent(LogicalKeyboardKey.keyW);
      await t.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      for (var i = 0; i < 20 && find.text('var96_photo.jpg').evaluate().isNotEmpty; i++) {
        await t.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
        await t.pump();
      }
      expect(find.text('var96_photo.jpg'), findsNothing);
      expect(find.text('var91.stj'), findsWidgets);
      await t.runAsync(() => Future.delayed(const Duration(seconds: 2))); // миниатюра
      await _shot(t, '7_project');
      await t.pumpWidget(const SizedBox());
      await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
    }
    await t.pumpWidget(RepaintBoundary(key: _boundary, child: const StationApp()));
    await _waitFor(t, find.text('НЕДАВНИЕ'));
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 500)));
    await _shot(t, '8_start');
    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
  });

  testWidgets('защита работы: отмена, закрытие, автосохранение, восстановление', (t) async {
    t.view.physicalSize = const Size(1480, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    await t.pumpWidget(RepaintBoundary(key: _boundary, child: StationApp(initialPath: _sample)));
    await _waitFor(t, find.textContaining('светофоров'));

    // правка -> можно отменить
    await t.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await t.sendKeyEvent(LogicalKeyboardKey.keyR);
    await t.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await _waitFor(t, find.byTooltip('Отменить: расстановка заново (Ctrl+Z)'));
    await t.tap(find.byTooltip('Отменить: расстановка заново (Ctrl+Z)'));
    await _waitFor(t, find.textContaining('Отменено'));
    await _waitFor(t, find.byTooltip('Повторить: расстановка заново (Ctrl+Y)'));
    await _shot(t, '9_undo');

    // закрытие окна с несохранёнными правками -> вопрос; «Отмена» – окно остаётся
    final exit = t.binding.handleRequestAppExit();
    await t.pump(const Duration(milliseconds: 300));
    expect(find.text('Сохранить изменения?'), findsOneWidget);
    await _shot(t, '10_close');
    await t.tap(find.text('Отмена'));
    await t.pump(const Duration(milliseconds: 300));
    expect(await exit, AppExitResponse.cancel);

    // автосохранение через 30 с
    await t.pump(const Duration(seconds: 31));
    final auto = File('${Recent.dir}${Platform.pathSeparator}autosave${Platform.pathSeparator}autosave.json');
    for (var i = 0; i < 50 && !auto.existsSync(); i++) {
      await t.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    }
    expect(auto.existsSync(), isTrue);

    // «сбой»: программа закрыта без сохранения -> при запуске предложит восстановить
    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
    await t.pumpWidget(RepaintBoundary(key: _boundary, child: const StationApp()));
    await _waitFor(t, find.text('Восстановить работу?'));
    await _shot(t, '11_restore');
    await t.tap(find.text('Восстановить'));
    await _waitFor(t, find.textContaining('светофоров'));
    expect(find.text('не сохранено'), findsOneWidget);
    await _shot(t, '12_restored');
    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
  });

  testWidgets('ручные правки: стык, пути, светофор, «Объясни», перекомпоновка', (t) async {
    t.view.physicalSize = const Size(1480, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    // от прошлого теста могла остаться резервная копия – иначе спросит про восстановление
    final auto = Directory('${Recent.dir}${Platform.pathSeparator}autosave');
    if (auto.existsSync()) auto.deleteSync(recursive: true);
    await t.pumpWidget(RepaintBoundary(key: _boundary, child: StationApp(initialPath: _sample)));
    await _waitFor(t, find.textContaining('светофоров'));
    await t.pump(const Duration(milliseconds: 300));
    final view = t.widget<SchemeView>(find.byType(SchemeView).first);
    final scene = view.scene!;
    final origin = t.getTopLeft(find.byType(SchemeView).first);
    Offset scr(Offset mm) => origin + view.controller.toScreen(mm)!;

    // 1) стык тянется мышью вдоль пути
    final j = scene.joints.firstWhere((j) {
      final e = scene.edges.firstWhere((e) => e.id == j.edge);
      return (e.b - e.a).dx.abs() > 30 && j.t > 12 && j.t < (e.b - e.a).distance - 12;
    });
    await t.dragFrom(scr(j.pos), const Offset(-12, 0));
    await _waitFor(t, find.text('Стык перенесён'));

    // 2) «Пути»: новый отрезок от конца пути
    await t.sendKeyEvent(LogicalKeyboardKey.keyT);
    await t.pump();
    final end = scene.nodes.firstWhere((n) => n.isEnd && n.mark == 'tupik');
    await t.dragFrom(scr(end.pos), const Offset(0, -25));
    await _waitFor(t, find.textContaining('Отрезок добавлен'));
    await _shot(t, '13_track');

    // 3) тип конца: клик по концу -> меню -> «Перегон»
    final v2 = t.widget<SchemeView>(find.byType(SchemeView).first);
    final end2 = v2.scene!.nodes.firstWhere((n) => n.isEnd && n.mark == 'tupik');
    await t.tapAt(origin + v2.controller.toScreen(end2.pos)!);
    for (var i = 0; i < 10; i++) {
      await t.pump(const Duration(milliseconds: 100)); // меню раскрывается
    }
    await t.tap(find.text('Перегон').last);
    await _waitFor(t, find.text('Конец пути: перегон'));

    // 4) светофор: выбрать в списке, переименовать
    await t.sendKeyEvent(LogicalKeyboardKey.keyV);
    await t.tap(find.text('Светофоры').last);
    await t.pump();
    await t.tap(find.text('ЧД').last);
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.text('Свойства').last);
    await t.pump();
    await t.enterText(find.byType(TextField).last, 'ЧДх');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await _waitFor(t, find.text('Светофор изменён'));
    expect(find.text('изменён вручную'), findsOneWidget);

    // 5) «Объясни»: F1 и клик по стыку
    await t.sendKeyEvent(LogicalKeyboardKey.f1);
    await t.pump();
    final v3 = t.widget<SchemeView>(find.byType(SchemeView).first);
    final jj = v3.scene!.joints.firstWhere((x) => x.rule == 'в');
    await t.tapAt(origin + v3.controller.toScreen(jj.pos)!);
    await _waitFor(t, find.textContaining('Методичка:'));
    await _shot(t, '14_explain');

    // 6) «Два листа» – ручные правки стыков переносятся
    await t.sendKeyEvent(LogicalKeyboardKey.f1);
    await t.tap(find.text('Два листа (горловины раздельно)'));
    await _waitFor(t, find.textContaining('Ручные правки стыков перенесены'));
    await t.tap(find.text('Светофоры').last);
    await t.pump();
    expect(find.text('ЧДх'), findsWidgets); // правка светофора тоже сохранилась
    await _shot(t, '15_after_relayout');

    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
  });
}
