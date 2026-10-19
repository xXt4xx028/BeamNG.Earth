"""Run a central Earth generator: one 40 GB download cache, at most 8 clients.

Clients receive generated files through the mod; they do not run Python.
BeamMP-Server remains a separate process. Run both services on the host.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def command(beammp_dir, data_dir, public_host, listen='127.0.0.1', port=47613):
    return [sys.executable,str(ROOT/'server'/'earthd.py'),
            '--remote-assets','--listen',listen,'--port',str(port),'--max-clients','8',
            '--cache-cap','40','--cache-dir',str(data_dir/'downloads'),
            '--user-dir',str(data_dir/'runtime'),'--auth-token-file',str(data_dir/'.world-token'),
            '--publish-config',str(beammp_dir/'Resources'/'Server'/'EarthSync'/'EarthSync.runtime.json'),
            '--public-host',public_host,'--workers','2','--road-processes','2','--pin','off',
            '--load-boost','off','--update-check','off']


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beammp-dir',required=True,type=Path,help='dedicated test BeamMP server folder')
    parser.add_argument('--public-host',required=True,help='LAN/VPN address accepted by the game socket sandbox; direct public Internet is unsupported')
    parser.add_argument('--listen',default='127.0.0.1',help='explicit bind address; default is local-only')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--port',type=int,default=47613)
    args=parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('invalid port')
    host=args.beammp_dir.resolve()
    data=(args.data_dir or host/'EarthWorld').resolve()
    resource=host/'Resources'/'Server'/'EarthSync'
    resource.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'beammp'/'Resources'/'Server'/'EarthSync'/'main.lua',resource/'main.lua')
    print('Shared download cache: 40 GB target for all 8 clients; generated runtime files are additional.',flush=True)
    print('Keep BeamMP-Server running separately with MaxPlayers = 8 and the Earth client ZIP.',flush=True)
    print('Earth asset connections require LAN or a compatible VPN/local tunnel; the game may block public IPs.',flush=True)
    raise SystemExit(subprocess.call(command(host,data,args.public_host,args.listen,args.port)))
