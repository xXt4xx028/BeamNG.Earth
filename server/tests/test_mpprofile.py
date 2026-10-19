import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mpprofile import profile


class MPProfileTest(unittest.TestCase):
    def test_order_does_not_change_identity(self):
        self.assertEqual(profile('v', 'r', {'a': 1, 'b': 2}), profile('v', 'r', {'b': 2, 'a': 1}))

    def test_source_and_geometry_changes_reject_compatibility(self):
        base = profile('v', 'r', {'block': 512})['id']
        for v, r, options in [('v2', 'r', {'block': 512}), ('v', 'r2', {'block': 512}),
                               ('v', 'r', {'block': 1024})]:
            self.assertNotEqual(base, profile(v, r, options)['id'])

    def test_nonfinite_cannot_be_fingerprinted(self):
        with self.assertRaises(ValueError):
            profile('v', 'r', {'bad': float('nan')})
