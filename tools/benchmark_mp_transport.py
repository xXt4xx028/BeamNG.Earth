"""Repeatable CPU/wire-size microbenchmark; not a game FPS or Internet benchmark."""
import argparse
import asyncio
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import time
import platform

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import remoteassets


class CountingWriter:
    def __init__(self): self.bytes=0
    def write(self,data): self.bytes+=len(data)
    async def drain(self): pass


async def transfer(user,binary,players=8):
    store=remoteassets.SharedFiles()
    path=Path(user)/'temp/beamngEarth/benchmark/terrain.ter'
    store.read(path) # same warm asset cache in both cases
    senders=[remoteassets.Sender(CountingWriter(),user,store=store,binary=binary) for _ in range(players)]
    message={'type':'terrain_ready','ter':'/temp/beamngEarth/benchmark/terrain.ter'}
    wall=time.perf_counter()
    await asyncio.gather(*(sender.deliver(message) for sender in senders))
    return {'wallSeconds':time.perf_counter()-wall,
            'wireBytes':sum(sender.wire_bytes for sender in senders),'players':players}


def framing_bench(source,repeats,iterations):
    from lupa.luajit21 import LuaRuntime
    lua=LuaRuntime()
    lua.globals().framing=lua.execute(source)
    measure=lua.eval('''function(iterations)
      local frames={}
      for i=1,64 do frames[i]=framing.encode(string.char(i)..string.rep('x',48*1024-1)) end
      local stream=table.concat(frames)
      local total=0
      for iteration=1,iterations do
        local r=framing.newReassembler(); r:feed(stream)
        while true do local p=r:pop(); if not p then break end; total=total+#p end
      end
      return total
    end''')
    measure(1)
    samples=[]
    for _ in range(repeats):
        start=time.perf_counter()
        assert measure(iterations)==iterations*64*48*1024
        samples.append(time.perf_counter()-start)
    return {'medianSeconds':statistics.median(samples),'iterations':iterations,
            'bytesPerIteration':64*48*1024}


def run(args):
    with tempfile.TemporaryDirectory() as user:
        path=Path(user)/'temp/beamngEarth/benchmark/terrain.ter'
        path.parent.mkdir(parents=True)
        path.write_bytes(random.Random(731).randbytes(4*1024*1024))
        samples={False:[],True:[]}
        for _ in range(args.repeats):
            for binary in (False,True):
                samples[binary].append(asyncio.run(transfer(user,binary)))
        result={'scope':'Synthetic serialization and LuaJIT framing only; excludes TLS, bandwidth caps, VFS, generation and game FPS.',
                'environment':{'platform':platform.platform(),'python':sys.version,'repeats':args.repeats,
                               'assetBytes':4*1024*1024,'seed':731,'cache':'warm'},
                'transfer':{}}
        for mode,binary in [('base64',False),('binary',True)]:
            result['transfer'][mode]={key:statistics.median(s[key] for s in samples[binary])
                                     for key in samples[binary][0]}
    path='mod/beamng_earth/lua/ge/extensions/beamngEarth/framing.lua'
    old=subprocess.check_output(['git','show',args.baseline+':'+path],cwd=ROOT).decode('utf-8')
    result['baselineCommit']=subprocess.check_output(['git','rev-parse',args.baseline],cwd=ROOT,text=True).strip()
    result['framing']={'before':framing_bench(old,args.repeats,args.iterations),
                       'after':framing_bench((ROOT/path).read_text(encoding='utf-8'),args.repeats,args.iterations)}
    result['reductions']={
        'wirePercent':100*(1-result['transfer']['binary']['wireBytes']/result['transfer']['base64']['wireBytes']),
        'senderTimePercent':100*(1-result['transfer']['binary']['wallSeconds']/result['transfer']['base64']['wallSeconds']),
        'framingTimePercent':100*(1-result['framing']['after']['medianSeconds']/result['framing']['before']['medianSeconds'])}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='54bae46')
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--iterations',type=int,default=20)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.repeats<1 or args.iterations<1: parser.error('counts must be positive')
    result=run(args)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
