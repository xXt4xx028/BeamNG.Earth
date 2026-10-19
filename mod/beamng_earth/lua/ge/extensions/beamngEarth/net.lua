-- Non-blocking TCP client for the companion server (docs/V1_SPEC.md "Transport").
-- luasocket with settimeout(0): nothing here ever blocks the frame. Reconnects every 2 s.
-- update() returns the decoded messages of this frame, plus the pseudo-messages
-- {type='_connected'} / {type='_disconnected'} so the caller can (re)sync its state.
-- attempts() / everConnected(): connection attempts since the last connection (the on-screen
-- banner's "reconnecting (attempt n)") and whether this game ever reached the server.

local framing = require('beamngEarth/framing')
local assets = require('beamngEarth/assets')

local M = {}

M.HOST, M.PORT = '127.0.0.1', 47613
local remoteToken = nil
local RECONNECT_S = 2.0
local CONNECT_TIMEOUT_S = 2.0
local RECV_CHUNK = 65536
local MAX_RECV_PER_FRAME = 64 -- chunks; 4 MiB per frame is plenty for JSON control traffic

local socket = nil
local sock = nil
local state = 'disconnected' -- 'disconnected' | 'connecting' | 'connected'
local timer = RECONNECT_S    -- first attempt happens on the first update
local rx = framing.newReassembler()
local outQueue = {}          -- encoded frames waiting to be sent
local outPos = 1             -- next byte of outQueue[1] to send
local events = {}
local attempts = 0           -- connection attempts since the last successful connection
local everConnected = false

M.lastError = nil

local function closeSocket(err)
  if sock then pcall(sock.close, sock) end
  local wasConnected = state == 'connected'
  sock, state, timer = nil, 'disconnected', 0
  rx:reset()
  assets.reset()
  outQueue, outPos = {}, 1
  M.lastError = err
  if wasConnected then events[#events + 1] = { type = '_disconnected', error = err } end
end

local function startConnect()
  attempts = attempts + 1
  socket = socket or require('socket')
  sock = socket.tcp()
  sock:settimeout(0)
  -- A non-blocking connect returns nil,'timeout' while in progress. luasocket turns the
  -- master into a tcp{client} even then (no second connect() call is possible), so
  -- completion is detected with getpeername() in pollConnect().
  local ok, err = sock:connect(M.HOST, M.PORT)
  if ok then
    state = 'connected'
  elseif err == 'timeout' or err == 'Operation already in progress' then
    state, timer = 'connecting', 0
  else
    closeSocket(err)
    return
  end
  if state == 'connected' then
    M.lastError = nil
    attempts, everConnected = 0, true
    pcall(sock.setoption, sock, 'tcp-nodelay', true)
    events[#events + 1] = { type = '_connected' }
  end
end

local function pollConnect(dt)
  if sock:getpeername() then
    state = 'connected'
    M.lastError = nil
    attempts, everConnected = 0, true
    pcall(sock.setoption, sock, 'tcp-nodelay', true)
    events[#events + 1] = { type = '_connected' }
    return
  end
  timer = timer + dt
  if timer >= CONNECT_TIMEOUT_S then closeSocket('connect timeout / refused') end
end

local function flush()
  while sock and outQueue[1] do
    local data = outQueue[1]
    local last, err, partialLast = sock:send(data, outPos)
    if last then
      table.remove(outQueue, 1)
      outPos = 1
    elseif err == 'timeout' then
      outPos = (partialLast or (outPos - 1)) + 1 -- kernel buffer full; continue next frame
      return
    else
      closeSocket('send: ' .. tostring(err))
      return
    end
  end
end

local function receive(out)
  local closeErr = nil
  for _ = 1, (#rx.buf + rx.pending < 4*1024*1024 and MAX_RECV_PER_FRAME or 0) do
    local data, err, partial = sock:receive(RECV_CHUNK)
    rx:feed(data or partial)
    -- 'timeout' = drained for this frame. Anything else ('closed', 'connection reset by
    -- peer', ...) is fatal; luasocket keeps returning it, so the socket must be closed.
    if err and err ~= 'timeout' then closeErr = err; break end
    if not data then break end
  end
  -- decode before closing: closeSocket() resets the reassembler, and the server's last
  -- frames (e.g. an anchor_error) may have arrived together with the close
  for _ = 1, 16 do
    local payload = rx:pop()
    if not payload then break end
    local msg = jsonDecode(payload, 'beamngEarth/net')
    if type(msg) == 'table' then
      local handled, err = false, nil
      if remoteToken then handled, err = assets.receive(msg) end
      if err then closeSocket(err); return end
      if not handled then out[#out + 1] = msg end
    end
  end
  if rx.err then
    closeSocket(rx.err)
  elseif closeErr then
    closeSocket(closeErr == 'closed' and 'closed by server' or ('receive: ' .. tostring(closeErr)))
  end
end

-- Call once per frame. Returns an array of messages (may be empty).
function M.update(dt)
  if state == 'disconnected' then
    timer = timer + dt
    if timer >= RECONNECT_S then startConnect() end
  elseif state == 'connecting' then
    pollConnect(dt)
  end
  -- connect/disconnect events come before this frame's messages, a disconnect raised
  -- while receiving comes after them
  local out = events
  events = {}
  if state == 'connected' then
    flush()
    if sock then receive(out) end
  end
  for _, e in ipairs(events) do out[#out + 1] = e end
  events = {}
  return out
end

-- Queue a message table; returns false when not connected (the message is dropped).
function M.send(msg)
  if state ~= 'connected' then return false end
  if remoteToken and msg.type == 'hello' then
    msg.remoteAuth, msg.remoteAssets = remoteToken, 1
  end
  outQueue[#outQueue + 1] = framing.encode(jsonEncode(msg))
  flush()
  return true
end

function M.state() return state end
function M.isConnected() return state == 'connected' end
function M.attempts() return attempts end
function M.everConnected() return everConnected end

function M.close()
  closeSocket('closed')
  events = {}
  timer = RECONNECT_S
end

function M.configure(endpoint)
  if type(endpoint) ~= 'table' or endpoint.assetsProtocol ~= 1 or type(endpoint.host) ~= 'string'
    or #endpoint.host > 253 or not endpoint.host:match('^[%w%.%-]+$')
    or type(endpoint.port) ~= 'number' or endpoint.port < 1 or endpoint.port > 65535 or endpoint.port % 1 ~= 0
    or type(endpoint.token) ~= 'string' or #endpoint.token < 32 or #endpoint.token > 256 then return false end
  if M.HOST == endpoint.host and M.PORT == endpoint.port and remoteToken == endpoint.token then return true end
  M.close()
  M.HOST, M.PORT, remoteToken = endpoint.host, endpoint.port, endpoint.token
  timer = RECONNECT_S
  return true
end

function M.clearRemoteAssets()
  if remoteToken then
    assets.clear()
  end
end

function M.isRemote() return remoteToken ~= nil end

function M.useLocal()
  if remoteToken then M.close() end
  M.HOST, M.PORT, remoteToken = '127.0.0.1', 47613, nil
end

return M
