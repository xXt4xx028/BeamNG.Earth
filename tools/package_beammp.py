"""Build experimental BeamMP Resources and a central host source ZIP.

Does not install anything into an existing game or server.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]


def build(out, bridge_exe=None):
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
    docs = ['BEAMMP-CENTRAL.md','BEAMMP-CLIENT-BRIDGE.md','BEAMMP-REGIONAL.md','BEAMMP-TRANSPORT-REVIEW.md']
    for name in docs[1:]:
        shutil.copy2(ROOT/'docs'/name,out/name)
    coverage='2026-10-18-mexico-patagonia-coverage.json'
    (out/'research').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'docs/research'/coverage,out/'research'/coverage)
    bridge_dir = out/'ClientBridge'
    bridge_dir.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'tools/earth_client_bridge.py',bridge_dir/'earth_client_bridge.py')
    bridge_info = None
    if bridge_exe:
        bridge_exe=Path(bridge_exe).resolve()
        target=bridge_dir/'EarthClientBridge.exe'
        shutil.copy2(bridge_exe,target)
        bridge_info={'file':'ClientBridge/EarthClientBridge.exe','bytes':target.stat().st_size,
                     'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'start':'manual'}
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
        for name in docs[1:]:
            archive.write(ROOT/'docs'/name,'BeamNG.Earth-BeamMP/docs/'+name)
        archive.write(ROOT/'docs/research'/coverage,'BeamNG.Earth-BeamMP/docs/research/'+coverage)
        for name in ('earth_client_bridge.py','import_elevation.py','check_regional_data.py'):
            archive.write(ROOT/'tools'/name,'BeamNG.Earth-BeamMP/tools/'+name)
        for name in ('main.lua','EarthSync.json'):
            path=ROOT/'beammp'/'Resources'/'Server'/'EarthSync'/name
            archive.write(path,'BeamNG.Earth-BeamMP/'+path.relative_to(ROOT).as_posix())
    (out/'ServerConfig.Earth.example.toml').write_text(
        '# Merge into the existing BeamMP server configuration.\n[General]\nMaxPlayers = 8\n'
        'Map = "/levels/beamng_earth/info.json"\n',encoding='utf-8')
    result = {'experimental': True, 'clientZip': str(client), 'serverPlugin': str(plugin),
              'hostZip': str(companion), 'sharedCacheGB':40,'maxPlayers':8,
              'clientBridge':bridge_info,
              'clientBytes': client.stat().st_size,'hostBytes': companion.stat().st_size}
    (out / 'build.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist' / 'beammp-central')
    parser.add_argument('--bridge-exe',type=Path,help='optional explicitly built Windows bridge; stored outside the mod ZIP')
    args=parser.parse_args()
    print(json.dumps(build(args.out.resolve(),args.bridge_exe), indent=2))
