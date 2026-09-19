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

    // выход: гасим бэкенд
    await t.pumpWidget(const SizedBox());
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
  });

  testWidgets('работа .stj и стартовый экран с недавними', (t) async {
    t.view.physicalSize = const Size(1480, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    if (stj.isNotEmpty) {
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
      await _waitFor(t, find.textContaining('.stj'));
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
}
