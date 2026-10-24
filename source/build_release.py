"""Build a clean Windows distribution without local downloads, caches or history."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parent
release = root.parent / 'release'
build = root / 'build'
app = release / 'SCSPDownloader'
if app.exists():
    raise SystemExit('Release directory already exists. Move it aside before building; user data will not be overwritten.')
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
    '--name', 'SCSPDownloader', '--distpath', str(build / 'distribution'), '--workpath', str(build),
    '--specpath', str(root), '--collect-all', 'archspec', '--collect-all', 'fmod_toolkit',
    '--collect-all', 'UnityPy', '--collect-submodules', 'scsp_download', 'launcher.py'], cwd=root, check=True)

shutil.copytree(build / 'distribution/SCSPDownloader', app)
for name in ('web', 'tools'):
    shutil.copytree(root / name, app / name, ignore=shutil.ignore_patterns('__pycache__', '*.zip', '*.log'))
for name in ('official-current-index.json', 'song-names.json', 'character-data.json', 'wardrobe-data.json'):
    shutil.copy2(root / name, app / name)
for name in ('README.md', 'README.en.md', 'LICENSE'):
    shutil.copy2(root.parent / name, app / name)
(app / 'Update-Resources.cmd').write_text('@echo off\ncd /d "%~dp0"\nset /p gameVersion=Game Version: \nset /p resourceVersion=Resource Version: \nSCSPDownloader.exe --update --game-version "%gameVersion%" --resource-version "%resourceVersion%"\npause\n', encoding='ascii')
files = {p.relative_to(app).as_posix(): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in app.rglob('*') if p.is_file()}
release.mkdir(exist_ok=True)
(release / 'release-manifest.json').write_text(json.dumps({'files': files}, indent=2), encoding='utf-8')
output = release / 'SCSPDownloader-win64.zip'
temporary = output.with_suffix('.zip.part')
with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for name in files:
        archive.write(app / name, 'SCSPDownloader/' + name)
with zipfile.ZipFile(temporary) as archive:
    if archive.testzip():
        raise RuntimeError('ZIP CRC failed')
temporary.replace(output)
print('Release ready:', output)
