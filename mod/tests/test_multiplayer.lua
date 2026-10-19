local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local geo = require('beamngEarth/geodesy')
local space = require('beamngEarth/mpspace')
local mp = require('beamngEarth/multiplayer')
local wire, serial = {}, 0
function jsonEncode(data) serial=serial+1; local key='{'..serial..'}'; wire[key]=data; return key end
function jsonDecode(key) return wire[key] end
local sent, positions, vehicles, handlers = {}, {}, {}, {}
local inSession = true
MPCoreNetwork={isMPSession=function() return inSession end}
MPConfig={getPlayerServerID=function() return 1 end}
MPGameNetwork={send=function(raw) sent[#sent+1]=raw end}
positionGE={handle=function(raw) positions[#positions+1]=raw end,
  setPositionRotationVelocity=function() end, posSmoother={}}
MPVehicleGE={handle=function(raw) vehicles[#vehicles+1]=raw end,onPlayerLeft=function() end}
function AddEventHandler(name, fn) handlers[name]=fn end
function RemoveEventHandler(name) handlers[name]=nil end
function TriggerServerEvent(name, raw)
  if name == 'EarthMPBootstrap' then return end
  T.check(name=='EarthMPHello' and not name:find(':'),'event name cannot contain the protocol delimiter')
  local msg=jsonDecode(raw)
  handlers['EarthMPSession'](jsonEncode({protocol=1,profile=msg.profile,accepted=true,session='test'}))
end
local queue = true
settings={getValue=function() return queue end,setValue=function(_,v) queue=v end}
local originalSend,originalVehicle=MPGameNetwork.send,MPVehicleGE.handle
local state={inOurLevel=true,active=true,anchor=geo.newAnchor(19.4326,-99.1332),block={cx=0,cy=0},
  mpProfile={id='profile'},mpBlockSize=512,player={x=0,y=0,z=2200}}
mp.update(state,3)
T.check(mp.status().ready,'handshake accepted')
T.check(not queue,'native deferred spawn queue disabled')
local function sample(x)
  local e=space.envelope(state.anchor,'profile'); e.session='test'
  return {pos={x,0,2200},rot={0,0,0,1},vel={1,0,0},rvel={0,0,0},earth=e,tim=3,ping=0.01,vid=22}
end
-- Outgoing native pose acquires a geographic frame; ordinary messages are untouched.
local ownPose=sample(20); ownPose.earth=nil
MPGameNetwork.send('Zp:1-0:'..jsonEncode(ownPose))
local body=sent[#sent]:match('^Zp:1%-0:(.*)$')
T.check(jsonDecode(body).earth.session=='test','outgoing pose tagged')
MPGameNetwork.send('chat:unchanged'); T.check(sent[#sent]=='chat:unchanged','other traffic unaffected')
-- Unknown/far players are data-only until the local terrain can support them.
MPVehicleGE.handle('s:USER:Nick: with colon:2-0:'..jsonEncode(sample(2000)))
positionGE.handle('p:2-0:'..jsonEncode(sample(2000)))
mp.update(state,0.1)
T.check(mp.status().activeVehicles==0 and #vehicles==0,'far vehicle not spawned')
positionGE.handle('p:2-0:'..jsonEncode(sample(40)))
mp.update(state,0.1)
T.check(mp.status().activeVehicles==1,'near vehicle spawned from cached metadata')
T.check(#positions==1,'current pose replayed after spawn')
local spawn=jsonDecode(vehicles[#vehicles]:match('(%{.*%})$'))
T.near(spawn.pos[1],40,1e-6,'old spawn refreshed with latest pose')
positionGE.handle('p:2-0:'..jsonEncode(sample(2000))); mp.update(state,0.1)
T.check(vehicles[#vehicles]=='d:2-0','culling uses receive deletion, not outbound deletion')
T.check(mp.status().cachedVehicles==1,'culling preserves geographic record')
-- Deferred reset uses object-form coordinates and is replayed when the vehicle returns.
local reset=sample(30); reset.pos={x=30,y=0,z=2200}; reset.rot={x=0,y=0,z=0,w=1}
MPVehicleGE.handle('r:2-0:'..jsonEncode(reset)); mp.update(state,0.1)
T.check(mp.status().activeVehicles==1,'reset brings remote vehicle into relevance')
T.check(vehicles[#vehicles]:sub(1,6)=='r:2-0:','reset replayed')
-- No local-frame packet is forwarded during a moving-origin transition.
mp.beginFrameChange()
local n=#sent
MPGameNetwork.send('Zp:1-0:'..jsonEncode(sample(0)))
T.check(#sent==n,'transient pose blocked')
mp.update(state,0.6)
T.check(mp.status().ready,'fence drains')
state.pending={purpose='rebase'}; mp.update(state,0)
T.check(mp.status().ready,'rebase prefetch does not silence driving packets')
state.pending=nil
-- Untagged and incompatible poses fail closed.
local rejected=mp.status().stats.rejected
positionGE.handle('p:3-0:'..jsonEncode({pos={0,0,0}}))
T.check(mp.status().stats.rejected==rejected+1,'untagged packet rejected')
MPVehicleGE.handle('d:2-0'); T.check(mp.status().cachedVehicles==0,'server removal forgets cached spawn')
MPVehicleGE.handle('s:USER:Leaving:4-0:'..jsonEncode(sample(2000)))
MPVehicleGE.onPlayerLeft(4)
T.check(mp.status().cachedVehicles==0,'disconnect clears dormant players before IDs can be reused')
state.inOurLevel=false; mp.update(state,0)
T.check(MPGameNetwork.send==originalSend and MPVehicleGE.handle==originalVehicle,'hooks restored on level exit')
T.check(queue,'spawn queue preference restored')
-- Cold local companion: retain a late-join spawn until profile and session arrive.
state.inOurLevel=true; state.mpProfile=nil
mp.update(state,0)
MPVehicleGE.handle('s:USER:Late:5-0:'..jsonEncode(sample(10)))
T.check(mp.status().cachedVehicles==1,'spawn cached before local profile')
state.mpProfile={id='profile'}; mp.update(state,3)
T.check(mp.status().activeVehicles==1,'matching pre-hello spawn survives generator handshake')
mp.reset()
mp.prepareLevel()
local before=#sent
MPGameNetwork.send('Os:0:'..jsonEncode(sample(0)))
T.check(#sent==before,'initial spawn captured during mission loading, before core level-start')
mp.reset()
T.done('multiplayer')
