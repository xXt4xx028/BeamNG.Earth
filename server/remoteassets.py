"""Ordered file delivery for remote Earth clients, before their control messages.

Only generated files below <user>/temp/beamngEarth are exposed. Clients cannot
request arbitrary files. The sender walks dependencies from server-owned JSON.
"""
import asyncio
import base64
import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import protocol

PREFIX = '/temp/beamngEarth/'
CHUNK = 48 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_DEPENDENCIES = 256
MAX_BATCH = 64 * 1024 * 1024


@dataclass(frozen=True)
class Blob:
    body: bytes
    digest: str


class SharedFiles:
    """Bounded shared read/hash cache; pooled filenames are checked for changes."""
    def __init__(self, max_bytes=128*1024*1024):
        self.max_bytes, self.bytes = max_bytes, 0
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.reads = self.hits = 0

    def read(self, path):
        # Single lock also coalesces concurrent first reads by the eight senders.
        with self.lock:
            stat = path.stat()
            stamp = (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            old = self.entries.get(path)
            if old and old[0] == stamp:
                self.entries.move_to_end(path)
                self.hits += 1
                return old[1]
            if stat.st_size > MAX_FILE:
                raise ValueError('asset exceeds transfer limit')
            body = path.read_bytes()
            after = path.stat()
            if stamp != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('asset changed during read; reconnect after generation completes')
            self.reads += 1
            blob = Blob(body,hashlib.sha256(body).hexdigest())
            if old:
                self.bytes -= len(self.entries.pop(path)[1].body)
            if len(body) <= self.max_bytes:
                self.entries[path] = (stamp,blob)
                self.bytes += len(body)
                while self.bytes > self.max_bytes:
                    self.bytes -= len(self.entries.popitem(last=False)[1][1].body)
            return blob


class Pacer:
    """Reserve one small frame at a time; shared instance caps aggregate Earth upload."""
    def __init__(self, bytes_per_second):
        self.rate = bytes_per_second
        self.next = 0.0

    async def wait(self, size):
        if self.rate <= 0:
            return
        now = asyncio.get_running_loop().time()
        start = max(now,self.next)
        self.next = start + size/self.rate
        if start > now:
            await asyncio.sleep(start-now)


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


def assets(user_dir, message, store=None):
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
        blob = store.read(path) if store else Blob(path.read_bytes(),'')
        body = blob.body
        if sum(len(v.body) for v in found.values() if v is not None) + len(body) > MAX_BATCH:
            raise ValueError('asset batch exceeds memory limit')
        found[vfs] = None  # cycle guard
        if path.suffix == '.json':
            for dep in references(json.loads(body)):
                visit(dep)
        found.pop(vfs)
        found[vfs] = blob

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
    def __init__(self, writer, user_dir, queue_size=256, store=None, global_pacer=None, client_rate=0):
        self.writer, self.user_dir = writer, user_dir
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.sent = {}
        self.task = None
        self.store = store
        self.global_pacer = global_pacer
        self.pacer = Pacer(client_rate)
        self.wire_bytes = 0

    def start(self):
        self.task = asyncio.create_task(self.run())

    def put(self, message):
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.writer.close()  # backpressure: bounded RAM instead of an unlimited stream

    async def emit(self, message):
        frame = protocol.encode(message)
        await self.pacer.wait(len(frame))
        if self.global_pacer:
            await self.global_pacer.wait(len(frame))
        self.writer.write(frame)
        self.wire_bytes += len(frame)
        await self.writer.drain()

    async def deliver(self, message):
        if message.get('type') == 'asset_delete':
            # A pooled filename may have been reused after deletion was queued.
            if self.sent.get(message['path']) == message.get('digest'):
                self.sent.pop(message['path'],None)
                await self.emit(message)
            return
        files = await asyncio.to_thread(assets, self.user_dir, message, self.store)
        for path, blob in files.items():
            body = blob.body
            digest = blob.digest or hashlib.sha256(body).hexdigest()
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
