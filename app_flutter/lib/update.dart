import 'dart:convert';
import 'dart:io';

import 'package:ffi/ffi.dart';
import 'package:win32/win32.dart';

/// Версия приложения – задаётся при сборке (build.py: --dart-define=APP_VERSION=…
/// из pubspec.yaml). В разработке – «dev», проверка обновлений выключена.
const appVersion = String.fromEnvironment('APP_VERSION', defaultValue: 'dev');

/// Публичный репозиторий, в Releases которого выкладываются установщики.
/// Исходники при этом могут жить в приватном репозитории.
const updateRepo = 'viirtualp1/station-joints-releases';

class Release {
  final String version, page, notes;
  final String? installer; // ссылка на StationJoints-Setup-*.exe
  Release(this.version, this.page, this.notes, this.installer);
}

/// Сравнение версий вида 1.2.10 (лишние части и суффиксы игнорируются).
int compareVersions(String a, String b) {
  List<int> parts(String v) => [
    for (final p in v.replaceFirst(RegExp(r'^[vV]'), '').split(RegExp(r'[.\-+]')).take(3)) int.tryParse(p) ?? 0,
  ];
  final x = parts(a), y = parts(b);
  for (var i = 0; i < 3; i++) {
    final d = (i < x.length ? x[i] : 0) - (i < y.length ? y[i] : 0);
    if (d != 0) return d.sign;
  }
  return 0;
}

/// Разбор ответа GitHub API /releases/latest. null – если не новее текущей.
Release? parseRelease(Map<String, dynamic> j, String current) {
  final tag = j['tag_name'] as String?;
  if (tag == null || j['draft'] == true || j['prerelease'] == true) return null;
  if (compareVersions(tag, current) <= 0) return null;
  String? exe;
  for (final a in (j['assets'] as List? ?? const [])) {
    final name = (a['name'] as String? ?? '').toLowerCase();
    if (name.endsWith('.exe') && name.contains('setup')) exe = a['browser_download_url'] as String?;
  }
  return Release(
    tag.replaceFirst(RegExp(r'^[vV]'), ''),
    j['html_url'] as String? ?? '',
    (j['body'] as String? ?? '').trim(),
    exe,
  );
}

/// Есть ли новая версия. Ошибки сети – молча null (проверка – не главное).
Future<Release?> checkUpdate() async {
  if (appVersion == 'dev') return null;
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
  try {
    final req = await client.getUrl(Uri.parse('https://api.github.com/repos/$updateRepo/releases/latest'));
    req.headers
      ..set(HttpHeaders.userAgentHeader, 'StationJoints/$appVersion')
      ..set(HttpHeaders.acceptHeader, 'application/vnd.github+json');
    final res = await req.close().timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) return null;
    final body = await res.transform(utf8.decoder).join();
    return parseRelease(jsonDecode(body) as Map<String, dynamic>, appVersion);
  } catch (_) {
    return null;
  } finally {
    client.close(force: true);
  }
}

/// Скачать установщик во временную папку; onProgress – доля 0..1.
Future<String> downloadInstaller(Release r, void Function(double) onProgress) async {
  final client = HttpClient();
  try {
    final req = await client.getUrl(Uri.parse(r.installer!));
    req.headers.set(HttpHeaders.userAgentHeader, 'StationJoints/$appVersion');
    final res = await req.close();
    if (res.statusCode != 200) throw HttpException('сервер ответил ${res.statusCode}');
    final dir = Directory('${Directory.systemTemp.path}${Platform.pathSeparator}StationJoints');
    dir.createSync(recursive: true);
    final file = File('${dir.path}${Platform.pathSeparator}StationJoints-Setup-${r.version}.exe');
    final sink = file.openWrite();
    var got = 0;
    final total = res.contentLength;
    await for (final chunk in res) {
      sink.add(chunk);
      got += chunk.length;
      if (total > 0) onProgress(got / total);
    }
    await sink.close();
    return file.path;
  } finally {
    client.close(force: true);
  }
}

/// Открыть ссылку в браузере по умолчанию.
void openUrl(String url) {
  final op = 'open'.toNativeUtf16(), u = url.toNativeUtf16();
  try {
    ShellExecute(null, PCWSTR(op), PCWSTR(u), null, null, SW_SHOWNORMAL);
  } finally {
    calloc
      ..free(op)
      ..free(u);
  }
}
