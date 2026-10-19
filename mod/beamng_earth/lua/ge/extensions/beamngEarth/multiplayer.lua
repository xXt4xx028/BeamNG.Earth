-- Experimental adapter for BeamMP's public GE exports. No BeamMP files are replaced.
-- Spatial messages retain the sender's geographic frame until the receiving PC
-- has terrain ready. Far vehicles are cached as data, rather than simulated.
local space = require('beamngEarth/mpspace')
local M = {}
local st, installed, accepted, profile, session
local originals, wrappers = {}, {}
local remote, outgoing = {}, {}
local timer, fence = 0, 0
local errorText = 'Waiting for BeamMP session'
local MAX_REMOTE, MAX_PENDING = 128, 64
local stats = { sent = 0, received = 0, rejected = 0, culled = 0 }
local savedQueue

local function mpSession()
  return MPCoreNetwork and MPCoreNetwork.isMPSession and MPCoreNetwork.isMPSession()
end

local function ready()
  return accepted and st and st.active and st.anchor and st.block
    and (not st.pending or st.pending.purpose == 'rebase')
    and not st.rebasing and not st.placeFrames and fence <= 0
end

local function decode(raw)
  local ok, data = pcall(jsonDecode, raw)
  if ok and type(data) == 'table' then return data end
end

local function own(id)
  local pid = id and id:match('^(%d+)%-')
  return pid and MPConfig and tonumber(pid) == MPConfig.getPlayerServerID()
end

local function removeLocal(id, record)
  if record.spawned then
    originals.vehicle('d:' .. id) -- BeamMP's receive path suppresses destruction broadcasts.
    record.spawned = false
    stats.culled = stats.culled + 1
  end
end

local function recordFor(id)
  if remote[id] then return remote[id] end
  local count = 0
  for _ in pairs(remote) do count = count + 1 end
  if count >= MAX_REMOTE then stats.rejected = stats.rejected + 1; return nil end
  remote[id] = { dirty = true, edits = {} }
  return remote[id]
end

local function converted(data)
  if not data or not st or not st.anchor then return nil end
  if not data.earth or data.earth.session ~= session then return nil end
  return space.convert(data, st.anchor, profile)
end

local function decorate(raw)
  local kind = raw:sub(1, 2)
  if kind ~= 'Zp' and kind ~= 'Os' and kind ~= 'Or' then return raw end
  local prefix, body = raw:match('^(%a%a:[^:]+:)(%{.*%})$')
  local data = body and decode(body)
  if not data or not ready() then return nil end
  data.earth = space.envelope(st.anchor, profile)
  data.earth.session = session
  return prefix .. jsonEncode(data)
end

local function onSession(raw)
  local msg = decode(raw)
  if not msg or msg.protocol ~= space.PROTOCOL or msg.profile ~= profile then return end
  accepted = msg.accepted == true
  session = accepted and msg.session or nil
  errorText = accepted and 'Geographic sync active (experimental)' or tostring(msg.error or 'World profile rejected')
end

function M.install()
  if installed then return true end
  if not (MPGameNetwork and positionGE and MPVehicleGE and AddEventHandler
    and type(MPGameNetwork.send) == 'function' and type(positionGE.handle) == 'function'
    and type(positionGE.setPositionRotationVelocity) == 'function'
    and type(MPVehicleGE.handle) == 'function') then return false end
  originals.send, originals.position, originals.vehicle = MPGameNetwork.send, positionGE.handle, MPVehicleGE.handle
  originals.correction = positionGE.setPositionRotationVelocity
  originals.playerLeft = MPVehicleGE.onPlayerLeft
  wrappers.send = function(packet)
    if not (st and st.inOurLevel and mpSession()) then return originals.send(packet) end
    local raw = tostring(packet)
    local kind = raw:sub(1, 2)
    if kind == 'Os' and not ready() then
      -- Initial spawns can precede both companion and session handshakes.
      if #outgoing < MAX_PENDING then outgoing[#outgoing + 1] = raw end
      return
    end
    local encoded = decorate(raw)
    if encoded then
      if kind == 'Zp' then stats.sent = stats.sent + 1 end
      return originals.send(encoded)
    end
  end
  wrappers.position = function(raw)
    if not (st and st.inOurLevel and mpSession()) then return originals.position(raw) end
    local id, body = raw:match('^p:(%d+%-%d+):(%{.*%})$')
    if not id or own(id) then return end
    local data = decode(body)
    if not data or not space.validEnvelope(data.earth, profile) or data.earth.session ~= session then
      stats.rejected = stats.rejected + 1; return
    end
    local r = recordFor(id)
    if r then r.pose, r.dirty = data, true; stats.received = stats.received + 1 end
  end
  wrappers.vehicle = function(raw)
    if not (st and st.inOurLevel and mpSession()) then return originals.vehicle(raw) end
    local kind = raw:sub(1, 1)
    if kind == 'd' then
      local id = raw:sub(3)
      remote[id] = nil
      return originals.vehicle(raw)
    end
    local prefix, id, body
    if kind == 's' then
      prefix, id, body = raw:match('^(s:%w+:[%g%s]+:)(%d+%-%d+):(%{.*%})$')
    elseif kind == 'r' then
      prefix, id, body = raw:match('^(r:)(%d+%-%d+):(%{.*%})$')
    end
    if id then
      if own(id) then return originals.vehicle(raw) end -- acknowledgement of our own spawn
      local data = decode(body)
      -- Before the handshake we can retain only a bounded number of tagged spawns.
      if not data or type(data.earth) ~= 'table' or data.earth.protocol ~= space.PROTOCOL then
        stats.rejected = stats.rejected + 1; return
      end
      local r = recordFor(id)
      if r then
        if kind == 's' then r.spawn, r.prefix = data, prefix
        else r.reset, r.pose = data, nil end
        r.dirty = true
      end
      return
    end
    -- Edits/couplers for a dormant vehicle must wait until its spawn is replayed.
    local editId = raw:match('^%a:(%d+%-%d+):')
    local r = editId and remote[editId]
    if r and not r.spawned then
      if #r.edits < 16 then r.edits[#r.edits + 1] = raw end
      return
    end
    return originals.vehicle(raw)
  end
  wrappers.correction = function(...)
    if st and st.inOurLevel and mpSession() and not ready() then return end
    return originals.correction(...)
  end
  wrappers.playerLeft = function(playerId, ...)
    for id in pairs(remote) do
      if tonumber(id:match('^(%d+)%-')) == tonumber(playerId) then remote[id] = nil end
    end
    if originals.playerLeft then return originals.playerLeft(playerId, ...) end
  end
  MPGameNetwork.send, positionGE.handle, MPVehicleGE.handle = wrappers.send, wrappers.position, wrappers.vehicle
  positionGE.setPositionRotationVelocity = wrappers.correction
  MPVehicleGE.onPlayerLeft = wrappers.playerLeft
  AddEventHandler('EarthMPSession', onSession, 'beamngEarthMP')
  -- Queued native spawns contain local coordinates and must not survive a rebase.
  if settings and settings.getValue and settings.setValue then
    savedQueue = settings.getValue('enableSpawnQueue', true)
    settings.setValue('enableSpawnQueue', false)
  end
  installed = true
  return true
end

function M.beginFrameChange()
  if not installed or not mpSession() then return end
  fence = 0.5 -- drain old GE/VE callbacks before sending samples in the new frame
  for id, r in pairs(remote) do removeLocal(id, r); r.dirty = true end
  if positionGE.posSmoother then for id in pairs(positionGE.posSmoother) do positionGE.posSmoother[id] = nil end end
end

function M.update(state, dt)
  st = state
  if not (st.inOurLevel and mpSession()) then
    if installed then M.reset() end
    return
  end
  if not M.install() then errorText = 'Unsupported or unloaded BeamMP GE API'; return end
  fence = math.max(0, fence - (dt or 0))
  local nextProfile = st.mpProfile and st.mpProfile.id
  if nextProfile ~= profile then
    accepted, session, profile, timer = false, nil, nextProfile, 3
    for id, r in pairs(remote) do
      removeLocal(id, r)
      -- Late join spawns may arrive before our local generator's hello.
      if not r.spawn or not space.validEnvelope(r.spawn.earth, nextProfile) then remote[id] = nil end
    end
  end
  timer = timer + (dt or 0)
  if profile and timer >= 3 and TriggerServerEvent then
    timer = 0
    TriggerServerEvent('EarthMPHello', jsonEncode({ protocol = space.PROTOCOL, profile = profile }))
  end
  if not ready() then return end
  -- Refresh pending initial-spawn positions after the startup teleport.
  local pending = outgoing; outgoing = {}
  for _, raw in ipairs(pending) do
    local prefix, body = raw:match('^(Os:[^:]+:)(%{.*%})$')
    local data = body and decode(body)
    local veh = data and getObjectByID(data.vid)
    if veh then
      local p = veh:getPosition()
      local q = quatFromDir(-veh:getDirectionVector(), veh:getDirectionVectorUp())
      data.pos, data.rot = { p.x, p.y, p.z }, { q.x, q.y, q.z, q.w }
      local encoded = decorate(prefix .. jsonEncode(data))
      if encoded then originals.send(encoded) end
    end
  end
  for id, r in pairs(remote) do
    local current = converted(r.pose or r.reset or r.spawn)
    local inside = current and space.nearPlayer(current, st.player, 2000)
      and space.inBlock(current, st.block, st.mpBlockSize or 512, 2, r.spawned and 24 or 80)
    if not inside then
      removeLocal(id, r)
    elseif r.spawn then
      if not r.spawned then
        local spawn = converted(r.spawn)
        if spawn then
          -- The cached spawn may be hours old; use the latest geographic pose.
          spawn.pos, spawn.rot = space.position(current), space.rotation(current)
          originals.vehicle(r.prefix .. id .. ':' .. jsonEncode(spawn))
          r.spawned, r.dirty = true, true
          for _, edit in ipairs(r.edits) do originals.vehicle(edit) end
          r.edits = {}
        end
      end
      if r.spawned and r.reset then
        local reset = converted(r.reset)
        if reset then originals.vehicle('r:' .. id .. ':' .. jsonEncode(reset)) end
        r.reset = nil
      end
      if r.spawned and r.pose and r.dirty then
        local pose = converted(r.pose)
        if pose then originals.position('p:' .. id .. ':' .. jsonEncode(pose)) end
        r.dirty = false
      end
    end
  end
end

function M.reset()
  if installed then
    if MPGameNetwork.send == wrappers.send then MPGameNetwork.send = originals.send end
    if positionGE.handle == wrappers.position then positionGE.handle = originals.position end
    if MPVehicleGE.handle == wrappers.vehicle then MPVehicleGE.handle = originals.vehicle end
    if positionGE.setPositionRotationVelocity == wrappers.correction then positionGE.setPositionRotationVelocity = originals.correction end
    if MPVehicleGE.onPlayerLeft == wrappers.playerLeft then MPVehicleGE.onPlayerLeft = originals.playerLeft end
    if RemoveEventHandler then RemoveEventHandler('EarthMPSession', 'beamngEarthMP') end
    if savedQueue ~= nil and settings and settings.setValue then settings.setValue('enableSpawnQueue', savedQueue) end
  end
  installed, accepted, profile, session = false, false, nil, nil
  remote, outgoing, timer, fence = {}, {}, 0, 0
end

function M.status()
  local active, cached = 0, 0
  for _, r in pairs(remote) do cached = cached + 1; if r.spawned then active = active + 1 end end
  return { installed = installed == true, accepted = accepted == true, ready = ready() and true or false,
    message = errorText, profile = profile, activeVehicles = active, cachedVehicles = cached, stats = stats }
end

return M
