"""Real localhost -> TLS -> server bytes; no BeamNG/BeamMP engine is mocked as real."""
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
import os
import subprocess

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import earth_client_bridge


def certificate(root):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Earth loopback test')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
          .not_valid_after(now+timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
          .sign(key,hashes.SHA256()))
    cert_file=Path(root)/'cert.pem'; key_file=Path(root)/'key.pem'
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return cert_file,key_file


class ClientBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            import cryptography
        except ImportError:
            self.skipTest('optional test dependency cryptography not installed')
        self.tmp=tempfile.TemporaryDirectory()
        self.cert,self.key=certificate(self.tmp.name)
        self.server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context.load_cert_chain(self.cert,self.key)
        self.upstream_tasks=set()
        async def echo(reader,writer):
            task=asyncio.current_task(); self.upstream_tasks.add(task)
            try:
                while data:=await reader.read(65536):
                    writer.write(data); await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                self.upstream_tasks.discard(task)
        self.server=await asyncio.start_server(echo,'127.0.0.1',0,ssl=self.server_context)
        self.context=ssl.create_default_context(cafile=str(self.cert))
        self.bridge=earth_client_bridge.Bridge('127.0.0.1',self.server.sockets[0].getsockname()[1],self.context)
        self.listener=await asyncio.start_server(self.bridge.accept,'127.0.0.1',0)
        self.port=self.listener.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.listener.close(); await self.listener.wait_closed()
        await self.bridge.close()
        self.server.close(); await self.server.wait_closed()
        if self.upstream_tasks: await asyncio.gather(*self.upstream_tasks,return_exceptions=True)
        self.tmp.cleanup()

    async def test_binary_roundtrip_and_connection_cleanup(self):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
        payload=bytes(range(256))*4096
        writer.write(payload); await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)),5),payload)
        writer.close(); await writer.wait_closed()
        for _ in range(100):
            if self.bridge.active == 0: break
            await asyncio.sleep(.01)
        self.assertEqual(self.bridge.active,0)

    async def test_untrusted_certificate_is_rejected(self):
        self.bridge.context=ssl.create_default_context()
        reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
        self.assertEqual(await asyncio.wait_for(reader.read(),5),b'')
        writer.close(); await writer.wait_closed()

    async def test_packaged_executable_when_supplied(self):
        executable=os.environ.get('EARTH_BRIDGE_EXE')
        if not executable:
            self.skipTest('set EARTH_BRIDGE_EXE to test a compiled bridge')
        import socket
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
        process=await asyncio.create_subprocess_exec(executable,'--host','127.0.0.1',
            '--port',str(self.server.sockets[0].getsockname()[1]),'--local-port',str(port),
            '--ca-file',str(self.cert),'--once',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,
            **({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}))
        try:
            ready=await asyncio.wait_for(process.stdout.readline(),15)
            self.assertIn(b'listening',ready)
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            payload=bytes(range(256))*4096
            writer.write(payload); await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)),10),payload)
            writer.close(); await writer.wait_closed()
            self.assertEqual(await asyncio.wait_for(process.wait(),10),0)
        finally:
            if process.returncode is None:
                process.terminate(); await process.wait()


if __name__ == '__main__': unittest.main()
