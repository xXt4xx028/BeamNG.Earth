# BeamNG.Earth — experimental BeamMP integration

For the newer **central 40 GB / 8-player host mode**, use [BEAMMP-CENTRAL.md](BEAMMP-CENTRAL.md).
The local-generator instructions below describe the earlier distributed mode.

This fork targets **independent exploration**: each player streams the area around
their own vehicle, with their own floating origin. Coordinates received from
another player are converted through the geographic frames before BeamMP uses
them. Players can visit different continents without forcing each other's map
to teleport.

Status: **alpha; automated tests only, no live two-client validation yet**.
The adapter was checked against the public GE interfaces in BeamMP's
`development` branch on 2026-10-18. Compatibility with an installed BeamMP
release still requires the live test below. Do not present this as a finished
multiplayer release.

## What is synchronized

- Initial spawns, continuous positions, orientations, linear/angular velocities
  and resets carry the sender's geographic origin and session identity.
- A server resource accepts clients with the same generator compatibility
  fingerprint. It covers Python source code, project version, data release IDs,
  relevant geometry options, imagery chain and season mode.
- Remote vehicles are retained as geographic data while distant. They spawn
  locally only inside the currently loaded physics terrain, with entry/exit
  margins and a 2 km three-dimensional relevance limit. Simulation authority
  remains with the vehicle's owner through BeamMP.
- Origin changes remove the local representations of remote vehicles, clear
  BeamMP's GE position smoother and briefly fence spatial updates. Latest
  geographic poses are converted again after the new terrain is committed.
- Different player locations remain independent; ordinary BeamMP traffic
  continues using its normal transport.

**This does not broadcast every generated map file or load the whole planet on
every PC.** The fingerprint is a compatibility check, not a proof of byte-identical
tiles. Elevation/imagery fallback, upstream data changes, asynchronous refinement,
different anchors' terrain interpolation and engine behavior can still produce
differences. Authoritative terrain snapshots and per-tile hash reconciliation are
not implemented. Co-located collision agreement must be measured in game.

## Build

From the repository root with Python 3.10+:

```powershell
python tools/package_beammp.py
```

Output under `dist/beammp/`:

- `Resources/Client/beamng_earth_mp.zip`: client mod/map with paths rooted at
  `lua/`, `levels/`, `scripts/`, etc.
- `Resources/Server/EarthSync/`: BeamMP server compatibility resource.
- `BeamNG.Earth-BeamMP-companion-source.zip`: local Python generator for players.
- `README-BEAMMP.md` and `build.json`.

The build command only creates artifacts; it does not install or launch a game.

## Server setup

1. Copy the generated `Resources` contents into a dedicated test BeamMP server.
2. Set `Map = "/levels/beamng_earth/info.json"` in its `ServerConfig.toml`.
3. Ensure the Earth client ZIP is the only installed copy of this mod. An old
   unpacked upstream copy can shadow files from the server ZIP.
4. Start the BeamMP server normally. No world-generation Python process needs
   to run on the dedicated BeamMP server in this design.
5. `EarthSync.json` can pin a known client profile by its 64-character hash.
   With `"profile": null`, the first compatible hello locks the profile for that
   server process. To use different generator settings, restart the server and
   reconnect clients. After a resource/session restart, reconnect and respawn.

## Each player's PC

Unpack the companion source, create an environment, and install its requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
.\.venv\Scripts\python.exe server/earthd.py --user-dir "ACTUAL_BEAMNG_USER_FOLDER" --cache-cap 10 --workers 2 --road-processes 1 --load-boost off
```

Use the **actual user folder selected by BeamNG**, containing `temp` and `mods`.
All players must use the same companion source and options that affect geometry
or source selection. CPU worker counts and cache caps may differ.

Join through the BeamMP launcher, keeping the companion running. Do not use the
upstream Earth launcher to start an additional single-player game or replace
this fork with an upstream binary.

Check in the GE console:

```lua
dump(beamngEarth_core.multiplayerStatus())
```

Wait for `accepted = true` and `ready = true`. A missing local generator or server
resource prevents the geographic handshake. Initial spatial spawns are queued
until the local terrain and session are ready. The adapter temporarily disables
BeamMP's spawn queue in this level, then restores the preference when leaving.
For initial tests, disable automatically generated traffic and parked cars.

## Disk and CPU planning

Map downloads grow as places are explored. The upstream cache cap defaults to
**20 decimal GB per PC**; `--cache-cap 10` starts with a 10 GB budget. This is an
eviction target, not a hard quota: recently used data and some protected files
are retained, so the cache can exceed it temporarily. Generated session files
under the game's `temp/beamngEarth` are additional disk use. The source, mod,
environment and BeamNG itself are also outside the cache budget.

Start with **15–25 GB free** for this experiment using a 10 GB cache, or
**30–40 GB free** with the 20 GB default. Those are planning reserves, not measured
upper bounds. A long session or large recently used region can need more.
There is no complete-Earth download in this implementation.

The development PC has a Ryzen 7 5700X (8 cores/16 logical CPUs). A reasonable
initial *budget* for the local generator is roughly **10–30% of total CPU** while
streaming, with **30–60% or higher bursts** possible when entering uncached areas.
These percentages are engineering estimates, **not a benchmark**. The game,
vehicle physics and BeamMP add their own load. On 16 logical CPUs one fully busy
logical CPU is about 6.25% of Task Manager's total; SMT does not make this a
linear performance model. The upstream automatic core separation works on Linux;
do not assume it limits Windows CPU usage.

Hosting the BeamMP server on the same PC does not make that PC generate every
other player's terrain: each player runs their own generator. Many nearby
vehicles can still make the host's game much heavier.

Measure during a drive with the optional observer:

```powershell
.\.venv\Scripts\python.exe -m pip install psutil
.\.venv\Scripts\python.exe tools/mp_resources.py --seconds 30 --user-dir "ACTUAL_BEAMNG_USER_FOLDER" --out resources.json
```

It reports generator-process-tree CPU normalized to the machine, summed RSS
(shared memory can be counted more than once), cache size and temporary map files.
It excludes the game/server. `generatorDetected = false` means no running source
generator was found; zeros in that case are not a load benchmark. For a packaged
launcher, pass its root `--pid` explicitly.

## Required live test before wider use

1. Two clients with matching profiles join, spawn, drive beside each other and
   make contact. Check positions, collision heights, reset and vehicle edits.
2. One client goes to a different city/continent. Verify the other client stays
   put and no distant vehicle is spawned at huge local coordinates.
3. They return to the same location. Verify cached spawns use the latest position.
4. Cross a floating-origin boundary while both are nearby, then while separated.
   Check for stale corrections, vehicle damage and packet timing around the fence.
5. Test a late join, disconnection/reconnection, player ID reuse, a companion
   restart, missing downloads and conflicting generator options.
6. Repeat while measuring CPU/RAM/disk, with a cold and warm cache.

Remaining limitations include unvalidated GE/VE queue timing around rebases,
remote edit/coupler handling while vehicles are dormant, data-only players not
appearing in native vehicle-dependent UI until locally spawned, and a bounded
cache of 128 remote vehicles per client. Metadata preservation by the complete
launcher/server chain still needs live confirmation. Terrain ownership stays
local; this is not authoritative server physics or exact map-file replication.
