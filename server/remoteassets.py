"""Ordered file delivery for remote Earth clients, before their control messages.

Only generated files below <user>/temp/beamngEarth are exposed. Clients cannot
request arbitrary files. The sender walks dependencies from server-owned JSON.
"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path

import protocol

PREFIX = '/temp/beamngEarth/'
CHUNK = 48 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_DEPENDENCIES = 256
MAX_BATCH = 64 * 1024 * 1024


def reconcile_cache_once(disk):
    # Worker processes share this directory but do not all update the parent's
    # in-memory index. Reconcile actual files before applying the shared budget.
    disk.scan()
    disk.evict()


async def reconcile_cache(disk, interval=120):
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(reconcile_cache_once,disk)


def local_path(user_dir, vfs):
    if not isinstance(vfs, str) or not vfs.startswith(PREFIX) or '\\' in vfs:
        raise ValueError('not a generated Earth path')
    parts = vfs[len(PREFIX):].split('/')
    if any(not p or p in ('.', '..') or ':' in p for p in parts):
        raise ValueError('invalid generated path')
    root = (Path(user_dir) / 'temp' / 'beamngEarth').resolve()
    result = root.joinpath(*parts).resolve()
    if not result.is_relative_to(root):
        raise ValueError('generated path escapes root')
    return result


def references(value):
    if isinstance(value, str) and value.startswith(PREFIX):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def assets(user_dir, message):
    """Dependencies first; return immutable bytes before another worker can reuse a slot."""
    found = {}

    def visit(vfs):
        if vfs in found:
            return
        if len(found) >= MAX_DEPENDENCIES:
            raise ValueError('too many asset dependencies')
        path = local_path(user_dir, vfs)
        if path.stat().st_size > MAX_FILE:
            raise ValueError('asset exceeds transfer limit')
        body = path.read_bytes()
        if sum(len(v) for v in found.values() if v is not None) + len(body) > MAX_BATCH:
            raise ValueError('asset batch exceeds memory limit')
        found[vfs] = None  # cycle guard
        if path.suffix == '.json':
            for dep in references(json.loads(body)):
                visit(dep)
        found.pop(vfs)
        found[vfs] = body

    for vfs in references(message):
        visit(vfs)
    # The map's protocol announces coordinates, not filenames.
    if message.get('type') == 'map_tiles_ready':
        import maptiles
        root = Path(user_dir) / 'temp' / 'beamngEarth' / 'maptiles'
        for z, x, y, ok, layer in message.get('tiles', []):
            if ok:
                path = Path(maptiles.tile_path(str(root), layer, z, x, y))
                visit('/' + path.relative_to(user_dir).as_posix())
    return found


class Sender:
    def __init__(self, writer, user_dir, queue_size=256):
        self.writer, self.user_dir = writer, user_dir
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.sent = {}
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    def put(self, message):
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.writer.close()  # backpressure: bounded RAM instead of an unlimited stream

    async def emit(self, message):
        self.writer.write(protocol.encode(message))
        await self.writer.drain()

    async def deliver(self, message):
        if message.get('type') == 'asset_delete':
            # A pooled filename may have been reused after deletion was queued.
            if self.sent.get(message['path']) == message.get('digest'):
                self.sent.pop(message['path'],None)
                await self.emit(message)
            return
        files = await asyncio.to_thread(assets, self.user_dir, message)
        for path, body in files.items():
            digest = hashlib.sha256(body).hexdigest()
            if self.sent.get(path) == digest:
                continue
            await self.emit({'type': 'asset_begin', 'path': path, 'bytes': len(body), 'digest': digest})
            for offset in range(0, len(body), CHUNK):
                await self.emit({'type': 'asset_chunk', 'path': path, 'offset': offset,
                                 'data': base64.b64encode(body[offset:offset + CHUNK]).decode('ascii')})
            await self.emit({'type': 'asset_end', 'path': path})
            self.sent[path] = digest
        await self.emit(message)

    async def run(self):
        try:
            while True:
                message = await self.queue.get()
                await self.deliver(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.writer.close()  # never deliver control messages whose files are missing

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
