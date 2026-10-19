-- Receive generated assets from a central Earth server. No Python on the player PC.
local M = {}
local PREFIX = '/temp/beamngEarth/'
local MAX_FILE = 32 * 1024 * 1024
local pending = nil -- ordered transport: at most one file is assembled at a time
local owned = {}
local alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local digits = {}
for i = 1, #alphabet do digits[alphabet:sub(i,i)] = i - 1 end
local hasMime, mime = pcall(require,'mime') -- LuaSocket's C decoder when available in BeamMP

function M.validPath(path)
  if type(path) ~= 'string' or path:sub(1,#PREFIX) ~= PREFIX or #path > 512 then return false end
  if path:find('[\\:%z]') or path:find('//',1,true) then return false end
  local rest = path:sub(#PREFIX+1)
  if rest == '' then return false end
  for part in rest:gmatch('[^/]+') do if part == '.' or part == '..' then return false end end
  return not path:find('/$',1)
end

function M.decode64(encoded)
  if type(encoded) ~= 'string' or #encoded % 4 ~= 0 then return nil end
  if hasMime and type(mime.unb64) == 'function' then
    if encoded:find('[^%w%+/%=]') then return nil end
    local pad=encoded:find('=',1,true)
    if pad and (pad < #encoded-1 or not encoded:sub(pad):match('^=+$')) then return nil end
    return mime.unb64(encoded)
  end
  local out = {}
  for i = 1, #encoded, 4 do
    local a,b,c,d = encoded:sub(i,i), encoded:sub(i+1,i+1), encoded:sub(i+2,i+2), encoded:sub(i+3,i+3)
    if not digits[a] or not digits[b] or (c ~= '=' and not digits[c]) or (d ~= '=' and not digits[d])
      or (c == '=' and d ~= '=') or ((c == '=' or d == '=') and i+3 ~= #encoded) then return nil end
    local n = digits[a]*262144 + digits[b]*4096 + (digits[c] or 0)*64 + (digits[d] or 0)
    if c == '=' then out[#out+1] = string.char(math.floor(n/65536)%256)
    elseif d == '=' then out[#out+1] = string.char(math.floor(n/65536)%256,math.floor(n/256)%256)
    else out[#out+1] = string.char(math.floor(n/65536)%256,math.floor(n/256)%256,n%256) end
  end
  return table.concat(out)
end

function M.receive(msg)
  if type(msg.type) ~= 'string' or msg.type:sub(1,6) ~= 'asset_' then return false end
  if not M.validPath(msg.path) then return nil, 'invalid asset path' end
  if msg.type == 'asset_begin' then
    if pending or type(msg.bytes) ~= 'number' or msg.bytes < 0 or msg.bytes > MAX_FILE or msg.bytes % 1 ~= 0 then
      return nil, 'invalid asset size/order'
    end
    pending = {path=msg.path, bytes=msg.bytes, have=0, chunks={}}
  elseif msg.type == 'asset_chunk' then
    if not pending or pending.path ~= msg.path or msg.offset ~= pending.have then return nil, 'out-of-order asset' end
    if type(msg.data) ~= 'string' or #msg.data > 65536 then return nil, 'asset chunk too large' end
    local bytes = M.decode64(msg.data)
    if not bytes or pending.have+#bytes > pending.bytes then return nil, 'invalid asset chunk' end
    pending.have = pending.have + #bytes
    pending.chunks[#pending.chunks+1] = bytes
  elseif msg.type == 'asset_end' then
    if not pending or pending.path ~= msg.path or pending.have ~= pending.bytes then return nil, 'incomplete asset' end
    local dir = msg.path:match('^(.*)/[^/]+$')
    if not FS:directoryExists(dir) then FS:directoryCreate(dir,true) end
    local body = table.concat(pending.chunks)
    local ok, err = pcall(writeFile,msg.path,body)
    if not ok or err == false then return nil, 'cannot write generated asset' end
    -- Refuse to expose a control message unless the complete bytes reached VFS.
    if readFile(msg.path) ~= body then return nil, 'generated asset write verification failed' end
    owned[msg.path], pending = true, nil
  else return nil, 'unknown asset message' end
  return true
end

function M.reset()
  pending = nil
end

function M.clear()
  pending = nil
  for path in pairs(owned) do
    if FS and FS.removeFile then pcall(FS.removeFile,FS,path) end
  end
  owned = {}
end
return M
