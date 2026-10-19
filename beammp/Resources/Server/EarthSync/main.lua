-- EarthSync: server-side compatibility handshake for the experimental Earth client.
-- The normal BeamMP transport still owns players/vehicles and relays their packets.
local PROTOCOL = 1
local peers = {}
local profile -- optional pin from EarthSync.json; otherwise locked by first accepted client
local worldServer
local maxPlayers = 8
local session = tostring(os.time()) .. '-' .. tostring(math.random(100000, 999999))
local configPath = 'Resources/Server/EarthSync/EarthSync.json'
local runtimePath = 'Resources/Server/EarthSync/EarthSync.runtime.json'

local function readJson(raw, limit)
  if type(raw) ~= 'string' or #raw > (limit or 8192) then return nil end
  local ok, result = pcall(Util.JsonDecode, raw)
  return ok and type(result) == 'table' and result or nil
end

local function hash(s)
  return type(s) == 'string' and #s == 64 and not s:find('[^0-9a-f]')
end

local function finite(n)
  return type(n) == 'number' and n == n and math.abs(n) < math.huge
end

local function loadConfig()
  local f = io.open(runtimePath, 'r') or io.open(configPath, 'r')
  if f then
    local c = readJson(f:read('*a')); f:close()
    if c then
      if hash(c.profile) then profile = c.profile end
      worldServer = type(c.worldServer) == 'table' and c.worldServer or nil
      maxPlayers = math.max(1,math.min(8,tonumber(c.maxPlayers) or 8))
    end
  end
end

function EarthSync_init()
  loadConfig()
  if MP.Set and MP.Settings and MP.Settings.MaxPlayers then MP.Set(MP.Settings.MaxPlayers,maxPlayers) end
  print('[EarthSync] Experimental geographic sync, protocol ' .. PROTOCOL)
end

function EarthSync_bootstrap(playerId)
  loadConfig() -- permits the world service to start after BeamMP
  if worldServer then
    MP.TriggerClientEvent(playerId,'EarthMPEndpoint',Util.JsonEncode(worldServer))
  end
end

function EarthSync_hello(playerId, raw)
  loadConfig()
  local msg = readJson(raw)
  if not msg then return end
  local ok = msg.protocol == PROTOCOL and hash(msg.profile)
  if ok and not profile then profile = msg.profile end
  ok = ok and msg.profile == profile
  peers[playerId] = ok and profile or nil
  MP.TriggerClientEvent(playerId, 'EarthMPSession', Util.JsonEncode({
    protocol = PROTOCOL, profile = msg.profile, accepted = ok,
    session = ok and session or nil,
    error = not ok and 'Incompatible Earth generator/profile. Use the server mod and matching earthd options.' or nil,
  }))
end

function EarthSync_left(playerId)
  peers[playerId] = nil
end

-- Reject unmodified clients and untagged initial spawns on this Earth-only server.
-- This is a compatibility check, not an anticheat or proof of identical map files.
function EarthSync_spawn(playerId, vehicleId, raw)
  -- Current TServer emits "role:name:pid-vid:{json}"; also accept the
  -- documented short prefix and older bare-JSON event payloads.
  if type(raw) == 'string' then
    raw = raw:match('^%w+:[%g%s]+:%d+%-%d+:%s*(%{.*%})%s*$')
      or raw:match('^%d+%-%d+:%s*(%{.*%})%s*$') or raw
  end
  local data = readJson(raw, 2 * 1024 * 1024)
  local e = data and data.earth
  if not peers[playerId] or type(e) ~= 'table' or e.protocol ~= PROTOCOL
    or e.profile ~= profile or e.session ~= session or not finite(e.lat) or math.abs(e.lat) > 90
    or not finite(e.lon) or math.abs(e.lon) > 180 then
    MP.SendChatMessage(playerId, '[EarthSync] Start the matching local Earth companion and wait for the handshake before spawning.')
    return 1
  end
  return 0
end

MP.RegisterEvent('onInit', 'EarthSync_init')
MP.RegisterEvent('EarthMPHello', 'EarthSync_hello')
MP.RegisterEvent('EarthMPBootstrap', 'EarthSync_bootstrap')
MP.RegisterEvent('onPlayerDisconnect', 'EarthSync_left')
MP.RegisterEvent('onVehicleSpawn', 'EarthSync_spawn')
