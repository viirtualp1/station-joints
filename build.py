"""Сборка StationJoints.exe – один файл без исходников, в папку dist/.

    python build.py

Собирает в отдельном окружении .build-venv, куда ставятся только нужные пакеты
(OpenCV без GUI, numpy, Pillow, customtkinter) – так exe заметно меньше.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, '.build-venv')
PY = os.path.join(VENV, 'Scripts' if os.name == 'nt' else 'bin', 'python')
SEP = ';' if os.name == 'nt' else ':'


def run(*args):
    print('>', ' '.join(args), flush=True)
    subprocess.run(args, check=True, cwd=ROOT)


def main():
    if not os.path.exists(PY):
        run(sys.executable, '-m', 'venv', VENV)
    run(PY, '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
    run(PY, '-m', 'pip', 'install', '--quiet', 'opencv-python-headless', 'numpy', 'pillow',
        'customtkinter', 'pyinstaller')
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
    main()
