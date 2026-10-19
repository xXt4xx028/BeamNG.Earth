"""Build experimental BeamMP Resources and a central host source ZIP.

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
    for name in ('main.lua','EarthSync.json'):
        path=ROOT/'beammp'/'Resources'/'Server'/'EarthSync'/name
        shutil.copy2(path, plugin / path.name)
    shutil.copy2(ROOT / 'docs' / 'BEAMMP-CENTRAL.md', out / 'README-BEAMMP.md')
    spec = importlib.util.spec_from_file_location('earth_package', ROOT / 'tools' / 'package.py')
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    companion = out / 'BeamNG.Earth-BeamMP-host-source.zip'
    with zipfile.ZipFile(companion, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in package.collect():
            archive.write(ROOT / name, 'BeamNG.Earth-BeamMP/' + name)
        archive.write(ROOT / 'docs' / 'BEAMMP.md', 'BeamNG.Earth-BeamMP/docs/BEAMMP.md')
        archive.write(ROOT / 'tools' / 'mp_resources.py', 'BeamNG.Earth-BeamMP/tools/mp_resources.py')
        archive.write(ROOT / 'tools' / 'start_beammp_world.py', 'BeamNG.Earth-BeamMP/tools/start_beammp_world.py')
        archive.write(ROOT / 'docs' / 'BEAMMP-CENTRAL.md', 'BeamNG.Earth-BeamMP/docs/BEAMMP-CENTRAL.md')
        for name in ('main.lua','EarthSync.json'):
            path=ROOT/'beammp'/'Resources'/'Server'/'EarthSync'/name
            archive.write(path,'BeamNG.Earth-BeamMP/'+path.relative_to(ROOT).as_posix())
    (out/'ServerConfig.Earth.example.toml').write_text(
        '# Merge into the existing BeamMP server configuration.\n[General]\nMaxPlayers = 8\n'
        'Map = "/levels/beamng_earth/info.json"\n',encoding='utf-8')
    result = {'experimental': True, 'clientZip': str(client), 'serverPlugin': str(plugin),
              'hostZip': str(companion), 'sharedCacheGB':40,'maxPlayers':8,
              'clientBytes': client.stat().st_size,'hostBytes': companion.stat().st_size}
    (out / 'build.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist' / 'beammp-central')
    print(json.dumps(build(parser.parse_args().out.resolve()), indent=2))
