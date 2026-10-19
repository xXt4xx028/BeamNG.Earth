local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local geo = require('beamngEarth/geodesy')
local space = require('beamngEarth/mpspace')
local source = geo.newAnchor(19.4326, -99.1332)
local function packet(a)
  return { pos = {100, 0, 2200}, rot = {0, 0, 0, 1}, vel = {30, 10, -2}, rvel = {0.1, 0.2, 0.3},
    tim = 7, ping = 0.05, earth = space.envelope(a, 'profile') }
end
for _, coords in ipairs({ {19.4426, -99.1332}, {90, 0}, {-90, 180}, {0, 179.999}, {0, -179.999} }) do
  local target = geo.newAnchor(coords[1], coords[2])
  local p = packet(source)
  local q = assert(space.convert(p, target, 'profile'))
  T.check(q.earth == nil and p.earth ~= nil, 'conversion does not mutate input envelope')
  T.check(q.tim == p.tim and q.ping == p.ping, 'prediction timing preserved')
  q.earth = space.envelope(target, 'profile')
  local back = assert(space.convert(q, source, 'profile'))
  -- q and -q represent the same orientation (notably around the antimeridian).
  if back.rot[4] < 0 then for i = 1, 4 do back.rot[i] = -back.rot[i] end end
  for _, key in ipairs({'pos', 'rot', 'vel', 'rvel'}) do
    for i, v in ipairs(p[key]) do T.near(back[key][i], v, 1e-7, key .. ' geographic roundtrip') end
  end
  -- Orientation and vector rotation must describe the same physical heading.
  local bx, by, bz = geo.beamngRotate(q.rot[1], q.rot[2], q.rot[3], q.rot[4], 1, 0, 0)
  local x, y, z = source:transformTo(target):rotate(1, 0, 0)
  T.near(bx, x, 1e-10, 'heading x'); T.near(by, y, 1e-10, 'heading y'); T.near(bz, z, 1e-10, 'heading z')
end
local reset = {pos = {x=10,y=20,z=30}, rot={x=0,y=0,z=0,w=1}, earth=space.envelope(source,'profile')}
local out = assert(space.convert(reset,source,'profile'))
T.near(out.pos.x,10,1e-9,'reset object position'); T.near(out.rot.w,1,1e-9,'reset object quaternion')
T.check(not space.convert(packet(source),source,'wrong'),'profile mismatch rejected')
local bad=packet(source); bad.pos[1]=0/0
T.check(not space.convert(bad,source,'profile'),'nonfinite position rejected')
bad=packet(source); bad.earth.lat=91
T.check(not space.convert(bad,source,'profile'),'invalid latitude rejected')
bad=packet(source); bad.rot={0,0,0,0}
T.check(not space.convert(bad,source,'profile'),'zero quaternion rejected')
T.check(space.inBlock({pos={0,0,0}},{cx=0,cy=0},512,2,80),'inside physics block')
T.check(not space.inBlock({pos={500,0,0}},{cx=0,cy=0},512,2,80),'outside safety margin')
T.check(not space.inBlock({pos={0,0,0}},nil,512,2,80),'unloaded block rejected')
T.check(not space.nearPlayer({pos={0,0,-12000000}},{x=0,y=0,z=0},2000),'antipodal vehicle below origin is culled')
T.check(not space.nearPlayer({pos={0,0,0}},nil,2000),'player position required for relevance')
T.done('mpspace')
