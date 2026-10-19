import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
sys.path.insert(0,str(ROOT/'tools'))
import dem
import localdem


class LocalDemTest(unittest.TestCase):
    def pack(self, root, data):
        path=Path(root)/'12/735/1812.npy'
        path.parent.mkdir(parents=True)
        np.save(path,data,allow_pickle=False)
        manifest={'schema':1,'attribution':'INEGI test fixture','verticalReference':'test',
                  'tiles':{'12/735/1812':hashlib.sha256(path.read_bytes()).hexdigest()}}
        (Path(root)/'manifest.json').write_text(json.dumps(manifest))
        return path

    def test_full_regional_tile_skips_network_and_ground_filter(self):
        with tempfile.TemporaryDirectory() as root:
            data=np.full((512,512),2345,np.float32)
            self.pack(root,data)
            source=dem.Dem(str(Path(root)/'cache'),local_dir=root)
            try:
                with patch.object(source,'_load_remote_tile',side_effect=AssertionError('no network')):
                    np.testing.assert_array_equal(source._load_tile((12,735,1812)),data)
                self.assertEqual(source.served[(12,735,1812)],'local')
                self.assertIsNotNone(source.local_dem.identity)
            finally:
                source.pool.shutdown(); source.urgent_pool.shutdown()

    def test_nodata_falls_back_and_modified_pack_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            data=np.full((512,512),100,np.float32); data[0,0]=np.nan
            path=self.pack(root,data)
            source=dem.Dem(str(Path(root)/'cache'),local_dir=root)
            try:
                with patch.object(source,'_load_remote_tile',return_value=np.full((512,512),50,np.float32)):
                    result=source._load_tile((12,735,1812))
                self.assertEqual((result[0,0],result[1,1]),(50,100))
                path.write_bytes(b'changed on disk')
                with self.assertRaisesRegex(ValueError,'changed'):
                    source._load_tile((12,735,1812))
            finally:
                source.pool.shutdown(); source.urgent_pool.shutdown()

    def test_bad_manifest_path_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'manifest.json').write_text(json.dumps({'schema':1,'tiles':{'../secret/file':'a'*64}}))
            with self.assertRaises(ValueError): localdem.Store(root)

    def test_real_raster_reprojection_and_bounded_import(self):
        try:
            import rasterio
        except ImportError:
            self.skipTest('optional rasterio not installed')
        import import_elevation
        from rasterio.transform import from_bounds
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); source=root/'regional.tif'
            span=2*import_elevation.HALF/2**12
            left=735*span-import_elevation.HALF; top=import_elevation.HALF-1812*span
            data=np.full((512,512),2040,np.float32)
            with rasterio.open(source,'w',driver='GTiff',width=512,height=512,count=1,dtype='float32',
                               crs='EPSG:3857',transform=from_bounds(left,top-span,left+span,top,512,512),
                               nodata=-9999) as raster:
                raster.write(data,1)
            result=import_elevation.prepare(source,root/'out','INEGI fixture','test datum',12,12,4,vertical_offset=3)
            store=localdem.Store(root/'out')
            np.testing.assert_allclose(store.tile((12,735,1812)),2043)
            self.assertEqual(result['verticalOffsetM'],3)
            with self.assertRaisesRegex(ValueError,'budget'):
                import_elevation.prepare(source,root/'too-big','credit','datum',12,15,1)


if __name__ == '__main__': unittest.main()
