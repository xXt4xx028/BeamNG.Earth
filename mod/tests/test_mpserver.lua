local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local wire, n = {}, 0
Util={}
function Util.JsonEncode(data) n=n+1; local key='{'..n..'}'; wire[key]=data; return key end
function Util.JsonDecode(raw) return wire[raw] end
local replies, rejected = {}, 0
MP={RegisterEvent=function() end,TriggerClientEvent=function(id,name,raw) replies[id]=wire[raw] end,
  SendChatMessage=function() rejected=rejected+1 end}
dofile(dir .. '/../../beammp/Resources/Server/EarthSync/main.lua')
EarthSync_init()
local profile=string.rep('a',64)
local function hello(id,p)
  EarthSync_hello(id,Util.JsonEncode({protocol=1,profile=p or profile}))
end
local function spawn(id,lat)
  return EarthSync_spawn(id,0,Util.JsonEncode({earth={protocol=1,profile=profile,
    session=replies[1] and replies[1].session,lat=lat or 19.4,lon=-99.1}}))
end
T.check(EarthSync_spawn(1,0,'bad')==1,'untagged spawn rejected before hello')
hello(1); T.check(replies[1].accepted and type(replies[1].session)=='string','first compatible client locks profile')
T.check(spawn(1)==0,'tagged compatible spawn accepted')
local prefixed=Util.JsonEncode({earth={protocol=1,profile=profile,session=replies[1].session,lat=0,lon=0}})
T.check(EarthSync_spawn(1,0,'1-0:'..prefixed)==0,'documented server ID prefix accepted')
T.check(EarthSync_spawn(1,0,'USER:Nick: with colon:1-0:'..prefixed)==0,'current server role/name prefix accepted')
hello(2); T.check(replies[2].accepted,'second compatible generator accepted')
hello(3,string.rep('b',64)); T.check(not replies[3].accepted,'different generator rejected')
T.check(spawn(3)==1,'rejected client cannot spawn')
T.check(spawn(1,91)==1,'invalid latitude rejected')
T.check(spawn(1,0/0)==1,'nonfinite anchor rejected')
EarthSync_left(1); T.check(spawn(1)==1,'disconnect clears handshake')
EarthSync_hello(8,Util.JsonEncode({protocol=99,profile=profile})); T.check(not replies[8].accepted,'unknown wire version rejected')
T.done('mpserver')
