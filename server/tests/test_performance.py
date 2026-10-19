import argparse
import os
import random
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
sys.path.insert(0,str(ROOT/'tools'))
import performance
import dem
import farfield
import imagery
import netfetch
import overture
import start_beammp_world


def options(**overrides):
    values=dict(performance='balanced',workers=3,road_processes=2,block_process='on',roads='on',buildings='off',
                far_radius=80000,tex=None,horizon=None,lod_scale=1,dem_cache_mib=None,image_cache_tiles=None,
                query_memory_mib=None)
    values.update(overrides)
    return argparse.Namespace(**values)


class PerformanceTest(unittest.TestCase):
    def test_preset_disables_horizon_and_honors_explicit_values(self):
        args=options()
        performance.apply_profile(args,[])
        self.assertFalse(args.horizon)
        self.assertEqual((args.far_radius,args.lod_scale),(12000,.85))
        args=options(horizon=True,far_radius=25000)
        performance.apply_profile(args,['--horizon','--far-radius=25000'])
        self.assertTrue(args.horizon)
        self.assertEqual(args.far_radius,25000)
        self.assertIn('--performance',start_beammp_world.command(Path('server'),Path('data'),'host'))

    def test_auto_is_conservative_and_no_preset_preserves_legacy(self):
        for ram,name in [(8,'low'),(16,'balanced'),(32,'balanced')]:
            args=options(performance='auto')
            self.assertEqual(performance.apply_profile(args,[],ram),name)
        args=options(performance=None)
        self.assertIsNone(performance.apply_profile(args,[]))
        self.assertEqual(args.far_radius,80000)

    def test_decoded_dem_budget_is_shared_across_spawned_processes(self):
        args=options(); performance.apply_profile(args,[])
        with patch.dict(os.environ,{},clear=True),tempfile.TemporaryDirectory() as root:
            limits=performance.cache_budget(args)
            self.assertEqual(limits['processes'],7)
            self.assertLessEqual(limits['demMiBTotal'],512)
            source=dem.Dem(root)
            images=imagery.Imagery(root,chain=())
            try:
                self.assertEqual(source.mem_tiles,73)
                self.assertEqual(images.mem_tiles,256)
                self.assertEqual(source.pool._max_workers,6)
            finally:
                source.pool.shutdown(); source.urgent_pool.shutdown(); images.pool.shutdown()

    def test_visual_presets_preserve_exact_near_tiles(self):
        layout=farfield.Layout(64,512,True)
        for px,py in [(0,0),(73,97),(8192,8192),(-300,-700)]:
            reference,_=farfield.select(px,py,radius=80000,min_level=layout.min_level,layout=layout)
            exact={k for k,t in reference.items() if t.level==layout.exact_level}
            for name,profile in performance.PROFILES.items():
                selected,_=farfield.select(px,py,radius=profile['far_radius'],min_level=layout.min_level,
                    layout=layout,kfun=lambda level:layout.k(level)*profile['lod_scale'])
                self.assertEqual({k for k,t in selected.items() if t.level==layout.exact_level},exact)
                self.assertLess(len(selected),len(reference))

    def test_duckdb_connection_uses_explicit_query_budget(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'BEAMNG_EARTH_QUERY_MIB':'384'}):
            reader=overture.Reader(root,netfetch.Fetcher(offline=True))
            try:
                con,_,_=reader._connect({},'demand')
                try:
                    self.assertEqual(con.execute("SELECT current_setting('memory_limit')").fetchone()[0], '384.0 MiB')
                    self.assertEqual(con.execute('SELECT sum(i) FROM range(1000) t(i)').fetchone()[0],499500)
                finally:
                    con.close()
            finally:
                reader.close()

    def test_client_minimum_scale_preserves_near_across_layouts_and_origins(self):
        rng=random.Random(42)
        for cells in (32,64):
            for block in (512,1024):
                layout=farfield.Layout(cells,block,True)
                for _ in range(20):
                    position=(rng.uniform(-16000,16000),rng.uniform(-16000,16000))
                    baseline,_=farfield.select(*position,radius=80000,min_level=layout.min_level,layout=layout)
                    exact={k for k,t in baseline.items() if t.level==layout.exact_level}
                    # Includes Low host (.7) combined with minimum Auto client (.55).
                    for scale in (.7,.55,.7*.55):
                        selected,_=farfield.select(*position,radius=8000,min_level=layout.min_level,
                            layout=layout,kfun=lambda level:layout.k(level)*scale)
                        self.assertEqual({k for k,t in selected.items() if t.level==layout.exact_level},exact)
