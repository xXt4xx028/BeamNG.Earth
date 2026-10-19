import asyncio
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import protocol
import remoteassets
import cache


class Writer:
    def __init__(self): self.frames=[]; self.closed=False
    def write(self,data): self.frames.extend(protocol.Decoder().feed(data))
    async def drain(self): pass
    def close(self): self.closed=True


class RemoteAssetsTest(unittest.IsolatedAsyncioTestCase):
    async def test_negotiated_binary_stream_is_exact_and_smaller(self):
        class RawWriter:
            def __init__(self): self.frames=[]
            def write(self,data): self.frames.append(data)
            async def drain(self): pass
        with tempfile.TemporaryDirectory() as user:
            path=Path(user)/'temp/beamngEarth/shared/terrain.ter'
            path.parent.mkdir(parents=True)
            body=bytes(range(256))*4096
            path.write_bytes(body)
            message={'type':'terrain_ready','ter':'/temp/beamngEarth/shared/terrain.ter'}
            raw=RawWriter(); binary=remoteassets.Sender(raw,user,binary=True)
            old=RawWriter(); legacy=remoteassets.Sender(old,user)
            await binary.deliver(message); await legacy.deliver(message)
            assembled=bytearray()
            self.assertEqual(protocol.decode_payload(raw.frames[0][4:])['encoding'],'binary')
            for frame in raw.frames[1:-2]:
                payload=frame[4:]
                self.assertEqual(protocol.HEADER.unpack(frame[:4])[0],len(payload))
                self.assertTrue(payload.startswith(remoteassets.BINARY_PREFIX))
                self.assertEqual(remoteassets.BINARY_HEADER.unpack(payload[5:9])[0],len(assembled))
                assembled.extend(payload[9:])
            self.assertEqual(assembled,body)
            self.assertEqual(protocol.decode_payload(raw.frames[-1][4:]),message)
            self.assertLess(binary.wire_bytes,legacy.wire_bytes*.76)
            for offset,chunk in [(-1,b'x'),(0,b''),(0,b'x'*(remoteassets.CHUNK+1))]:
                with self.assertRaises(ValueError): remoteassets.binary_frame(offset,chunk)

    async def test_eight_senders_share_one_read_and_detect_reused_slot(self):
        with tempfile.TemporaryDirectory() as user:
            path=Path(user)/'temp/beamngEarth/shared/shape.cdae'
            path.parent.mkdir(parents=True); path.write_bytes(b'one shared immutable shape')
            store=remoteassets.SharedFiles(max_bytes=100)
            senders=[remoteassets.Sender(Writer(),user,store=store) for _ in range(8)]
            message={'type':'shape','path':'/temp/beamngEarth/shared/shape.cdae'}
            await asyncio.gather(*(s.deliver(message) for s in senders))
            self.assertEqual((store.reads,store.hits),(1,7))
            old=senders[0].sent[message['path']]
            path.write_bytes(b'reused slot with new bytes')
            await senders[0].deliver(message)
            self.assertNotEqual(senders[0].sent[message['path']],old)
            self.assertLessEqual(store.bytes,100)

    async def test_shared_upload_pacer_serializes_reservations(self):
        from unittest.mock import patch
        pacer=remoteassets.Pacer(1000)
        loop=asyncio.get_running_loop()
        pacer.next=loop.time()+.05
        delays=[]
        async def fake_sleep(delay): delays.append(delay)
        with patch.object(remoteassets.asyncio,'sleep',fake_sleep):
            await pacer.wait(100)
            await pacer.wait(100)
        self.assertEqual(len(delays),2)
        self.assertGreater(delays[1]-delays[0],.09)

    async def test_shared_cache_accounts_for_files_written_by_other_workers(self):
        with tempfile.TemporaryDirectory() as root:
            disk=cache.Cache(root,40,start=False)
            path=Path(root)/'dem'/'worker-written.bin'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'worker data not registered in the parent process')
            remoteassets.reconcile_cache_once(disk)
            self.assertEqual(disk.message()['usedBytes'],path.stat().st_size)
            self.assertEqual(disk.cap,40*10**9)
            disk.close()
    async def test_dependency_delivery_before_control_and_reuse(self):
        with tempfile.TemporaryDirectory() as user:
            root=Path(user)/'temp'/'beamngEarth'/'s'
            root.mkdir(parents=True)
            binary=bytes(range(256))*400
            (root/'shape.cdae').write_bytes(binary)
            (root/'roads.json').write_text(json.dumps({'shape':'/temp/beamngEarth/s/shape.cdae'}))
            msg={'type':'roads_tile','path':'/temp/beamngEarth/s/roads.json'}
            writer=Writer(); sender=remoteassets.Sender(writer,user)
            await sender.deliver(msg)
            self.assertEqual(writer.frames[-1],msg)
            self.assertEqual(writer.frames[0]['path'],'/temp/beamngEarth/s/shape.cdae')
            chunks=[m for m in writer.frames if m['type']=='asset_chunk' and m['path'].endswith('.cdae')]
            self.assertEqual(b''.join(base64.b64decode(m['data']) for m in chunks),binary)
            writer.frames=[]
            await sender.deliver(msg)
            self.assertEqual(writer.frames,[msg],'unchanged assets sent only once per connection')
            (root/'shape.cdae').write_bytes(b'changed pooled slot')
            writer.frames=[]
            await sender.deliver(msg)
            self.assertTrue(any(m['type']=='asset_begin' and m['path'].endswith('.cdae') for m in writer.frames))
            shape='/temp/beamngEarth/s/shape.cdae'
            current=sender.sent[shape]
            writer.frames=[]
            await sender.deliver({'type':'asset_delete','path':shape,'digest':'outdated'})
            self.assertEqual(writer.frames,[],'stale deletion cannot delete reused geometry')
            await sender.deliver({'type':'asset_delete','path':shape,'digest':current})
            self.assertNotIn(shape,sender.sent)
            self.assertEqual(writer.frames[-1]['type'],'asset_delete')

    async def test_no_arbitrary_file_access(self):
        with tempfile.TemporaryDirectory() as user:
            for name in ['/settings/token','/temp/beamngEarth/../secret','/temp/beamngEarth/s/../../secret',
                         '/temp/beamngEarth/s\\secret','/temp/beamngEarth/C:/secret']:
                with self.assertRaises(ValueError): remoteassets.local_path(user,name)

    async def test_bounded_queue_disconnects_slow_reader(self):
        writer=Writer(); sender=remoteassets.Sender(writer,'.',queue_size=1)
        sender.put({'type':'status'}); sender.put({'type':'status'})
        self.assertTrue(writer.closed)

    async def test_missing_dependency_never_announces_ready(self):
        with tempfile.TemporaryDirectory() as user:
            writer=Writer(); sender=remoteassets.Sender(writer,user)
            sender.start(); sender.put({'type':'roads_tile','path':'/temp/beamngEarth/missing.json'})
            for _ in range(100):
                if writer.closed: break
                await asyncio.sleep(.01)
            await sender.close()
            self.assertTrue(writer.closed)
            self.assertEqual(writer.frames,[])
