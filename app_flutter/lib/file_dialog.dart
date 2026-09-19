import 'dart:ffi';

import 'package:ffi/ffi.dart';
import 'package:win32/win32.dart';

/// Системные диалоги «Открыть» / «Сохранить» Windows через comdlg32 (FFI).
/// Без нативных плагинов – сборка не требует «режима разработчика» Windows.

Pointer<Utf16> _multi(List<String> parts) {
  // строка вида "A\0B\0C\0\0" – формат фильтров comdlg32
  final units = <int>[];
  for (final p in parts) {
    units
      ..addAll(p.codeUnits)
      ..add(0);
  }
  units.add(0);
  final buf = calloc<Uint16>(units.length);
  buf.asTypedList(units.length).setAll(0, units);
  return buf.cast<Utf16>();
}

String? _dialog({
  required bool save,
  required String title,
  required List<(String, List<String>)> filters,
  String? suggestedName,
  String? defExt,
}) {
  const max = 4096;
  final file = calloc<Uint16>(max);
  if (suggestedName != null) {
    final u = suggestedName.codeUnits.take(max - 1).toList();
    file.asTypedList(max).setAll(0, u);
  }
  final filter = _multi([
    for (final (label, exts) in filters) ...[
      '$label (${exts.map((e) => '*.$e').join(', ')})',
      exts.map((e) => '*.$e').join(';'),
    ],
  ]);
  final titleP = title.toNativeUtf16();
  final defP = (defExt ?? '').toNativeUtf16();
  final ofn = calloc<OPENFILENAME>();
  try {
    ofn.ref
      ..lStructSize = sizeOf<OPENFILENAME>()
      ..hwndOwner = GetActiveWindow()
      ..lpstrFilter = PWSTR(filter)
      ..nFilterIndex = 1
      ..lpstrFile = PWSTR(file.cast<Utf16>())
      ..nMaxFile = max
      ..lpstrTitle = PWSTR(titleP)
      ..lpstrDefExt = PWSTR(defP)
      ..Flags = OPEN_FILENAME_FLAGS(
        save
            ? OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST
            : OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST,
      );
    final ok = save ? GetSaveFileName(ofn) : GetOpenFileName(ofn);
    if (!ok) return null;
    return file.cast<Utf16>().toDartString();
  } finally {
    calloc
      ..free(file)
      ..free(filter)
      ..free(titleP)
      ..free(defP)
      ..free(ofn);
  }
}

const _images = ['png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff'];

/// Открыть: работа .stj или картинка схемы.
String? pickOpen() => _dialog(
  save: false,
  title: 'Открыть схему или работу',
  filters: [
    ('Работы и схемы', ['stj', ..._images]),
    ('Работы «Стыки»', ['stj']),
    ('Изображения', _images),
    ('Все файлы', ['*']),
  ],
);

String? pickSave(String suggestedName, String label, String ext) => _dialog(
  save: true,
  title: 'Сохранить',
  filters: [
    (label, [ext]),
  ],
  suggestedName: suggestedName,
  defExt: ext,
);
