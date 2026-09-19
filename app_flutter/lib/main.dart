import 'package:flutter/material.dart';

import 'home.dart';
import 'theme.dart';

void main(List<String> args) => runApp(StationApp(initialPath: args.isEmpty ? null : args.first));

class StationApp extends StatefulWidget {
  final String? initialPath; // файл из командной строки («Открыть с помощью»)
  const StationApp({super.key, this.initialPath});

  @override
  State<StationApp> createState() => _StationAppState();
}

class _StationAppState extends State<StationApp> {
  ThemeMode _mode = ThemeMode.system;

  void _toggle() {
    final dark = _mode == ThemeMode.dark ||
        (_mode == ThemeMode.system &&
            WidgetsBinding.instance.platformDispatcher.platformBrightness == Brightness.dark);
    setState(() => _mode = dark ? ThemeMode.light : ThemeMode.dark);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Стыки — схема станции',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: _mode,
      home: Home(onToggleTheme: _toggle, initialPath: widget.initialPath),
    );
  }
}
