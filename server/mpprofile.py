"""Compatibility fingerprint for local Earth generators; not a hash of downloaded tiles."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

SCHEMA = 1


@lru_cache(maxsize=1)
def source_digest():
    """Pin Python generator code as well as the upstream's coarse API version."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
    return digest.hexdigest()


def profile(version, release, options):
    manifest = {"schema": SCHEMA, "generator": version, "overture": release, "options": options}
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"id": hashlib.sha256(encoded).hexdigest(), "manifest": manifest}


def for_server(server, version):
    import overture
    import mapdata
    import maprasters
    import heightmap
    import updates
    return profile(version, overture.RELEASE, {
        "version": updates.local_version(),
        "code": source_digest(),
        "localElevation": getattr(getattr(server.dem, 'local_dem', None), 'identity', None),
        "pipeline": mapdata.VERSION,
        "worldcover": maprasters.WORLDCOVER_RELEASE,
        "canopy": maprasters.CHM_RELEASE,
        "block": server.layout.block,
        "cells": server.layout.cells,
        "square": heightmap.SQUARE,
        "nearVisual": server.near_visual,
        "surface": server.surface is not None,
        "roads": server.mapdata is not None,
        "grading": server.grading,
        "buildings": server.buildings,
        "sidewalks": server.sidewalks,
        "airports": server.airports is not None,
        "sea": server.sea is not None,
        "imagery": [s.name for s in server.imagery.chain] if server.imagery is not None else [],
        "season": getattr(server.imagery, 'season_mode', 'off'),
    })
