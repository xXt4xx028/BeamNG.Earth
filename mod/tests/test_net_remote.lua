local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local framing=require('beamngEarth/framing')
local wire,n={},0
function jsonEncode(t) n=n+1; wire['k'..n]=t; return 'k'..n end
function jsonDecode(s) return wire[s] end
local incoming, sent, files='',{},{}
local readError='timeout'
FS={directoryExists=function() return false end,directoryCreate=function() end,removeFile=function(_,p) files[p]=nil end}
function writeFile(p,s) files[p]=s end
function readFile(p) return files[p] end
local sock={}
function sock:settimeout() end
function sock:setoption() end
function sock:connect(host,port) self.host,self.port=host,port; return true end
function sock:getpeername() return self.host,self.port end
function sock:send(s,offset) sent[#sent+1]=s:sub(offset or 1); return #s end
function sock:receive() local s=incoming; incoming=''; return nil,readError,s end
function sock:close() end
package.loaded.socket={tcp=function() return sock end}
local net=require('beamngEarth/net')
net.RECEIVE_BUDGET_MS=1000 -- deterministic existing checks, independent of test-machine load
local endpoint={host='10.0.0.5',port=47613,token=string.rep('a',64),assetsProtocol=1}
T.check(net.configure(endpoint) and net.isRemote(),'remote endpoint accepted')
T.check(not net.configure({host='../bad',port=1,token=endpoint.token,assetsProtocol=1}),'invalid endpoint rejected')
local p='/temp/beamngEarth/session/terrain.ter'
local function add(t) incoming=incoming..framing.encode(jsonEncode(t)) end
add({type='asset_begin',path=p,bytes=3,digest=string.rep('a',64)})
add({type='asset_chunk',path=p,offset=0,data='AAH/'})
add({type='asset_end',path=p})
add({type='terrain_ready',ter=p})
local messages=net.update(3)
T.check(#messages==2 and messages[1].type=='_connected' and messages[2].type=='terrain_ready','asset channel hidden from core')
T.check(files[p]=='\0\1\255','binary file available when terrain-ready is delivered')
net.send({type='hello',protocol=4})
local rx=framing.newReassembler(); rx:feed(sent[#sent]); local hello=jsonDecode(rx:pop())
T.check(hello.remoteAuth==endpoint.token and hello.remoteAssets==1 and hello.remoteAssetBinary==1,'remote handshake negotiates binary file capability and auth')
net.update(10)
local beat=framing.newReassembler(); beat:feed(sent[#sent])
T.check(jsonDecode(beat:pop()).type=='keepalive','paused/idle clients keep their authenticated slot alive')
net.clearRemoteAssets(); T.check(files[p]==nil,'remote files cleaned')
net.useLocal(); T.check(not net.isRemote() and net.HOST=='127.0.0.1','local mode restored after leaving server')
endpoint.host='earth.example.com'; endpoint.clientBridge=true
T.check(net.configure(endpoint) and net.HOST=='127.0.0.1' and net.PORT==47614,'TLS endpoint uses explicitly started localhost bridge')
net.update(3); net.send({type='hello',protocol=4})
local proxied=framing.newReassembler(); proxied:feed(sent[#sent])
T.check(jsonDecode(proxied:pop()).remoteAuth==endpoint.token,'bridge mode retains server authentication')
add({type='asset_begin',path=p,bytes=3,digest=string.rep('b',64),encoding='binary'})
incoming=incoming..framing.encode('\0EAR1\0\0\0\0\0\1\255')
add({type='asset_end',path=p})
add({type='terrain_ready',ter=p})
net.RECEIVE_BUDGET_MS=0
local controls={}
for i=1,4 do
  local batch=net.update(.01)
  for _,message in ipairs(batch) do controls[#controls+1]=message end
  if i<4 then T.check(#controls==0,'frame budget defers trailing control until bytes complete') end
end
T.check(#controls==1 and controls[1].type=='terrain_ready' and files[p]=='\0\1\255','binary and budget preserve dependency-before-control order')
add({type='status',text='first'}); add({type='status',text='second'}); add({type='status',text='third'})
readError='closed'
local tail={}
for i=1,3 do
  for _,message in ipairs(net.update(.01)) do tail[#tail+1]=message end
end
T.check(#tail==4 and tail[1].text=='first' and tail[3].text=='third' and tail[4].type=='_disconnected','EOF drains complete buffered frames across budget-limited updates')
net.useLocal()
T.done('net_remote')
