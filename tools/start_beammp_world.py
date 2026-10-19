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


def command(beammp_dir, data_dir, public_host, listen='127.0.0.1', port=47613,
            tls_cert=None,tls_key=None,local_dem=None,profile='auto'):
    args = [sys.executable,str(ROOT/'server'/'earthd.py'),
            '--remote-assets','--listen',listen,'--port',str(port),'--max-clients','8',
            '--cache-cap','40','--cache-dir',str(data_dir/'downloads'),
            '--user-dir',str(data_dir/'runtime'),'--auth-token-file',str(data_dir/'.world-token'),
            '--publish-config',str(beammp_dir/'Resources'/'Server'/'EarthSync'/'EarthSync.runtime.json'),
            '--public-host',public_host,'--performance',profile,'--pin','off',
            '--load-boost','off','--update-check','off',
            '--upload-mbps','240','--player-upload-mbps','40']
    if tls_cert:
        args += ['--tls-cert',str(tls_cert),'--tls-key',str(tls_key)]
    if local_dem:
        args += ['--local-dem-dir',str(local_dem)]
    return args


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beammp-dir',required=True,type=Path,help='dedicated test BeamMP server folder')
    parser.add_argument('--public-host',required=True,help='host reachable by players: LAN/VPN directly, or Internet with TLS and the separate client bridge')
    parser.add_argument('--listen',default='127.0.0.1',help='explicit bind address; default is local-only')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--port',type=int,default=47613)
    parser.add_argument('--tls-cert',type=Path,help='host certificate PEM; use with client bridge')
    parser.add_argument('--tls-key',type=Path,help='host private key PEM')
    parser.add_argument('--local-dem-dir',type=Path,help='prepared immutable regional elevation pack')
    parser.add_argument('--performance',choices=('auto','low','balanced','scenic'),default='auto',help='auto: low below 16 GiB RAM, balanced otherwise')
    args=parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('invalid port')
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error('--tls-cert and --tls-key must be supplied together')
    host=args.beammp_dir.resolve()
    data=(args.data_dir or host/'EarthWorld').resolve()
    resource=host/'Resources'/'Server'/'EarthSync'
    resource.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'beammp'/'Resources'/'Server'/'EarthSync'/'main.lua',resource/'main.lua')
    print('Shared download cache: 40 GB target for all 8 clients; generated runtime files are additional.',flush=True)
    print('Keep BeamMP-Server running separately with MaxPlayers = 8 and the Earth client ZIP.',flush=True)
    print(f'Earth upload cap: 240 Mbit/s shared, 40 Mbit/s per player; performance profile: {args.performance}.',flush=True)
    print('Use the separate client bridge for TLS/Internet, or LAN/VPN for direct game connections.',flush=True)
    raise SystemExit(subprocess.call(command(host,data,args.public_host,args.listen,args.port,
                                             args.tls_cert,args.tls_key,args.local_dem_dir,args.performance)))
