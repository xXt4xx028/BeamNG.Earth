"""Real TCP auth/admission and generated-file delivery; synthetic geographic input."""
import asyncio
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import cache
import earthd
import protocol
import remoteassets
from test_server import FakeDem


class CentralServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.disk=cache.Cache(str(Path(self.tmp.name)/'cache'),40,start=False)
        self.world=earthd.Server(self.tmp.name,str(Path(self.tmp.name)/'cache'),imagery=None,
                                 block=512,cells=32,cache=self.disk)
        self.world.dem=FakeDem()
        self.world.remote_assets=True
        self.world.max_clients=8
        self.world.remote_token='a'*64
        self.tasks=[]; self.clients=[]
        def connected(reader,writer):
            self.tasks.append(asyncio.create_task(earthd.Connection(self.world,reader,writer).run()))
        self.listener=await asyncio.start_server(connected,'127.0.0.1',0)
        self.port=self.listener.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        for r,w in self.clients: w.close()
        for r,w in self.clients:
            try: await w.wait_closed()
            except ConnectionError: pass
        self.listener.close(); await self.listener.wait_closed()
        if self.tasks:
            await asyncio.wait_for(asyncio.gather(*self.tasks,return_exceptions=True),10)
        self.world.tile_pool.shutdown(wait=True)
        self.world.hm_pool.shutdown(wait=True)
        self.disk.close()
        self.tmp.cleanup()

    async def connect(self,token=None,binary=False):
        r,w=await asyncio.open_connection('127.0.0.1',self.port)
        self.clients.append((r,w))
        w.write(protocol.encode({'type':'hello','protocol':4,'format':4,'remoteAssets':1,
                                 'remoteAuth':self.world.remote_token if token is None else token,
                                 'remoteAssetBinary':1 if binary else 0}))
        await w.drain()
        return r,w

    async def until(self,reader,kind):
        files={}; pending={}
        while True:
            msg=await asyncio.wait_for(protocol.read_message(reader),15)
            self.assertIsNotNone(msg)
            if msg['type']=='asset_begin': pending[msg['path']]=bytearray()
            elif msg['type']=='asset_chunk':
                self.assertEqual(len(pending[msg['path']]),msg['offset'])
                pending[msg['path']].extend(base64.b64decode(msg['data']))
            elif msg['type']=='asset_end': files[msg['path']]=bytes(pending.pop(msg['path']))
            elif msg['type']==kind:
                self.assertFalse(pending,'control is delivered after complete files')
                return msg,files

    async def test_eight_clients_share_profile_and_cache_ninth_rejected(self):
        ids=[]
        for _ in range(8):
            r,w=await self.connect()
            hello,_=await self.until(r,'hello')
            ids.append(hello['earthMP']['id'])
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(len(self.world.connections),8)
        r,w=await self.connect()
        full=await asyncio.wait_for(protocol.read_message(r),3)
        self.assertIn('full',full['text'])
        self.assertEqual(len(self.world.connections),8)
        # A player's settings page cannot clear or resize the shared 40 GB cache.
        await self.until(self.clients[0][0],'cache') # consume initial hello's usage report
        self.clients[0][1].write(protocol.encode({'type':'cache','capGb':1,'clear':True}))
        await self.clients[0][1].drain()
        await self.until(self.clients[0][0],'cache')
        self.assertEqual(self.disk.cap,40*10**9)

    async def test_per_client_quality_is_bounded_and_preserves_near_tiles(self):
        for _ in range(2):
            reader,writer=await self.connect()
            hello,_=await self.until(reader,'hello')
            self.assertTrue(hello['adaptiveLod'])
        one,two=tuple(self.world.connections)
        base_near=dict(self.world.near_radii)
        layout=self.world.layout
        import farfield
        reference,_=farfield.select(73,97,kfun=one.visual_k,radius=self.world.radius,
                                   min_level=self.world.min_level,radii=base_near,layout=layout)
        # Use the authenticated TCP connection for a real client preference.
        writer=self.clients[0][1]
        writer.write(protocol.encode({'type':'quality','lodScale':.55})); await writer.drain()
        for _ in range(100):
            if any(c.visual_scale==.55 for c in self.world.connections): break
            await asyncio.sleep(.01)
        self.assertEqual(sorted(c.visual_scale for c in self.world.connections),[.55,1])
        changed=next(c for c in self.world.connections if c.visual_scale==.55)
        selected,_=farfield.select(73,97,kfun=changed.visual_k,radius=self.world.radius,
                                  min_level=self.world.min_level,radii=base_near,layout=layout)
        exact=lambda tiles:{k for k,t in tiles.items() if t.level==layout.exact_level}
        self.assertEqual(exact(reference),exact(selected))
        self.assertLess(len(selected),len(reference))
        self.assertEqual(self.world.near_radii,base_near)
        for value in (True,None,'low',.1,1.1,float('nan'),float('inf')):
            changed.on_quality({'lodScale':value})
            self.assertEqual(changed.visual_scale,.55)
        with patch('earthd.time.monotonic',return_value=changed.last_quality_at+.5):
            changed.on_quality({'lodScale':1})
            self.assertEqual(changed.visual_scale,.55,'rapid edits cannot repeatedly rebuild LOD')
        with patch('earthd.time.monotonic',return_value=changed.last_quality_at+2):
            changed.on_quality({'lodScale':1})
            self.assertEqual(changed.visual_scale,1)
        # Screen-space refinement must not silently undo the lower distance detail.
        changed.visual_scale=.55; changed.active=1; changed.cam_aid=1
        changed.cam={'x':0,'y':0,'z':2000,'h':1080,'fovDeg':60}
        self.world.lod_px=2
        self.assertAlmostEqual(changed.view().tau,2/.55)

    async def test_binary_and_legacy_clients_receive_identical_generated_terrain(self):
        for binary in (True,False):
            reader,writer=await self.connect(binary=binary)
            await self.until(reader,'hello')
            writer.write(protocol.encode({'type':'prepare_anchor','requestId':1,'lat':19.4326,'lon':-99.1332,'cx':0,'cy':0}))
            await writer.drain()
            pending=None; files={}; binary_chunks=0
            while True:
                header=await asyncio.wait_for(reader.readexactly(4),15)
                payload=await reader.readexactly(protocol.HEADER.unpack(header)[0])
                if payload.startswith(remoteassets.BINARY_PREFIX):
                    self.assertTrue(binary)
                    self.assertIsNotNone(pending)
                    self.assertEqual(remoteassets.BINARY_HEADER.unpack(payload[5:9])[0],len(pending[1]))
                    pending[1].extend(payload[9:]); binary_chunks+=1
                    continue
                message=protocol.decode_payload(payload)
                if message['type']=='asset_begin': pending=(message['path'],bytearray())
                elif message['type']=='asset_chunk': pending[1].extend(base64.b64decode(message['data']))
                elif message['type']=='asset_end':
                    files[pending[0]]=bytes(pending[1]); pending=None
                elif message['type']=='anchor_ready':
                    self.assertIsNone(pending)
                    height=message['terrain']['heightmap']
                    self.assertEqual(files[height],(Path(self.tmp.name)/height.lstrip('/')).read_bytes())
                    self.assertEqual(binary_chunks>0,binary)
                    break

    async def test_auth_failure_does_not_consume_slot(self):
        for token in ['wrong','\u00f1'*64]:
            r,w=await self.connect(token)
            self.assertEqual(await asyncio.wait_for(r.read(),3),b'')
        self.assertEqual(len(self.world.connections),0)

    async def test_dead_connection_releases_its_slot(self):
        self.world.remote_idle_timeout=.2
        r,w=await self.connect()
        await self.until(r,'hello')
        await asyncio.wait_for(r.read(),3)
        self.assertEqual(len(self.world.connections),0)

    async def test_generated_terrain_arrives_before_ready_at_two_independent_places(self):
        for lat,lon in [(19.4326,-99.1332),(40.7128,-74.0060)]:
            r,w=await self.connect()
            await self.until(r,'hello')
            w.write(protocol.encode({'type':'prepare_anchor','requestId':1,'lat':lat,'lon':lon,'cx':0,'cy':0}))
            await w.drain()
            ready,files=await self.until(r,'anchor_ready')
            self.assertEqual((ready['lat'],ready['lon']),(lat,lon))
            height=ready['terrain']['heightmap']
            self.assertIn(height,files)
            self.assertEqual(files[height],(Path(self.tmp.name)/height.lstrip('/')).read_bytes())
        self.assertEqual(len(self.world.anchors),2)

    async def test_cleanup_preserves_all_eight_players_origins_and_terrain(self):
        from collections import deque
        class Peer: pass
        peers=[]
        for i in range(8):
            anchor=self.world.new_anchor(10+i,20)
            anchor.first_terrain=(0,0)
            self.world.anchors[anchor.id]=anchor
            peer=Peer(); peer.active=anchor.id; peer.held=set()
            peer.block=self.world.layout.block_at(0,0); peer.protected_terrain=deque()
            peers.append(peer)
            self.world.hm[(anchor.id,0,0)]={}
        self.world.connections=set(peers)
        for i in range(earthd.HM_CACHE+10): self.world.hm[(100,i*128,0)]={}
        self.world.evict_heightmaps()
        self.assertTrue(all((p.active,0,0) in self.world.hm for p in peers))
        self.world.prune(9)
        self.assertEqual(set(self.world.anchors),set(range(1,9)))
        self.world.connections.remove(peers[0])
        self.world.prune(9)
        self.assertNotIn(1,self.world.anchors)
        self.assertEqual(set(self.world.anchors),set(range(2,9)))

    async def test_host_release_is_forwarded_to_the_clients_temporary_files(self):
        r,w=await self.connect()
        await self.until(r,'hello')
        path=Path(self.tmp.name)/'temp'/'beamngEarth'/'test-release.cdae'
        path.write_bytes(b'generated geometry')
        connection=next(iter(self.world.connections))
        connection.send({'type':'probe','path':'/temp/beamngEarth/test-release.cdae'})
        _,files=await self.until(r,'probe')
        self.assertEqual(files['/temp/beamngEarth/test-release.cdae'],b'generated geometry')
        self.world._remove(str(path))
        released,_=await self.until(r,'asset_delete')
        self.assertEqual(released['path'],'/temp/beamngEarth/test-release.cdae')
        self.assertFalse(path.exists())
