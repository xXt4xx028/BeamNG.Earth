"""Immutable regional elevation overlays, prepared offline by import_elevation.py.

Files are float32 512px Web-Mercator tiles. NaN means use the normal provider.
Restart the world service after an import; every worker pins the same manifest.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

TILE = 512


class Store:
    def __init__(self, root=None):
        self.root = Path(root).resolve() if root else None
        self.manifest = None
        self.identity = None
        self.credits = ''
        if self.root and (self.root / 'manifest.json').exists():
            body = (self.root / 'manifest.json').read_bytes()
            self.manifest = json.loads(body)
            if self.manifest.get('schema') != 1 or not isinstance(self.manifest.get('tiles'), dict):
                raise ValueError('unsupported local elevation manifest')
            for key, digest in self.manifest['tiles'].items():
                parts = key.split('/')
                if len(parts) != 3 or any(not p.isdigit() for p in parts):
                    raise ValueError('invalid local elevation tile key')
                z, x, y = map(int, parts)
                if not 0 <= z <= 15 or not 0 <= x < 2**z or not 0 <= y < 2**z:
                    raise ValueError('local elevation tile out of range')
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('invalid local elevation digest')
            self.identity = hashlib.sha256(body).hexdigest()
            self.credits = self.manifest.get('attribution', 'Local elevation')

    def tile(self, key):
        name = '/'.join(map(str, key))
        digest = self.manifest['tiles'].get(name) if self.manifest else None
        if digest is None:
            return None
        path = (self.root / (name + '.npy')).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('local elevation path escapes root')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError('local elevation changed: restart/reimport before driving')
        import io
        data = np.load(io.BytesIO(body), allow_pickle=False)
        if data.shape != (TILE, TILE) or data.dtype != np.float32 or np.isinf(data).any():
            raise ValueError('invalid local elevation array')
        return data
