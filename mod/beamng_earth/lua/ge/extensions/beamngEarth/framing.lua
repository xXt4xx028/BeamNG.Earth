-- Wire framing (docs/V1_SPEC.md "Transport"): 4-byte little-endian uint32 length + payload.
-- Pure Lua: lengths are parsed with string.byte math (ffi.cast is a stub in BeamNG's sandbox).
-- The reassembler accepts arbitrary chunk splits, as delivered by non-blocking receives.

local M = {}

local byte, char, floor = string.byte, string.char, math.floor

M.MAX_FRAME = 64 * 1024 * 1024 -- anything larger means a desynced or hostile stream

function M.encode(payload)
  local n = #payload
  return char(n % 256, floor(n / 256) % 256, floor(n / 65536) % 256, floor(n / 16777216) % 256) .. payload
end

local Reassembler = {}
Reassembler.__index = Reassembler

function M.newReassembler()
  -- `parts` collects chunks cheaply; they are joined only when a frame might be complete.
  return setmetatable({ buf = '', pos = 1, parts = {}, pending = 0, need = nil, err = nil }, Reassembler)
end

function Reassembler:buffered()
  return #self.buf-self.pos+1+self.pending
end

function Reassembler:feed(chunk)
  if chunk and #chunk > 0 then
    self.parts[#self.parts + 1] = chunk
    self.pending = self.pending + #chunk
  end
end

-- Returns the next complete payload, or nil (need more data, or self.err is set).
function Reassembler:pop()
  if self.err then return nil end
  local have = self:buffered()
  if not self.need then
    if have < 4 then return nil end
  elseif have < 4 + self.need then
    return nil
  end
  if self.pending > 0 then
    -- Compact once when new data arrives, rather than copying the unread tail
    -- after every frame (quadratic copying when many chunks arrive together).
    self.buf = self.buf:sub(self.pos) .. table.concat(self.parts)
    self.pos = 1
    self.parts, self.pending = {}, 0
  end
  if not self.need then
    local b1, b2, b3, b4 = byte(self.buf, self.pos, self.pos+3)
    local n = b1 + b2 * 256 + b3 * 65536 + b4 * 16777216
    if n > M.MAX_FRAME then
      self.err = 'frame too large: ' .. n
      return nil
    end
    self.need = n
    if #self.buf-self.pos+1 < 4+n then return nil end
  end
  local n = self.need
  local payload = self.buf:sub(self.pos+4, self.pos+3+n)
  self.pos = self.pos+4+n
  if self.pos > #self.buf then self.buf,self.pos = '',1 end
  self.need = nil
  return payload
end

function Reassembler:reset()
  self.buf, self.pos, self.parts, self.pending, self.need, self.err = '', 1, {}, 0, nil, nil
end

M.Reassembler = Reassembler

return M
