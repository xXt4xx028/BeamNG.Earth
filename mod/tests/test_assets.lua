local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local assets = require('beamngEarth/assets')
local files = {}
FS={directoryExists=function() return false end,directoryCreate=function() end,
  removeFile=function(_,p) files[p]=nil end}
function writeFile(p,b) files[p]=b end
function readFile(p) return files[p] end
local p='/temp/beamngEarth/session/test.cdae'
local digest=string.rep('a',64)
T.check(assets.validPath(p),'generated path allowed')
for _,bad in ipairs({'/settings/x','/temp/beamngEarth/../x','/temp/beamngEarth/a/../../x',
  '/temp/beamngEarth/a\\b','/temp/beamngEarth/a:C','/temp/beamngEarth//x','/temp/beamngEarth/'}) do
  T.check(not assets.validPath(bad),'escape rejected: '..bad)
end
T.check(assets.decode64('AAH/YWJj')=='\0\1\255abc','binary base64 preserves null/high bytes')
T.check(not assets.decode64('!!!!'),'bad base64 rejected')
T.check(assets.receive({type='status',text='normal'})==false,'control messages pass through')
T.check(assets.receive({type='asset_begin',path=p,bytes=6,digest=digest}),'start')
T.check(assets.receive({type='asset_chunk',path=p,offset=0,data='AAH/'}),'first chunk')
T.check(files[p]==nil,'partial file not published')
T.check(assets.receive({type='asset_chunk',path=p,offset=3,data='YWJj'}),'second chunk')
T.check(assets.receive({type='asset_end',path=p}),'complete')
T.check(files[p]=='\0\1\255abc','complete bytes reach VFS before control message')
assets.receive({type='asset_delete',path=p,digest=string.rep('b',64)})
T.check(files[p]~=nil,'stale delete cannot remove a newer pooled file')
assets.receive({type='asset_delete',path=p,digest=digest})
T.check(files[p]==nil,'server release deletes only the matching owned file')
assets.receive({type='asset_begin',path=p,bytes=6,digest=digest})
local ok,err=assets.receive({type='asset_chunk',path=p,offset=3,data='YWJj'})
T.check(not ok and err~=nil,'out-of-order chunk fails closed')
assets.reset()
ok,err=assets.receive({type='asset_begin',path=p,bytes=40*1024*1024,digest=digest})
T.check(not ok and err~=nil,'allocation bounded')
assets.clear(); T.check(files[p]==nil,'only owned files cleaned on level exit')
local raw='\0EAR1'..string.char(0,0,0,0)..'\0\1\255abc'
T.check(not assets.receiveBinary(raw),'binary cannot arrive before asset-begin')
assets.receive({type='asset_begin',path=p,bytes=6,digest=digest,encoding='binary'})
T.check(assets.receiveBinary(raw),'raw bytes accepted without base64')
T.check(not assets.receiveBinary(raw),'duplicate binary offset rejected')
assets.receive({type='asset_end',path=p})
T.check(files[p]=='\0\1\255abc','binary data reaches VFS exactly')
assets.receive({type='asset_begin',path=p,bytes=6,digest=digest,encoding='binary'})
T.check(not assets.receiveBinary('\0EAR1\0\0'),'truncated binary header rejected')
T.check(not assets.receiveBinary('\0EAR1\0\0\0\0'..string.rep('x',49153)),'binary chunk size bounded')
T.check(not assets.receive({type='asset_chunk',path=p,offset=0,data='AAH/'}),'cannot mix binary and base64 encodings')
assets.clear()
T.done('assets')
