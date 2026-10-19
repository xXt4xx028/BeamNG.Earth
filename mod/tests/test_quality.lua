local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
dofile(dir .. '/stubs.lua')
local quality = require('beamngEarth/quality')
local q = quality.new()
local function run(seconds, dt, blocked)
  local changes = 0
  for _ = 1, math.ceil(seconds / dt) do if q:update(dt, blocked) then changes = changes + 1 end end
  return changes
end
T.check(q.scale == 1 and q.mode == 'balanced', 'balanced preserves host detail')
T.check(run(30, 0.05) == 0, 'manual profile does not adapt')
T.check(q:setMode('low') and q.scale == 0.7, 'low reduces only the requested visual scale')
T.check(not q:setMode('invalid') and q.mode == 'low', 'invalid mode refused')
q:setMode('auto')
T.check(run(2, 0.05) == 0 and q.scale == 1, 'auto warms up before changing detail')
T.check(run(5, 0.05) == 1 and q.scale == 0.85, 'sustained slow frames lower one step')
T.check(run(8, 0.05) == 0, 'cooldown prevents rapid changes')
T.check(run(30, 0.05) == 2 and q.scale == 0.55, 'bounded minimum after sustained pressure')
T.check(run(30, 0.05) == 0, 'cannot lower below the negotiated minimum')
T.check(run(10, 1 / 60) == 0, 'short fast interval does not immediately restore detail')
T.check(run(20, 1 / 60) == 1 and q.scale == 0.7, 'slow recovery restores one step')
q:setMode('balanced'); q:setMode('auto')
T.check(run(30, 0.05, true) == 0 and q.scale == 1, 'loading and paused frames do not lower quality')
for _ = 1, 100 do q:update(0.6, false) end
T.check(q.scale == 1, 'isolated long stalls are excluded')
T.check(run(30, 1 / 30) == 0 and q.scale == 1, 'stable target frame rate keeps host detail')
T.done('test_quality')
