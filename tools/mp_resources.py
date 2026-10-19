"""Measure local Earth generator CPU/RAM and disk use (pip install psutil).

python tools/mp_resources.py --seconds 30 --user-dir PATH
CPU is normalized to the whole machine, like Windows Task Manager.
The game and BeamMP server are excluded. No estimated load is reported as a measurement.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

import psutil


def size(path):
    total = 0
    if path.is_dir():
        for base, dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(base) / name).stat().st_size
                except OSError:
                    pass
    return total


def processes(root_pid=None):
    roots = []
    if root_pid:
        try:
            roots = [psutil.Process(root_pid)]
        except psutil.NoSuchProcess:
            pass
    else:
        for proc in psutil.process_iter(['pid', 'cmdline']):
            if proc.pid == os.getpid():
                continue
            cmd = proc.info['cmdline'] or []
            if any(Path(arg).name.lower() == 'earthd.py' for arg in cmd):
                roots.append(proc)
    found = {}
    for proc in roots:
        try:
            found[proc.pid] = proc
            found.update((p.pid, p) for p in proc.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def measure(seconds, root_pid=None):
    known, samples, peak_memory = {}, [], 0
    peak_processes = 0
    for _ in range(seconds + 1):
        current = processes(root_pid)
        cpu, memory = 0.0, 0
        for pid, proc in current.items():
            try:
                if pid not in known:
                    known[pid] = proc
                    proc.cpu_percent()
                else:
                    cpu += known[pid].cpu_percent()
                memory += proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        peak_processes = max(peak_processes, len(current))
        peak_memory = max(peak_memory, memory)
        if samples or _ > 0:
            samples.append(cpu / (psutil.cpu_count() or 1))
        if _ < seconds:
            time.sleep(1)
    return {'generatorDetected': bool(peak_processes), 'peakProcesses': peak_processes,
            'cpuMeanPercentOfMachine': round(statistics.mean(samples), 2),
            'cpuPeakPercentOfMachine': round(max(samples), 2),
            'peakSummedRssBytes': peak_memory}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--pid', type=int, help='root generator PID, useful for a packaged launcher')
    parser.add_argument('--cache-dir', type=Path, default=Path.home() / '.cache' / 'beamng-earth')
    parser.add_argument('--user-dir', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    data = measure(args.seconds, args.pid)
    data.update({'logicalCpus': psutil.cpu_count(), 'physicalCores': psutil.cpu_count(logical=False),
                 'systemRamBytes': psutil.virtual_memory().total, 'cacheBytes': size(args.cache_dir),
                 'temporaryWorldBytes': size(args.user_dir / 'temp' / 'beamngEarth') if args.user_dir else None})
    encoded = json.dumps(data, indent=2)
    if args.out:
        args.out.write_text(encoded + '\n', encoding='utf-8')
    print(encoded)
