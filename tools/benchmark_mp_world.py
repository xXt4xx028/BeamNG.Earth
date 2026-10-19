"""Reproduce outer-LOD selection/capacity comparisons, without network or game FPS claims."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import farfield
import performance

POSITIONS = [(0., 0.), (123.25, 567.5), (-3200., 1900.), (10000., 10000.)]


def benchmark():
    layout = farfield.Layout(64, 512, True)
    configs = {'previous_horizon_minimum': (80000, 1.), 'fixed_12km': (12000, 1.)}
    configs.update({name: (p['far_radius'], p['lod_scale']) for name, p in performance.PROFILES.items()})
    rows = {}
    near = {}
    for name, (radius, scale) in configs.items():
        counts, times = [], []
        extra = {'max_level': farfield.HORIZON_MAX_LEVEL, 'disc': True} if name == 'previous_horizon_minimum' else {}
        for position in POSITIONS:
            for _ in range(10):
                started = time.perf_counter()
                selected, _ = farfield.select(*position, radius=radius, layout=layout,
                    min_level=layout.min_level, kfun=lambda level: layout.k(level) * scale, **extra)
                times.append((time.perf_counter() - started) * 1000)
            exact = {k for k, t in selected.items() if t.level == layout.exact_level}
            if name == 'previous_horizon_minimum':
                near[position] = exact
            assert exact == near[position], (name, position, 'near geometry changed')
            counts.append(len(selected))
        rows[name] = {'radiusM': radius, 'outerKScale': scale, 'tilesPerPosition': counts,
                      'meanTiles': statistics.mean(counts),
                      'meanAssetTriangles': statistics.mean(counts) * layout.tris,
                      'medianSelectorMs': round(statistics.median(times), 4),
                      'exactNearKeysUnchanged': True, 'disc': bool(extra)}
    baseline = rows['previous_horizon_minimum']['meanTiles']
    for row in rows.values():
        row['tileReductionPercent'] = round((1 - row['meanTiles'] / baseline) * 100, 2)
    return {'at': datetime.now(timezone.utc).isoformat(), 'version': (ROOT / 'VERSION').read_text().strip(),
            'scope': 'stateless real farfield.select; no DEM, generation, I/O, transitions, VFS, physics or render',
            'cells': 64, 'block': 512, 'positions': POSITIONS, 'trisPerAsset': layout.tris,
            'meanNearExactTiles': statistics.mean(map(len, near.values())), 'profiles': rows,
            'demCacheCapacityMiB': {'previous_7_processes': 7 * 512, 'balanced_7_processes': 7 * (512 // 7)},
            'memoryCaveat': 'LRU data capacity only, not measured RAM/RSS; query/game/working arrays additional',
            'fpsMeasured': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = json.dumps(benchmark(), indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result + '\n', encoding='utf-8')
    print(result)
