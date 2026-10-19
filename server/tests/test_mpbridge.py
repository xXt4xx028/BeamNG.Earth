"""Two independent Lua clients + the real EarthSync resource, with JSON packet relay.

Mocks engine/native BeamMP calls, not the geographic bridge or handshake resource.
This is not a live game test. Optional dev dependency: lupa.
"""
import json
from pathlib import Path
import unittest

try:
    from lupa.luajit21 import LuaRuntime, lua_type
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
PROFILE = 'a' * 64


def codecs(lua):
    def to_lua(value):
        if isinstance(value, dict):
            return lua.table_from({k: to_lua(v) for k, v in value.items()})
        if isinstance(value, list):
            return lua.table_from([to_lua(v) for v in value])
        return value

    def from_lua(value):
        if lua_type(value) == 'table':
            keys = list(value.keys())
            if keys and all(isinstance(k, (int, float)) for k in keys) and set(keys) == set(range(1, len(keys) + 1)):
                return [from_lua(value[i]) for i in range(1, len(keys) + 1)]
            return {k: from_lua(value[k]) for k in keys}
        return value

    encode = lambda value: json.dumps(from_lua(value), separators=(',', ':'), allow_nan=False)
    decode = lambda value: to_lua(json.loads(value))
    lua.globals().jsonEncode = encode
    lua.globals().jsonDecode = decode
    return encode, decode


@unittest.skipIf(LuaRuntime is None, 'optional lupa not installed')
class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.clients, self.sent, self.positions, self.vehicles = {}, {}, {}, {}
        self.server = LuaRuntime(unpack_returned_tuples=True)
        encode, decode = codecs(self.server)
        self.server.globals().Util = self.server.table_from({'JsonEncode': encode, 'JsonDecode': decode})
        self.server.globals().MP = self.server.table_from({
            'RegisterEvent': lambda *args: None,
            'SendChatMessage': lambda *args: None,
            'TriggerClientEvent': self.reply,
        })
        self.server.execute((ROOT / 'beammp/Resources/Server/EarthSync/main.lua').read_text())
        self.server.globals().EarthSync_init()

    def reply(self, player, name, raw):
        # BeamMP separates event names from payload at the first colon.
        self.assertNotIn(':', name)
        self.clients[player].globals().handlers[name](raw)

    def client(self, player, lat, lon):
        lua = self.clients[player] = LuaRuntime(unpack_returned_tuples=True)
        codecs(lua)
        self.sent[player], self.positions[player], self.vehicles[player] = [], [], []
        lua.globals().package.path = (ROOT / 'mod/beamng_earth/lua/ge/extensions/?.lua').as_posix() + ';' + lua.globals().package.path
        lua.execute('''
          handlers = {}
          function AddEventHandler(name, fn) handlers[name] = fn end
          function RemoveEventHandler(name) handlers[name] = nil end
          settings = {getValue=function(_, default) return default end, setValue=function() end}
          MPCoreNetwork = {isMPSession=function() return true end}
        ''')
        lua.globals().MPConfig = lua.table_from({'getPlayerServerID': lambda: player})
        lua.globals().send_py = self.sent[player].append
        lua.globals().position_py = self.positions[player].append
        lua.globals().vehicle_py = self.vehicles[player].append
        lua.execute('''
          MPGameNetwork = {send=function(raw) send_py(raw) end}
          positionGE = {handle=function(raw) position_py(raw) end,
            setPositionRotationVelocity=function() end, posSmoother={}}
          MPVehicleGE = {handle=function(raw) vehicle_py(raw) end, onPlayerLeft=function() end}
        ''')

        def trigger(name, raw):
            event, payload = (name + ':' + raw).split(':', 1)
            self.assertEqual(event, 'EarthMPHello')
            self.server.globals().EarthSync_hello(player, payload)

        lua.globals().TriggerServerEvent = trigger
        lua.execute('geo=require("beamngEarth/geodesy"); bridge=require("beamngEarth/multiplayer")')
        lua.globals().state = lua.eval('function(lat,lon,profile) return {inOurLevel=true,active=true,'
            'anchor=geo.newAnchor(lat,lon),block={cx=0,cy=0},player={x=0,y=0,z=2200},'
            'mpBlockSize=512,mpProfile={id=profile}} end')(lat, lon, PROFILE)
        lua.execute('bridge.update(state, 3)')
        self.assertTrue(lua.globals().bridge.status().ready)
        return lua

    def emit(self, lua, packet):
        lua.globals().MPGameNetwork.send(packet)

    def spawn(self, source, target):
        data = {'pos': [100, 0, 2200], 'rot': [0, 0, 0, 1], 'vid': 42, 'jbm': 'pickup', 'vcf': {}}
        self.emit(self.clients[source], 'Os:0:' + json.dumps(data))
        encoded = self.sent[source][-1].split(':', 2)[2]
        native = f'USER:Player {source}:{source}-0:{encoded}'
        self.assertEqual(self.server.globals().EarthSync_spawn(source, 0, native), 0)
        self.clients[target].globals().MPVehicleGE.handle('s:' + native)

    def pose(self, source, target):
        data = {'pos': [100, 0, 2200], 'rot': [0, 0, 0, 1], 'vel': [30, 5, 0],
                'rvel': [0, 0, 0.1], 'tim': 5, 'ping': 0.02}
        self.emit(self.clients[source], f'Zp:{source}-0:' + json.dumps(data))
        native = self.sent[source][-1]
        self.clients[target].globals().positionGE.handle(native[1:])

    def test_separate_origins_and_independent_return(self):
        a = self.client(1, 19.4326, -99.1332)
        b = self.client(2, 19.4426, -99.1332)
        self.spawn(1, 2)
        self.pose(1, 2)
        b.execute('bridge.update(state, 0.1)')
        self.assertEqual(len(self.vehicles[2]), 0, 'far owner is not instantiated outside physics terrain')
        # Only B travels. A's map stays at its previous origin.
        b.execute('bridge.beginFrameChange(); state.anchor=geo.newAnchor(19.4326,-99.1332); bridge.update(state,0.6)')
        self.assertEqual(a.globals().state.anchor.lat, 19.4326)
        self.assertEqual(b.globals().bridge.status().activeVehicles, 1)
        payload = json.loads(self.positions[2][-1].split(':', 2)[2])
        self.assertAlmostEqual(payload['pos'][0], 100, places=6)
        self.assertAlmostEqual(payload['pos'][1], 0, places=6)
        self.assertNotIn('earth', payload, 'native prediction sees receiver-local coordinates')

    def test_nearby_players_with_different_origins(self):
        self.client(1, 19.4326, -99.1332)
        b = self.client(2, 19.4336, -99.1332)
        self.spawn(1, 2)
        self.pose(1, 2)
        b.execute('bridge.update(state,0.1)')
        payload = json.loads(self.positions[2][-1].split(':', 2)[2])
        self.assertLess(payload['pos'][1], -100)
        self.assertGreater(payload['pos'][1], -120)
        self.assertEqual(payload['tim'], 5)
        self.assertAlmostEqual(sum(v*v for v in payload['vel']), 925, places=5)
