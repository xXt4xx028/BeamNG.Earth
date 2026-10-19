"""Real TCP auth/admission and generated-file delivery; synthetic geographic input."""
import asyncio
import base64
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import cache
import earthd
import protocol
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

    async def connect(self,token=None):
        r,w=await asyncio.open_connection('127.0.0.1',self.port)
        self.clients.append((r,w))
        w.write(protocol.encode({'type':'hello','protocol':4,'format':4,'remoteAssets':1,
                                 'remoteAuth':self.world.remote_token if token is None else token}))
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

    async def test_auth_failure_does_not_consume_slot(self):
        for token in ['wrong','\u00f1'*64]:
            r,w=await self.connect(token)
            self.assertEqual(await asyncio.wait_for(r.read(),3),b'')
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
