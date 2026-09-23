# Интерфейс «Стыки» (Flutter, Windows)

Интерфейс ничего не считает сам: схему распознаёт, компонует и проверяет Python-бэкенд
(`../server.py`), обмен – JSON по строке через stdin/stdout (`lib/backend.dart`).

```
lib/main.dart          – приложение, тема
lib/home.dart          – главный экран: табы, команды бэкенду, выделение, клавиши
lib/scheme_view.dart   – холст: зум, выбор, перетаскивание стыков, рисование путей
lib/scene.dart         – модель сцены (что прислал бэкенд)
lib/document.dart      – открытая схема (таб)
lib/autosave.dart      – резервные копии несохранённых схем
lib/recent.dart, update.dart, file_dialog.dart – недавние, обновления, диалоги Windows
lib/ui/                – панели, списки, меню, диалоги, строка состояния, кнопки
```

Запуск из исходников: `flutter run -d windows` – бэкенд найдётся сам (`server.py` выше по
дереву, запускается через `python`), либо задайте путь в `STATION_BACKEND`.

Тесты: `flutter test` (`test/visual_test.dart` поднимает настоящий бэкенд; снимки экрана –
`flutter test test/visual_test.dart --dart-define=SHOTS=<папка>`).
