"""Small coverage probe, not a bulk downloader or a terrain-accuracy measurement."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import netfetch
from PIL import Image

PLACES={
    'sierra_madre_occidental':(27.52,-107.81),
    'sierra_madre_oriental':(25.35,-100.15),
    'sierra_madre_sur':(16.14,-96.47),
    'eje_volcanico':(19.12,-98.64),
    'bariloche':(-41.15,-71.30),
    'el_chalten':(-49.33,-72.88),
    'coyhaique':(-45.57,-72.07),
    'torres_del_paine':(-50.94,-73.40),
}


def probe():
    fetcher=netfetch.Fetcher()
    jobs=[]
    for name,(lat,lon) in PLACES.items():
        for provider,z,template in [
            ('mapterhorn',12,'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'),
            ('mapterhorn',15,'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'),
            ('eox2023',14,'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg')]:
            n=2**z
            x=int((lon+180)/360*n)
            y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
            jobs.append((name,lat,lon,provider,z,template.format(z=z,x=x,y=y)))
    def check(job):
        name,lat,lon,provider,z,url=job
        result={'place':name,'lat':lat,'lon':lon,'provider':provider,'zoom':z}
        start=time.monotonic()
        try:
            body=fetcher.get(url).body
            image=Image.open(io.BytesIO(body)); image.load()
            result.update(status='image',bytes=len(body),size=list(image.size))
        except netfetch.NotFound:
            result['status']='not_found'
        except (netfetch.FetchError,OSError,ValueError) as error:
            result.update(status='unavailable',error=type(error).__name__)
        result['seconds']=round(time.monotonic()-start,3)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(check,jobs))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result={'note':'Endpoint availability at sample points; not measured spatial accuracy. A z15 miss can fall back to coarser data.',
            'probes':probe()}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(f"{args.out}: {len(result['probes'])} small coverage probes")
