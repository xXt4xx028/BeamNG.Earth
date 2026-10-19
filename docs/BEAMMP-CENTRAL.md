# Central Earth host: shared 40 GB cache, up to 8 players

Alpha.3 keeps world generation on the host. Each player installs the normal
BeamMP-distributed client mod and receives generated terrain, geometry and
textures over a separate authenticated Earth connection. **Players do not run
Python in this mode.** They still render the world and run vehicle physics in
BeamNG, and the engine needs local temporary copies of received files.

**Network limitation:** upstream's in-game probes found that BeamNG's LuaSocket
sandbox rejects direct public Internet connections (`connect restricted`), while
localhost works; its documented allowlist includes LAN addresses. This prototype
therefore needs LAN, a compatible VPN, or the new separately started
[TLS client bridge](BEAMMP-CLIENT-BRIDGE.md).
The VPN path still needs testing in the installed game version. A public BeamMP
server address alone does not make the separate Earth asset socket reachable.
For Internet hosting, alpha.3 can use the external bridge on each player's PC.
The Lua mod then connects only to localhost. The bridge is an explicitly started
program; a BeamMP mod ZIP does not install/start it automatically.

An alternative relay through BeamMP events has been [reviewed in source](BEAMMP-TRANSPORT-REVIEW.md).
It is not implemented; shared TCP traffic and synchronous sends need
live throughput/latency tests before claiming it can stream terrain to eight players.

The host runs two processes:

1. **BeamMP-Server**, with the `EarthSync` Lua resource and the client ZIP.
2. **Earth world service**, the Python generator from this fork. It shares one
   download cache between all players and keeps their origins/streaming state
   independent. It can run without BeamNG or a GPU on the host.

The Python generator is not a native Lua BeamMP resource. Installing the resource
does not magically execute Python inside BeamMP. Both processes must be started
on the host; the Lua resource announces the Earth endpoint to joining players.

## Cache and resource budget

- One **40 decimal GB download-cache target for the server**, shared by all
  players. It is not 40 GB per player and is not divided into fixed 5 GB shares.
  Players visiting the same area reuse downloaded input data.
- Old, unused input data is evicted by the upstream cache manager. Its protection
  of recently used data means 40 GB is an **eviction target, not a hard disk quota**.
- Generated host files under `EarthWorld/runtime` are additional. Player-side
  received files under `temp/beamngEarth` are also additional; the mod removes its
  received files when the host releases them and when leaving the level. Host runtime sessions have their normal
  cleanup rules. Reserve disk space beyond the 40 GB source cache.
- Both the BeamMP resource and the world service default to **8**. The service
  rejects a ninth connection, including attempts during authentication. A player
  cannot change the shared cache cap or clear it from their settings page.
  Idle connections without keepalives are removed after 30 seconds so a vanished
  connection cannot hold one of the eight slots indefinitely.
- Eight simultaneous independent destinations require substantially more world
  generation than eight players driving together. The earlier per-PC CPU
  estimate does not apply to this centralized design. Real eight-player CPU,
  RAM, upload bandwidth and FPS measurements are still required.
- The host helper now selects a 12 km far scenery radius and 256/256/128/128
  texture sizes, with a 240 Mbit/s aggregate and 40 Mbit/s per-player Earth
  upload cap. This reserves nominal headroom on a 300 Mbit/s link; it is not
  router QoS or a guarantee against congestion. Direct CLI limits are configurable.
- A shared 128 MiB in-memory asset cache avoids repeated disk reads and SHA256
  computation for unchanged files used by multiple players. It checks file
  identity/size/timestamps to detect pooled filenames being reused. It does not
  merge separately generated geometry or eliminate each player's download.
- Base64 file framing adds roughly one third to binary transfer size, plus small
  JSON overhead. Files are sent once per connection/content hash and resent if a
  pooled file changes. There is no claim that this transport is optimized for
  fast driving with eight players yet.

## Build and install on a dedicated test server

From the checkout:

```powershell
python tools/package_beammp.py
```

Copy `dist/beammp-central/Resources/` into the BeamMP server. In its existing
`ServerConfig.toml`, set:

```toml
[General]
MaxPlayers = 8
Map = "/levels/beamng_earth/info.json"
```

Keep the server's existing name, key, network settings and other required values.
There should be one Earth client ZIP in `Resources/Client`; remove an older
unpacked client copy through the game's normal mod manager if it shadows this
server-distributed mod.

Unpack `BeamNG.Earth-BeamMP-host-source.zip` on the host and install Python 3.10+
and the requirements in a virtual environment. Example with a VPN/private host
address reachable by all eight players:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
.\.venv\Scripts\python.exe tools/start_beammp_world.py --beammp-dir "C:\BeamMP-Test" --public-host 10.0.0.5 --listen 10.0.0.5
```

Replace both the directory and address with real values. The default bind address
is loopback, so remote players require an explicit reachable bind address.
Despite the option name `--public-host`, use the private/VPN address that the game
can access; an arbitrary public IP or hostname may be blocked by its sandbox.
No port forwarding, firewall changes or deployment are performed by the builder.

The helper starts one generator with a 40 GB cache, at most eight connections,
shared worker pools and an isolated runtime directory. It copies the Lua resource
and writes the endpoint/profile into its private `EarthSync.runtime.json` when the
service is listening. It creates a private `.world-token` in the data directory.
Do not commit or distribute the generated server config/token as a public client
mod. Clients obtain connection settings through the connected BeamMP resource.

Start BeamMP-Server separately as usual. The resource reloads endpoint settings
when a player asks for bootstrap, so the world service can start before or after
BeamMP. For reliable testing, restart both services and reconnect players after
changing generator code/options.

Without `--tls-cert`/`--tls-key`, the asset socket is authenticated but not
encrypted and targets a trusted private network/VPN. With those options, the
host announces client-bridge mode and the separate bridge verifies its TLS
certificate. See the bridge guide before using Internet mode. The shared token
is a connection credential, not anticheat.

## What happens on a player's PC

1. BeamMP downloads and mounts the client ZIP.
2. The mod asks the server resource for the world-service endpoint.
3. It connects, authenticates and receives the shared generator profile.
4. For each control message, the server sends the required generated files first.
   Nested JSON geometry dependencies and world-map image files are included.
5. The client assembles bounded chunks and checks the written bytes through VFS
   before exposing the control message to the terrain/mesh loader.
6. Geographic vehicle synchronization works as in alpha.1; distant vehicles are
   represented as data until they enter the locally loaded physics area.

The whole planet is available on demand; it is not preloaded into a 40 GB ZIP or
loaded into every player's RAM. Different players may explore different places.
They share the central source cache and generator. Terrain interpolation at
different local origins still needs live collision comparison; this is not a
proof of identical collision meshes at every point.

## Validation and remaining work

Automated tests cover real TCP authentication, eight accepted clients with a
ninth rejected, read-only cache controls, matching central profiles, binary
terrain delivery for two independent destinations, dependency order, content
deduplication, invalid paths/chunks, bounded sender queues, cleanup preserving
all eight origins and physics blocks, and Lua VFS assembly.

The full game/launcher has not yet been tested with two or eight real players.
In particular, validate binary `writeFile` behavior in the installed BeamNG
version, reconnect/rebase timing, world-map streaming, pooled geometry reuse,
collision agreement and sustained bandwidth under driving. Automated transport
tests are not eight-player performance measurements.

Alpha.3 adds tests for real TLS through the bridge into the headless generator,
binary transfer, rejecting an untrusted certificate, shared eight-sender file
reuse, upload pacing, regional raster reprojection and local DEM fallback.

Code is in branch `beammp/earth-sync`; use alpha.3 packages for these additions.
The older [distributed setup](BEAMMP.md) remains available for comparison.
