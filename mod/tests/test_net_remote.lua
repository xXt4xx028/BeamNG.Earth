local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local framing=require('beamngEarth/framing')
local wire,n={},0
function jsonEncode(t) n=n+1; wire['k'..n]=t; return 'k'..n end
function jsonDecode(s) return wire[s] end
local incoming, sent, files='',{},{}
FS={directoryExists=function() return false end,directoryCreate=function() end,removeFile=function(_,p) files[p]=nil end}
function writeFile(p,s) files[p]=s end
function readFile(p) return files[p] end
local sock={}
function sock:settimeout() end
function sock:setoption() end
function sock:connect(host,port) self.host,self.port=host,port; return true end
function sock:getpeername() return self.host,self.port end
function sock:send(s,offset) sent[#sent+1]=s:sub(offset or 1); return #s end
function sock:receive() local s=incoming; incoming=''; return nil,'timeout',s end
function sock:close() end
package.loaded.socket={tcp=function() return sock end}
local net=require('beamngEarth/net')
local endpoint={host='10.0.0.5',port=47613,token=string.rep('a',64),assetsProtocol=1}
T.check(net.configure(endpoint) and net.isRemote(),'remote endpoint accepted')
T.check(not net.configure({host='../bad',port=1,token=endpoint.token,assetsProtocol=1}),'invalid endpoint rejected')
local p='/temp/beamngEarth/session/terrain.ter'
local function add(t) incoming=incoming..framing.encode(jsonEncode(t)) end
add({type='asset_begin',path=p,bytes=3})
add({type='asset_chunk',path=p,offset=0,data='AAH/'})
add({type='asset_end',path=p})
add({type='terrain_ready',ter=p})
local messages=net.update(3)
T.check(#messages==2 and messages[1].type=='_connected' and messages[2].type=='terrain_ready','asset channel hidden from core')
T.check(files[p]=='\0\1\255','binary file available when terrain-ready is delivered')
net.send({type='hello',protocol=4})
local rx=framing.newReassembler(); rx:feed(sent[#sent]); local hello=jsonDecode(rx:pop())
T.check(hello.remoteAuth==endpoint.token and hello.remoteAssets==1,'remote handshake includes negotiated file capability and auth')
net.clearRemoteAssets(); T.check(files[p]==nil,'remote files cleaned')
net.useLocal(); T.check(not net.isRemote() and net.HOST=='127.0.0.1','local mode restored after leaving server')
T.done('net_remote')
