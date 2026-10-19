-- Geographic envelope for BeamMP packets. Pure Lua, independent of the game.
local geo = require('beamngEarth/geodesy')
local M = { PROTOCOL = 1 }

local function finite(n)
  return type(n) == 'number' and n == n and math.abs(n) < math.huge
end
M.finite = finite

local function values(v, n)
  if type(v) ~= 'table' then return nil end
  local out, names = {}, { 'x', 'y', 'z', 'w' }
  for i = 1, n do
    out[i] = v[i] or v[names[i]]
    if not finite(out[i]) then return nil end
  end
  return out
end

local function shape(old, v)
  if old.x ~= nil then return { x = v[1], y = v[2], z = v[3], w = v[4] } end
  return v
end

function M.envelope(anchor, profile)
  return { protocol = M.PROTOCOL, lat = anchor.lat, lon = anchor.lon, profile = profile }
end

function M.validEnvelope(e, profile)
  return type(e) == 'table' and e.protocol == M.PROTOCOL and e.profile == profile
    and finite(e.lat) and math.abs(e.lat) <= 90 and finite(e.lon) and math.abs(e.lon) <= 180
end

-- Preserve the packet's array/object representation (BeamMP resets use objects).
-- BeamNG quaternion multiplication applies the left operand first.
function M.convert(packet, target, profile)
  if type(packet) ~= 'table' or not M.validEnvelope(packet.earth, profile) then
    return nil, 'missing or incompatible geographic envelope'
  end
  local p, q = values(packet.pos, 3), values(packet.rot, 4)
  if not p or not q then return nil, 'invalid position or rotation' end
  local norm = math.sqrt(q[1]^2 + q[2]^2 + q[3]^2 + q[4]^2)
  if norm < 1e-8 then return nil, 'zero quaternion' end
  for i = 1, 4 do q[i] = q[i] / norm end
  local source = geo.newAnchor(packet.earth.lat, packet.earth.lon)
  local xf = source:transformTo(target)
  local out = {}
  for k, v in pairs(packet) do out[k] = v end
  out.pos = shape(packet.pos, { xf:apply(p[1], p[2], p[3]) })
  local bx, by, bz, bw = xf:beamngQuat()
  out.rot = shape(packet.rot, { geo.quatMul(q[1], q[2], q[3], q[4], bx, by, bz, bw) })
  for _, key in ipairs({ 'vel', 'rvel' }) do
    if packet[key] ~= nil then
      local v = values(packet[key], 3)
      if not v then return nil, 'invalid ' .. key end
      out[key] = shape(packet[key], { xf:rotate(v[1], v[2], v[3]) })
    end
  end
  out.earth = nil
  return out
end

function M.position(packet)
  return values(packet and packet.pos, 3)
end

function M.rotation(packet)
  return values(packet and packet.rot, 4)
end

function M.nearPlayer(packet, player, radius)
  local p = M.position(packet)
  if not p or not player then return false end
  return (p[1] - player.x)^2 + (p[2] - player.y)^2 + (p[3] - player.z)^2 <= radius^2
end

-- Never spawn a remote vehicle beyond the currently loaded physics block.
-- Its owner continues simulation on its own computer. Hysteresis is provided
-- by the caller's different entry/exit margins.
function M.inBlock(packet, block, samples, square, margin)
  local p = M.position(packet)
  if not p or not block then return false end
  local half = samples * square / 2
  return p[1] >= block.cx - half + margin and p[1] <= block.cx + half - square - margin
    and p[2] >= block.cy - half + margin and p[2] <= block.cy + half - square - margin
end

return M
