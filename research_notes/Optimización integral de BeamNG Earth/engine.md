# BeamNG engine, frame scheduling, rendering and LOD

Research date: 2026-10-18. Scope is the alpha.4 checkout before this optimization pass. Ranked below by expected usefulness, not measured FPS gain. Historical in-game evidence belongs to the upstream author's Linux/Vulkan/RX 7900 XTX session; it is not a benchmark of Bryan's Windows installation. [Upstream test setup](../../docs/research/2026-10-11-engine-probes.md#L10)

## 1. Can Forest work violate the existing streaming governor?

### Takeaway
Yes. Make Forest work respect heavy/quiet frames and charge its measured Lua cost to the same governor while retaining its existing shape/item limits. This closes a scheduling hole without removing vegetation.

### Cited Findings
- `core.lua:1216-1221` runs governed roads/farfield, then calls `trees.update(anchorId, player)` without a governor. `trees.lua:451-460` has a separate 750-item allowance every third frame. [Core](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L1216) · [Trees](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/trees.lua#L451)
- The governor deliberately reserves quiet frames around heavy operations, and accounts for deferred engine debt. [Governor lines 13-17 and 208-214](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L13)
- Forest is the correct engine primitive for repeated vegetation; replacing it with thousands of TSStatics would discard engine culling, shared shapes and batching. [Official Forest documentation](https://documentation.beamng.com/modding/levels/level_classes/forest/)

### Inferences
- Preserve the pooled small Forests and shape-touch cap. Add an optional governor parameter; defer creation/removal on blocked/heavy frames, measure a bounded batch, charge it, and retain an urgent cleanup path for level unload. Advance the every-third-frame cadence consistently when blocked so work eventually resumes.
- Tests: fake governor denies work and item count remains unchanged; grants work and existing per-frame/shape limits remain; a following frame completes pending items. Replay dense forest + rebase while recording Lua and next-frame engine times.

### Gaps
- The C++ cost is deferred and can exceed the Lua call cost. No current Windows measurement establishes the best batch size; a time cap cannot make an individual engine operation preemptible.

## 2. Why can collision rebuilds still coincide with imports?

### Takeaway
`roads.update` throttles collision rebuild frequency but does not reserve a heavy slot. Move rebuild arbitration before streaming when due; never rely only on elapsed seconds to isolate a rebuild.

### Cited Findings
- `roads.lua:615-621` invokes `be:reloadCollision()` after deletion/creation loops, then charges it as `roadWalk`; no `requestHeavy()` appears on this path. [Roads](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/roads.lua#L615)
- Upstream comments report deferred rebuild frames around 20 ms and later 56 ms with many colliders; these are historical observations, not current-machine results. [Roads rationale lines 34-44](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/roads.lua#L34)
- Official docs recommend dedicated, simpler collision meshes and collision testing at driving speed. [TSStatic collision](https://docs.beamng.com/modding/levels/level_classes/tsstatic/#collision-meshes) · [Level performance](https://docs.beamng.com/modding/levels/level_creation/section8/#853-collision-considerations)

### Inferences
- Request a heavy slot before creation when a scheduled rebuild is due, return while waiting, and rebuild when granted. Terrain commits already acknowledge collision rebuilds. Track newly created nearby colliders so safety deadlines cannot wait indefinitely; retain the existing check that prevents an object becoming solid around the player.
- Tests: no rebuild before grant; no streaming on the granted frame; terrain commit clears duplicate rebuild; long dirty queue eventually rebuilds; deleting a nearby collider does not leave a ghost obstacle indefinitely.

### Gaps
- The exact engine phase of the rebuild varies by version. A governor can isolate work but cannot eliminate a single rebuild hitch.

## 3. What limits rendering after network optimizations?

### Takeaway
Control visible object/material count as well as triangles. Smaller textures alone do not remove per-object draw overhead.

### Cited Findings
- Each textured far tile can create a separate Material and TSStatic. Material creation and shape import are separate governed units. [Farfield lines 351-381 and 1218-1256](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L351)
- BeamNG documents CPU cost from draw calls and multiplication by material/submesh count; material layers themselves do not create extra draw calls. [Official draw-call explanation](https://docs.beamng.com/modding/vehicle/vehicle-art/optimization/draw-calls/)
- Non-dynamic, non-animated TSStatics can use the engine's static manager; `meshCulling` is mainly relevant to its own-instance path and may add overhead. Decorative collision/decal should remain None. [Official TSStatic fields and static rendering](https://docs.beamng.com/modding/levels/level_classes/tsstatic/)

### Inferences
- First add visible/imported/material counters and quality presets that coarsen distant tile selection. Keep `dynamic=false` and `playAmbient=false` explicit for generated shapes if tests confirm defaults; do not blanket-enable meshCulling. Do not add collision to far terrain.
- A texture atlas could reduce material changes only if geometry/material batches are actually combined. It is a larger redesign involving UV gutters, independent arrivals and pooled-file ownership; no automatic draw-call reduction should be promised.
- Tests: compare same route/view with objects/materials/triangles and shadow/render timings. Test distance detail on mountain silhouettes, dense town and forest rather than a single flat scene.

### Gaps
- No retrieved source provides a universal safe object count or a documented runtime API guaranteeing arbitrary generated mesh batching. Avoid inventing either.

## 4. Which allocations can be removed safely right now?

### Takeaway
Skip hidden debug-window preparation and reuse exact scratch buffers. These have clearer correctness boundaries than changing global Lua GC settings.

### Cited Findings
- `core.lua:1078` evaluates `buildView()` and constructs actions every frame even when `ui.draw` returns at `ui.lua:55` because `M.visible=false`. `buildView:1029-1057` builds strings and calls farfield stats. [Core UI](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L1029) · [UI early return](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/ui.lua#L54)
- `governor.lua:133-138` creates/sorts a new median scratch table every non-heavy frame; `farfield.lua:1157` and `1191` create busy/kept tables each update. [Governor median](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L133) · [Farfield update](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L1157)

### Inferences
- Guard `buildView` before calling it; continue banner/credits/status updates. Hoist stable actions. Reuse a per-governor median scratch array with exact length cleanup, preserving the current numeric result. Compact completed groups in place and clear reusable busy keys without retaining old instances.
- Tests: hidden HUD never asks for farfield stats; visible HUD retains fields/actions; median equals existing implementation over ring wrap, odd/even history, heavy-frame exclusion; swap-group ordering unchanged. Benchmark allocation delta and elapsed Lua time separately.

### Gaps
- These remove known work, but do not prove a measurable FPS increase in GPU/physics-limited scenes. No evidence justifies globally retuning GC for the whole game.

## 5. Can stale queues consume unaccounted work?

### Takeaway
Use head-index FIFOs and bound stale-entry cleanup. The current road queues shift arrays on each pop and stale entries can bypass measured charges.

### Cited Findings
- `roads.lua:427`, `575` and `590` use `table.remove(queue,1)`. Charges occur only inside `if t/f ...` branches; dropped tile entries can be removed with no charged work. [Road far queue](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/roads.lua#L426) · [Near queues](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/roads.lua#L574)
- Farfield already has head/tail-index queues and performs stale skips in `peekImport`. [Existing FIFO pattern](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L1041)

### Inferences
- Replace road front-pops with a head/tail queue, reset when empty, and compact at a bounded threshold. Queue length/stats/hasWork must report live range rather than Lua `#` on sparse arrays. Limit stale skips per update or charge measured queue maintenance so teleports with thousands of invalidated entries cannot drain everything in one frame.
- Tests: FIFO order under add/drop/add; reset and rebase preserve ownership; 10,000 stale entries drain across bounded updates and eventually empty; invalid entries cannot starve a valid new nearby tile.

### Gaps
- No current workload measurement gives average queue size. This is algorithmic improvement with a useful stress test, not a claimed game-speed multiplier.

## 6. Why does nearest-tile priority become expensive on large bursts?

### Takeaway
`peekImport` scans the pending range on each material/import attempt. Cache the selected valid instance or maintain a priority ordering refreshed only when arrivals/camera changes justify it.

### Cited Findings
- `farfield.lua:1062-1075` calculates distance and view penalties for all queued candidates; the update loop calls it again after material setup before the same instance's import. [Candidate scan](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L1041) · [Import loop](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L1222)
- Near-first ordering is deliberate: upstream notes describe nearby ground waiting behind distant imports otherwise. [Farfield priority rationale](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L1035)

### Inferences
- Low-risk version: reuse a selected instance within an update while still valid, eliminating the duplicate material-to-shape scan; benchmark before introducing a heap. More advanced priority refresh can be triggered by new tiles, changed anchor, meaningful camera translation/turn or a short timeout. Preserve front-facing bias and prioritize actual player collision/ground availability.
- Tests: nearest/front-facing valid tile still wins; material setup doesn't cause a rescan; stale/drop between operations invalidates cached candidate; rotate camera and priority updates without starvation.

### Gaps
- A heap is not automatically faster when camera-dependent priorities change every frame. Quantify candidate visits, not just Big-O descriptions.

## 7. How should memory and spare tiles scale across PCs?

### Takeaway
Retain lazy reuse, but use a byte estimate alongside object count and a preset cap. Hidden objects still own resources; a disk cache limit does not cap client RAM/VRAM.

### Cited Findings
- Farfield keeps up to 400 hidden spare objects for 120 seconds, reviving identical tiles to avoid repeat imports. [Spare policy lines 103-112](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/farfield.lua#L103)
- Pooled shape/material lifetime must not release a slot while any connection holds it. [Documented ownership](../../docs/ARCHITECTURE.md#L872)
- BeamNG recommends smaller appropriate textures and cooked DDS; doubling each texture dimension multiplies pixel storage by four. [Official texture optimization](https://docs.beamng.com/modding/vehicle/vehicle-art/optimization/materials-and-meshes/)

### Inferences
- Add conservative texture+shape byte estimates per instance and cap spare total by both count and estimated bytes. Low-memory presets should evict spares sooner; do not evict live coverage or release slot serials before object/material references are gone. Preserve DDS/mip chains already generated; converting them back to PNG would introduce client decode/cooking work.
- Tests: repeated out-and-back revisits reuse below limit; byte-heavy tiles evict oldest spares earlier; all material refs and slot serial acknowledgments remain balanced; reset/rebase clears estimated totals. Long-session memory graph needs real game validation.

### Gaps
- Exact GPU residency is not available from these sources; byte estimates are accounting bounds, not an exact VRAM meter.

## 8. Will BeamNG's own quality sliders optimize generated terrain?

### Takeaway
Not sufficiently: generated terrain currently has one mesh detail, so native Mesh Quality cannot select an additional simpler mesh. Expose Earth-specific view/tile settings, and keep near physics safety independent of visual quality.

### Cited Findings
- `server/cdae.py:490` encodes a single normal detail with a 2-pixel minimum. The repository's LOD study identifies the server quadtree as the generated ground's effective LOD. [Encoder](../../server/cdae.py#L490) · [LOD study lines 129-155](../../docs/research/2026-10-14-lod-research.md#L129)
- Native TSStatic detail is selected from screen-space size, affected by camera FOV, viewport size, object scale and global detail bias. [Official TSStatic LOD](https://docs.beamng.com/modding/levels/level_classes/tsstatic/#lod-and-detail-levels)
- BeamNG advises profiling sustained driving, dense vegetation, urban views, night lights and worst long vistas, including after reload. [Official validation guidance](https://docs.beamng.com/modding/levels/level_creation/section8/#86-profiling)

### Inferences
- Earth visual presets should tune distant split error/radius/textures/vegetation while retaining exact near ground and colliders. Use actual viewport/FOV in any screen-error policy. Apply hysteresis and minimum dwell to prevent refinement/thinning oscillation; never regenerate collider data per client visual setting in multiplayer.
- Validate Mexico mountain road/forest, Patagonia open vista, steep cliff and dense settlement with repeatable routes; record p50/p95/p99 frame time, imports/sec, near-ground misses and memory over at least a sustained drive. Keep cold-cache startup separate from warm-cache driving.

### Gaps
- Broad geographic coverage does not imply uniform source quality or universal hardware support. No evidence permits guaranteeing a minimum FPS everywhere or claiming success for eight real players without that test.
