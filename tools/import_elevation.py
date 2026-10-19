"""Prepare a local DEM/DTM raster (GeoTIFF/IMG) for the Earth world service.

Optional preparation dependency: pip install rasterio. No rasterio on clients or
in the running generator. Input heights must be metres in a checked vertical datum.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import os

import numpy as np

HALF = 20037508.342789244
SIZE = 512


def prepare(source, output, attribution, vertical_reference, min_zoom=10, max_zoom=15,
            max_tiles=512, bounds=None, vertical_offset=0.0):
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, transform_bounds, Resampling

    if not 0 <= min_zoom <= max_zoom <= 15 or max_tiles < 1:
        raise ValueError('invalid zoom/tile budget')
    if not attribution.strip() or not vertical_reference.strip() or not math.isfinite(vertical_offset):
        raise ValueError('attribution and checked vertical reference are required')
    output = Path(output)
    if (output / 'manifest.json').exists():
        raise ValueError('use a new output directory for each immutable elevation pack')
    with rasterio.open(source) as src:
        if src.crs is None or src.count != 1:
            raise ValueError('need a single-band raster with a horizontal CRS and heights in metres')
        west, south, east, north = transform_bounds(src.crs, 'EPSG:3857', *src.bounds, densify_pts=21)
        if bounds:
            bw, bs, be, bn = bounds
            if not (-180 <= bw < be <= 180 and -85 <= bs < bn <= 85):
                raise ValueError('bounds must be west south east north; no antimeridian crossing')
            clip = transform_bounds('EPSG:4326', 'EPSG:3857', *bounds)
            west, south, east, north = max(west,clip[0]), max(south,clip[1]), min(east,clip[2]), min(north,clip[3])
        if not all(map(math.isfinite, (west,south,east,north))) or west >= east or south >= north:
            raise ValueError('empty or invalid raster extent')
        west, south, east, north = max(-HALF,west), max(-HALF,south), min(HALF,east), min(HALF,north)
        keys = []
        for z in range(min_zoom,max_zoom+1):
            span = 2 * HALF / 2**z
            x0, x1 = max(0,math.floor((west+HALF)/span)), min(2**z-1,math.ceil((east+HALF)/span)-1)
            y0, y1 = max(0,math.floor((HALF-north)/span)), min(2**z-1,math.ceil((HALF-south)/span)-1)
            count = (x1-x0+1)*(y1-y0+1)
            if len(keys)+count > max_tiles:
                raise ValueError('tile budget exceeded: crop a smaller area with --bounds')
            keys += [(z,x,y) for y in range(y0,y1+1) for x in range(x0,x1+1)]
        manifest = {'schema':1,'attribution':attribution,'verticalReference':vertical_reference,
                    'verticalOffsetM':vertical_offset,'sourceName':Path(source).name,'tiles':{}}
        for z,x,y in keys:
            span = 2 * HALF / 2**z
            left, top = x*span-HALF, HALF-y*span
            transform = from_bounds(left,top-span,left+span,top,SIZE,SIZE)
            data = np.full((SIZE,SIZE),np.nan,np.float32)
            # GDAL reads only the windows needed by this destination tile, not the whole raster.
            reproject(rasterio.band(src,1),data,src_transform=src.transform,src_crs=src.crs,
                      src_nodata=src.nodata,dst_transform=transform,dst_crs='EPSG:3857',
                      dst_nodata=np.nan,resampling=Resampling.bilinear,num_threads=1)
            # Crop at texel centres, so a --bounds import never exposes the rest of the input.
            xx = left+(np.arange(SIZE)+.5)*span/SIZE
            yy = top-(np.arange(SIZE)+.5)*span/SIZE
            data[(yy[:,None]<south)|(yy[:,None]>north)|(xx[None,:]<west)|(xx[None,:]>east)] = np.nan
            if not np.isfinite(data).any():
                continue
            if np.isinf(data).any():
                raise ValueError('input produced infinite heights')
            data += vertical_offset
            buffer = io.BytesIO(); np.save(buffer,data,allow_pickle=False)
            body = buffer.getvalue()
            key = f'{z}/{x}/{y}'
            path = output / (key+'.npy')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(body)
            manifest['tiles'][key] = hashlib.sha256(body).hexdigest()
    if not manifest['tiles']:
        raise ValueError('no valid elevation within selected area')
    output.mkdir(parents=True,exist_ok=True)
    temporary = output/'manifest.tmp'
    temporary.write_text(json.dumps(manifest,sort_keys=True,indent=2),encoding='utf-8')
    os.replace(temporary,output/'manifest.json')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--attribution',required=True)
    parser.add_argument('--vertical-reference',required=True,help='record the checked datum; no automatic geoid conversion')
    parser.add_argument('--vertical-offset',type=float,default=0)
    parser.add_argument('--min-zoom',type=int,default=10)
    parser.add_argument('--max-zoom',type=int,default=15)
    parser.add_argument('--max-tiles',type=int,default=512)
    parser.add_argument('--bounds',type=float,nargs=4,metavar=('WEST','SOUTH','EAST','NORTH'))
    args=parser.parse_args()
    try:
        result=prepare(args.source,args.out,args.attribution,args.vertical_reference,args.min_zoom,
                       args.max_zoom,args.max_tiles,args.bounds,args.vertical_offset)
    except ImportError:
        parser.error('install the optional preparation dependency: pip install rasterio')
    except (ValueError,OSError) as error:
        parser.error(str(error))
    print(f"Prepared {len(result['tiles'])} elevation tiles in {args.out}; restart the world service.")
