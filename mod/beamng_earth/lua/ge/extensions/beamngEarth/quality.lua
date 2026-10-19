-- Per-client outer LOD only. The host keeps all near-exact geometry and physics.
-- Auto targets roughly 30 fps, with sustained evidence and slow recovery to avoid
-- repeatedly rebuilding the quadtree. Loading, pauses and single long stalls do
-- not count as evidence. This cannot fix a physics or graphics bottleneck by itself.
local M = {}
local Q = {}
Q.__index = Q
local STEPS = { 1, 0.85, 0.7, 0.55 }

function M.new()
  return setmetatable({ mode = 'balanced', scale = 1, step = 1, warm = 0,
    slow = 0, fast = 0, cooldown = 0, ema = nil }, Q)
end

function Q:setMode(mode)
  if mode ~= 'balanced' and mode ~= 'low' and mode ~= 'auto' then return false end
  if mode == self.mode then return false end
  self.mode, self.step = mode, mode == 'low' and 3 or 1
  self.scale = STEPS[self.step]
  self.warm, self.slow, self.fast, self.cooldown, self.ema = 0, 0, 0, 0, nil
  return true
end

function Q:update(dt, blocked)
  if self.mode ~= 'auto' then return nil end
  if blocked or type(dt) ~= 'number' or dt ~= dt or dt < 0.001 or dt > 0.25 then
    self.warm, self.slow, self.fast, self.ema = 0, 0, 0, nil
    return nil
  end
  self.cooldown = math.max(0, self.cooldown - dt)
  self.ema = self.ema and self.ema + (dt - self.ema) * math.min(1, dt / 2) or dt
  self.warm = self.warm + dt
  if self.warm < 3 then return nil end
  self.slow = self.ema > 1 / 27 and self.slow + dt or 0
  self.fast = self.ema < 1 / 42 and self.fast + dt or 0
  if self.cooldown > 0 then return nil end
  local step = self.step
  if self.slow >= 3 and step < #STEPS then step = step + 1
  elseif self.fast >= 20 and step > 1 then step = step - 1 end
  if step == self.step then return nil end
  self.step, self.scale, self.slow, self.fast, self.cooldown = step, STEPS[step], 0, 0, 10
  return self.scale
end

return M
