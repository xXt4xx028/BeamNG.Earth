"""Build experimental BeamMP Resources and a companion source ZIP in dist/beammp.

Does not install anything into an existing game or server.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(out):
    client = out / 'Resources' / 'Client' / 'beamng_earth_mp.zip'
    client.parent.mkdir(parents=True, exist_ok=True)
    mod = ROOT / 'mod' / 'beamng_earth'
    with zipfile.ZipFile(client, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(mod.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(mod).as_posix())
    plugin = out / 'Resources' / 'Server' / 'EarthSync'
    plugin.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / 'beammp' / 'Resources' / 'Server' / 'EarthSync').glob('*'):
        if path.is_file():
            shutil.copy2(path, plugin / path.name)
    shutil.copy2(ROOT / 'docs' / 'BEAMMP.md', out / 'README-BEAMMP.md')
    spec = importlib.util.spec_from_file_location('earth_package', ROOT / 'tools' / 'package.py')
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    companion = out / 'BeamNG.Earth-BeamMP-companion-source.zip'
    with zipfile.ZipFile(companion, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in package.collect():
            archive.write(ROOT / name, 'BeamNG.Earth-BeamMP/' + name)
        archive.write(ROOT / 'docs' / 'BEAMMP.md', 'BeamNG.Earth-BeamMP/docs/BEAMMP.md')
        archive.write(ROOT / 'tools' / 'mp_resources.py', 'BeamNG.Earth-BeamMP/tools/mp_resources.py')
    result = {'experimental': True, 'clientZip': str(client), 'serverPlugin': str(plugin),
              'companionZip': str(companion), 'clientBytes': client.stat().st_size,
              'companionBytes': companion.stat().st_size}
    (out / 'build.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist' / 'beammp')
    print(json.dumps(build(parser.parse_args().out.resolve()), indent=2))
