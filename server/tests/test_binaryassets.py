"""Python sender -> Lua framing/asset receiver with binary-safe separate runtime."""
import asyncio
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
import remoteassets

try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    LuaRuntime=None


@unittest.skipIf(LuaRuntime is None,'optional lupa not installed')
class BinaryAssetsTest(unittest.IsolatedAsyncioTestCase):
    async def test_python_binary_frames_reassemble_in_real_lua_receiver(self):
        lua=LuaRuntime(encoding=None)
        files={}
        lua.execute("FS={directoryExists=function() return false end,directoryCreate=function() end}")
        lua.globals()[b'writeFile']=lambda path,body: files.__setitem__(path,body)
        lua.globals()[b'readFile']=files.get
        receiver=lua.execute((ROOT/'mod/beamng_earth/lua/ge/extensions/beamngEarth/assets.lua').read_bytes())
        framing=lua.execute((ROOT/'mod/beamng_earth/lua/ge/extensions/beamngEarth/framing.lua').read_bytes())
        rx=framing[b'newReassembler']()
        def value(v):
            if isinstance(v,dict): return lua.table_from({k.encode():value(x) for k,x in v.items()})
            if isinstance(v,str): return v.encode()
            return v
        class Writer:
            def __init__(self): self.frames=[]
            def write(self,frame): self.frames.append(frame)
            async def drain(self): pass
        with tempfile.TemporaryDirectory() as user:
            path=Path(user)/'temp/beamngEarth/test/terrain.ter'; path.parent.mkdir(parents=True)
            body=random.Random(900).randbytes(1024*1024)
            path.write_bytes(body)
            writer=Writer(); sender=remoteassets.Sender(writer,user,binary=True)
            await sender.deliver({'type':'terrain_ready','ter':'/temp/beamngEarth/test/terrain.ter'})
            stream=b''.join(writer.frames)
            for start in range(0,len(stream),7777):
                rx[b'feed'](rx,stream[start:start+7777])
                while (payload:=rx[b'pop'](rx)) is not None:
                    if payload.startswith(remoteassets.BINARY_PREFIX):
                        self.assertIs(receiver[b'receiveBinary'](payload),True)
                    else:
                        message=json.loads(payload)
                        if message['type']=='terrain_ready':
                            self.assertEqual(files[message['ter'].encode()],body)
                        else:
                            self.assertIs(receiver[b'receive'](value(message)),True)
            self.assertEqual(rx[b'buffered'](rx),0)
