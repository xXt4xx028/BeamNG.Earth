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
