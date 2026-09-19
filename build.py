"""Сборка приложения для раздачи (без исходников).

    python build.py            – новая версия: Flutter-интерфейс + Python-бэкенд
                                 -> dist/StationJoints/, установщик
                                    dist/StationJoints-Setup-<версия>.exe и
                                    портативный архив dist/StationJoints-win64.zip
    python build.py legacy     – старая версия на customtkinter -> dist/StationJoints.exe

Python-часть собирается в отдельном окружении .build-venv, куда ставятся только нужные
пакеты (OpenCV без GUI, numpy, Pillow) – так сборка заметно меньше.
Для Flutter нужен Flutter SDK (flutter в PATH или C:\\src\\flutter) и Visual Studio
Build Tools с компонентом C++; для установщика – Inno Setup 6
(winget install JRSoftware.InnoSetup), без него соберётся только архив.

Версия – одна на всё: `version:` в app_flutter/pubspec.yaml.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, '.build-venv')
PY = os.path.join(VENV, 'Scripts' if os.name == 'nt' else 'bin', 'python')
SEP = ';' if os.name == 'nt' else ':'
APP = os.path.join(ROOT, 'app_flutter')
EXCLUDE = [a for m in ('matplotlib', 'scipy', 'skimage', 'pandas', 'IPython', 'pytest',
                       'customtkinter', 'tkinter',
                       # не нужные форматы Pillow (AVIF – 7.6 МБ) и Tk/Qt
                       'PIL.AvifImagePlugin', 'PIL._avif', 'PIL.WebPImagePlugin', 'PIL._webp',
                       'PIL.ImageTk', 'PIL._imagingtk', 'PIL.ImageQt',
                       # сеть не нужна – без OpenSSL (libssl + libcrypto ~ 7 МБ);
                       # hashlib работает на встроенных sha1/md5
                       'ssl', '_ssl', '_hashlib')
           for a in ('--exclude-module', m)]


def app_version() -> str:
    m = re.search(r'^version:\s*([0-9]+\.[0-9]+\.[0-9]+)', open(
        os.path.join(APP, 'pubspec.yaml'), encoding='utf-8').read(), re.M)
    if not m:
        sys.exit('в app_flutter/pubspec.yaml нет строки version: X.Y.Z')
    return m.group(1)


def iscc_cmd():
    for c in (shutil.which('ISCC'),
              os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Inno Setup 6', 'ISCC.exe'),
              r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'):
        if c and os.path.exists(c):
            return c
    return None


def run(*args, cwd=ROOT):
    print('>', ' '.join(args), flush=True)
    subprocess.run(args, check=True, cwd=cwd)


def venv(*extra):
    if not os.path.exists(PY):
        run(sys.executable, '-m', 'venv', VENV)
    run(PY, '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
    run(PY, '-m', 'pip', 'install', '--quiet', 'opencv-python-headless', 'numpy', 'pillow',
        'pyinstaller', *extra)


def flutter_cmd():
    exe = shutil.which('flutter')
    if exe:
        return exe
    guess = r'C:\src\flutter\bin\flutter.bat'
    if os.path.exists(guess):
        return guess
    sys.exit('Flutter SDK не найден: добавьте flutter в PATH')


def build_flutter():
    venv()
    run(PY, os.path.join('tools', 'make_icon.py'))
    # 1) бэкенд: папка с server.exe (onedir – без распаковки при каждом запуске),
    #    без консольного окна; обмен с интерфейсом – через stdin/stdout
    run(PY, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--noconsole',
        '--name', 'server',
        '--distpath', os.path.join('build', 'backend-dist'),
        '--workpath', os.path.join('build', 'backend-work'),
        '--add-data', f'{os.path.join("samples", "var96_photo.jpg")}{SEP}samples',
        *EXCLUDE, 'server.py')
    # видео OpenCV не нужно – библиотека ffmpeg (~30 МБ) грузится лениво, убираем
    cv2dir = os.path.join(ROOT, 'build', 'backend-dist', 'server', '_internal', 'cv2')
    for f in os.listdir(cv2dir) if os.path.isdir(cv2dir) else []:
        if f.startswith('opencv_videoio_ffmpeg'):
            os.remove(os.path.join(cv2dir, f))
    # 2) интерфейс (версия – для проверки обновлений)
    ver = app_version()
    run(flutter_cmd(), 'build', 'windows', '--release', f'--dart-define=APP_VERSION={ver}', cwd=APP)
    rel = os.path.join(APP, 'build', 'windows', 'x64', 'runner', 'Release')
    # версия, зашитая в программу, должна совпасть с версией установщика – иначе
    # установленная программа будет вечно предлагать обновиться до «своего» релиза
    with open(os.path.join(rel, 'data', 'app.so'), 'rb') as f:
        if f'StationJoints/{ver}'.encode() not in f.read():
            sys.exit(f'В собранной программе не версия {ver} – удалите app_flutter/build и соберите заново')
    # 3) сборка вместе: интерфейс + backend/
    out = os.path.join(ROOT, 'dist', 'StationJoints')
    shutil.rmtree(out, ignore_errors=True)
    if os.path.exists(out):
        # приложение из dist запущено и держит файлы – собираем рядом
        print(f'! {out} занята (приложение запущено?) – сборка в StationJoints-new', flush=True)
        out += '-new'
        shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(rel, out)
    shutil.copytree(os.path.join(ROOT, 'build', 'backend-dist', 'server'),
                    os.path.join(out, 'backend'))
    zip_base = os.path.join(ROOT, 'dist', 'StationJoints-win64')
    if os.path.exists(zip_base + '.zip'):
        os.remove(zip_base + '.zip')
    shutil.make_archive(zip_base, 'zip', os.path.join(ROOT, 'dist'), os.path.basename(out))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
    print(f'\nГотово {ver}: {out} ({size / 2**20:.0f} МБ), '
          f'архив {zip_base}.zip ({os.path.getsize(zip_base + ".zip") / 2**20:.0f} МБ)')
    # 4) установщик
    iscc = iscc_cmd()
    if not iscc:
        print('Inno Setup не найден – установщик не собран (winget install JRSoftware.InnoSetup)')
        return
    for old in glob.glob(os.path.join(ROOT, 'dist', 'StationJoints-Setup-*.exe')):
        os.remove(old)
    run(iscc, '/Q', f'/DAppVersion={ver}', f'/DSourceDir={out}', 'installer.iss')
    setup = os.path.join(ROOT, 'dist', f'StationJoints-Setup-{ver}.exe')
    print(f'Установщик: {setup} ({os.path.getsize(setup) / 2**20:.0f} МБ)')


def build_legacy():
    venv('customtkinter')
    run(PY, os.path.join('tools', 'make_icon.py'))
    run(PY, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', 'StationJoints',
        '--icon', os.path.join('assets', 'icon.ico'),
        '--add-data', f'assets{SEP}assets',
        '--add-data', f'{os.path.join("samples", "var96_photo.jpg")}{SEP}samples',
        '--collect-data', 'customtkinter',
        *[a for m in ('matplotlib', 'scipy', 'skimage', 'pandas', 'IPython', 'pytest')
          for a in ('--exclude-module', m)],
        'app.py')
    exe = os.path.join(ROOT, 'dist', 'StationJoints.exe' if os.name == 'nt' else 'StationJoints')
    print(f'\nГотово: {exe} ({os.path.getsize(exe) / 2**20:.1f} МБ)')


if __name__ == '__main__':
    build_legacy() if 'legacy' in sys.argv[1:] else build_flutter()
