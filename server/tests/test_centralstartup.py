"""Smoke-test the actual headless CLI, with networking to providers disabled."""
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]


class CentralStartupTest(unittest.TestCase):
    def test_cli_publishes_authenticated_eight_player_40gb_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            config=root/'EarthSync.json'
            args=[sys.executable,str(ROOT/'server'/'earthd.py'),'--remote-assets','--port','0',
                  '--user-dir',str(root/'runtime'),'--cache-dir',str(root/'downloads'),
                  '--publish-config',str(config),'--public-host','127.0.0.1','--offline',
                  '--block-process','off','--roads','off','--surface','off','--trees','off',
                  '--airports','off','--sea','off','--gravity','off','--weather','off',
                  '--imagery','off','--map-tiles','off','--update-check','off','--no-horizon','--pin','off']
            process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while not config.exists() and process.poll() is None and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertTrue(config.exists(),'headless service did not publish config')
                data=json.loads(config.read_text(encoding='utf-8'))
                self.assertEqual((data['cacheGB'],data['maxPlayers']),(40,8))
                endpoint=data['worldServer']
                self.assertGreater(endpoint['port'],0)
                self.assertGreaterEqual(len(endpoint['token']),32)
                with socket.create_connection((endpoint['host'],endpoint['port']),timeout=5) as client:
                    payload=json.dumps({'type':'hello','protocol':4,'format':4,
                                        'remoteAuth':endpoint['token'],'remoteAssets':1}).encode()
                    client.sendall(struct.pack('<I',len(payload))+payload)
                    with client.makefile('rb') as stream:
                        size=struct.unpack('<I',stream.read(4))[0]
                        hello=json.loads(stream.read(size))
                    self.assertEqual(hello['type'],'hello')
                    self.assertEqual(hello['earthMP']['id'],data['profile'])
            finally:
                process.terminate()
                output,_=process.communicate(timeout=10)
                if not config.exists(): print(output.decode('utf-8',errors='replace'))

    def test_external_bind_without_remote_protocol_is_rejected(self):
        result=subprocess.run([sys.executable,str(ROOT/'server'/'earthd.py'),'--listen','0.0.0.0'],
                              capture_output=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'external listening requires --remote-assets',result.stderr)

    def test_real_headless_tls_service_through_client_bridge(self):
        import ssl
        import asyncio
        import importlib.util
        from test_clientbridge import certificate
        try:
            import cryptography
        except ImportError:
            self.skipTest('optional cryptography not installed')
        spec=importlib.util.spec_from_file_location('earth_client_bridge',ROOT/'tools/earth_client_bridge.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); cert,key=certificate(root); config=root/'runtime.json'
            args=[sys.executable,str(ROOT/'server/earthd.py'),'--remote-assets','--port','0',
                  '--tls-cert',str(cert),'--tls-key',str(key),'--user-dir',str(root/'runtime'),
                  '--cache-dir',str(root/'downloads'),'--publish-config',str(config),'--public-host','127.0.0.1',
                  '--offline','--block-process','off','--roads','off','--surface','off','--trees','off',
                  '--airports','off','--sea','off','--gravity','off','--weather','off','--imagery','off',
                  '--map-tiles','off','--update-check','off','--no-horizon','--pin','off']
            process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while not config.exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(.05)
                self.assertTrue(config.exists(),'TLS service failed to start')
                data=json.loads(config.read_text()); endpoint=data['worldServer']
                self.assertTrue(endpoint['clientBridge'])
                async def handshake():
                    bridge=module.Bridge('127.0.0.1',endpoint['port'],ssl.create_default_context(cafile=str(cert)))
                    listener=await asyncio.start_server(bridge.accept,'127.0.0.1',0)
                    try:
                        reader,writer=await asyncio.open_connection('127.0.0.1',listener.sockets[0].getsockname()[1])
                        payload=json.dumps({'type':'hello','protocol':4,'format':4,'remoteAuth':endpoint['token'],
                                            'remoteAssets':1}).encode()
                        writer.write(struct.pack('<I',len(payload))+payload); await writer.drain()
                        header=await asyncio.wait_for(reader.readexactly(4),5)
                        hello=json.loads(await reader.readexactly(struct.unpack('<I',header)[0]))
                        self.assertEqual(hello['earthMP']['id'],data['profile'])
                        writer.close(); await writer.wait_closed()
                    finally:
                        listener.close(); await listener.wait_closed(); await bridge.close()
                asyncio.run(handshake())
            finally:
                process.terminate(); process.communicate(timeout=10)
