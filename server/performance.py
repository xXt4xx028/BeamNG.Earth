"""Optional bounded Earth profiles; collision sampling/near-exact geometry stay unchanged."""
import os

PROFILES = {
    'low': dict(far_radius=8000.0,lod_scale=.7,tex=(128,128,128,64),horizon=False,
                workers=1,road_processes=1,dem_cache_mib=256,image_cache_tiles=128,query_memory_mib=256,
                fetch_threads=4),
    'balanced': dict(far_radius=12000.0,lod_scale=.85,tex=(256,256,128,128),horizon=False,
                     workers=2,road_processes=2,dem_cache_mib=512,image_cache_tiles=256,query_memory_mib=384,
                     fetch_threads=6),
    'scenic': dict(far_radius=40000.0,lod_scale=1.0,tex=(256,256,256,256),horizon=False,
                   workers=2,road_processes=2,dem_cache_mib=1024,image_cache_tiles=512,query_memory_mib=512,
                   fetch_threads=8),
}


def memory_gib():
    """Best-effort physical RAM; unknown machines choose the conservative profile."""
    try:
        if os.name == 'nt':
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                          ('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),
                          ('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                          ('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),
                          ('extended',ctypes.c_ulonglong)]
            status=MemoryStatus(); status.length=ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise OSError('memory unavailable')
            return status.total/2**30
        return os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')/2**30
    except (OSError,ValueError,AttributeError):
        return 8.0


def apply_profile(args,argv,ram_gib=None):
    name=getattr(args,'performance',None)
    if name is None:
        return None
    if name == 'auto':
        name='low' if (memory_gib() if ram_gib is None else ram_gib)<16 else 'balanced'
    explicit={token.split('=',1)[0] for token in argv if token.startswith('--')}
    for key,value in PROFILES[name].items():
        if key == 'fetch_threads':
            continue
        flags={'--'+key.replace('_','-')}
        if key=='horizon': flags.add('--no-horizon')
        if not explicit.intersection(flags):
            setattr(args,key,value)
    args.performance=name
    return name


def cache_budget(args):
    """Apply one DEM decoded-cache budget across the configured spawned processes.

    This bounds these LRUs, not total RSS: tile builds, DuckDB, maps and game RAM
    are additional. Spawn workers inherit the environment before construction.
    """
    processes=1
    if args.block_process=='on':
        processes+=2+args.workers
        if args.roads=='on' and args.road_processes>0:
            processes+=args.road_processes
            if args.buildings=='on': processes+=1
    budget=getattr(args,'dem_cache_mib',None)
    per_process=None
    if budget is not None:
        if budget<processes:
            raise ValueError('DEM cache budget must allow at least 1 MiB per process')
        per_process=budget//processes
        os.environ['BEAMNG_EARTH_DEM_MEM_TILES']=str(per_process)
    images=getattr(args,'image_cache_tiles',None)
    if images is not None:
        os.environ['BEAMNG_EARTH_IMAGE_MEM_TILES']=str(images)
    query=getattr(args,'query_memory_mib',None)
    if query is not None:
        os.environ['BEAMNG_EARTH_QUERY_MIB']=str(query)
    name=getattr(args,'performance',None)
    if name in PROFILES:
        fetch=PROFILES[name]['fetch_threads']
        os.environ['BEAMNG_EARTH_DEM_FETCH_THREADS']=str(fetch)
        os.environ['BEAMNG_EARTH_DEM_URGENT_THREADS']=str(fetch)
        os.environ['BEAMNG_EARTH_IMAGE_FETCH_THREADS']=str(min(6,fetch))
    return {'processes':processes,'demMiBPerProcess':per_process,
            'demMiBTotal':None if per_process is None else per_process*processes,
            'imageTiles':images,'queryMiBPerConnection':query}
