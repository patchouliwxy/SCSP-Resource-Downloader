"""Copy runtime tools and metadata from a release; never copy user downloads."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import zipfile

METADATA = {'official-current-index.json', 'song-names.json', 'character-data.json', 'wardrobe-data.json'}

def allowed(parts):
    return bool(parts) and (parts[0] == 'tools' or len(parts) == 1 and parts[0] in METADATA)

def prepare(release, target):
    release, target = Path(release).resolve(), Path(target).resolve()
    if release == target:
        raise ValueError('Release and source must be different directories')
    count = 0
    if release.is_file() and zipfile.is_zipfile(release):
        with zipfile.ZipFile(release) as archive:
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or any(p in ('..', '') or ':' in p or '\\' in p for p in path.parts):
                    raise ValueError('Unsafe archive path: ' + info.filename)
                parts = path.parts[1:] if path.parts[:1] == ('SCSPDownloader',) else path.parts
                if info.is_dir() or not allowed(parts):
                    continue
                out = target.joinpath(*parts)
                if not out.resolve().is_relative_to(target):
                    raise ValueError('Runtime target escapes source')
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, out.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
    elif release.is_dir():
        for path in release.rglob('*'):
            parts = path.relative_to(release).parts
            if not allowed(parts) or not path.is_file():
                continue
            out = target.joinpath(*parts)
            if not out.resolve().is_relative_to(target):
                raise ValueError('Runtime target escapes source')
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            count += 1
    else:
        raise ValueError('Select an extracted release directory or ZIP')
    required = METADATA | {'tools/AssetStudioMod/cli/AssetStudioModCLI_net472_win32_64/AssetStudioModCLI.exe',
                           'tools/AssetRipper/2.0.0/AssetRipper.GUI.Free.exe', 'tools/vgmstream/r2117/vgmstream-cli.exe'}
    missing = [p for p in required if not (target / p).is_file()]
    if missing:
        raise ValueError('Incomplete runtime: ' + ', '.join(sorted(missing)))
    print(f'Prepared {count} runtime/metadata files. No downloads or caches copied.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.release, Path(__file__).resolve().parent)
