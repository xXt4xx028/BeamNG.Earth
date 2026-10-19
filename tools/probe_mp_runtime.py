"""Check isolated Lua modules and binary VFS in a running BeamNG MCP session.

Does not install the mod, register hooks, change the level or move vehicles.
Creates one small temporary file and removes it. This is not an FPS benchmark.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from urllib.error import URLError

import mcp

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/beamng_earth/lua/ge/extensions/beamngEarth'


def literal(text):
    equals = ''
    while ']' + equals + ']' in text:
        equals += '='
    return '[' + equals + '[' + text + ']' + equals + ']'


def probe():
    before = json.loads(mcp.call('get_status'))
    path = '/temp/beamngEarth/alpha5_probe_' + uuid.uuid4().hex + '.bin'
    source = '''
local function module(source, req)
  local fn, err = loadstring(source, '@earth_alpha5_isolated_probe')
  assert(fn, err)
  setfenv(fn, setmetatable({require=req}, {__index=_G}))
  return fn()
end
local sw = module(STOPWATCH_SOURCE, require)
local governor = module(GOVERNOR_SOURCE, function(name)
  if name == 'beamngEarth/stopwatch' then return sw end
  return require(name)
end)
local quality = module(QUALITY_SOURCE, require).new()
local imports = {}
for _, tick in ipairs({2,4,8,20}) do
  local t, count = 0, 0
  local g = governor.new({clock=function() return t end})
  for _=1,600 do
    t = t + 1000/60
    g:beginFrame(true,1000/60)
    g:chargeEngine(tick)
    if g:try('cdae') then g:charge('cdae',4); count=count+1 end
  end
  assert(count > 200, 'normal tick starved imports')
  imports[tostring(tick)] = count
end
quality:setMode('auto')
for _=1,1000 do quality:update(0.05,false) end
assert(quality.scale == 0.55, 'adaptive outer LOD failed')
local bytes = string.char(0,1,2,13,10,255,128,0)..string.rep('Earth',512)
FS:directoryCreate('/temp/beamngEarth')
local ok, err = pcall(function()
  writeFile(PROBE_PATH, bytes)
  assert(readFile(PROBE_PATH) == bytes, 'binary VFS mismatch')
end)
FS:removeFile(PROBE_PATH)
assert(ok,err)
return jsonEncode({isolatedModules=true, importsByNormalTickMs=imports,
  autoMinimum=quality.scale, binaryVfsBytes=#bytes, temporaryFileRemoved=not FS:fileExists(PROBE_PATH),
  fpsMeasured=false, note='No hooks or level changes; logic probe only'})
'''
    for marker, value in [('STOPWATCH_SOURCE', (LUA / 'stopwatch.lua').read_text(encoding='utf-8')),
                          ('GOVERNOR_SOURCE', (LUA / 'governor.lua').read_text(encoding='utf-8')),
                          ('QUALITY_SOURCE', (LUA / 'quality.lua').read_text(encoding='utf-8')),
                          ('PROBE_PATH', path)]:
        source = source.replace(marker, literal(value))
    result = json.loads(mcp.call('run_lua', {'code': source}))
    after = json.loads(mcp.call('get_status'))
    return {'at': datetime.now(timezone.utc).isoformat(), 'version': (ROOT / 'VERSION').read_text().strip(),
            'levelBefore': before['level'], 'levelAfter': after['level'], 'result': result,
            'vehicleCountBefore': before['vehicleCount'], 'vehicleCountAfter': after['vehicleCount'],
            'earthDriveMeasured': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        result = json.dumps(probe(), indent=2)
    except URLError:
        parser.exit(1, 'BeamNG MCP no disponible en localhost:29292. Abre el juego y activa MCP para la prueba.\n')
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result + '\n', encoding='utf-8')
    print(result)
