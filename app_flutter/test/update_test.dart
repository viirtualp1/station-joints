import 'package:flutter_test/flutter_test.dart';
import 'package:station_joints/update.dart';

void main() {
  test('сравнение версий', () {
    expect(compareVersions('1.2.0', '1.1.9'), 1);
    expect(compareVersions('v1.10.0', '1.9.3'), 1);
    expect(compareVersions('1.0', '1.0.0'), 0);
    expect(compareVersions('1.0.0', '1.0.1'), -1);
    expect(compareVersions('2.0.0-beta', '1.9.9'), 1);
  });

  test('разбор ответа GitHub', () {
    final j = {
      'tag_name': 'v1.3.0',
      'html_url': 'https://github.com/x/y/releases/tag/v1.3.0',
      'body': 'Что нового\n',
      'assets': [
        {'name': 'StationJoints-win64.zip', 'browser_download_url': 'zip'},
        {'name': 'StationJoints-Setup-1.3.0.exe', 'browser_download_url': 'exe'},
      ],
    };
    final r = parseRelease(j, '1.2.0')!;
    expect(r.version, '1.3.0');
    expect(r.installer, 'exe');
    expect(r.notes, 'Что нового');
    expect(parseRelease(j, '1.3.0'), isNull); // уже установлена
    expect(parseRelease({...j, 'prerelease': true}, '1.0.0'), isNull);
  });
}
