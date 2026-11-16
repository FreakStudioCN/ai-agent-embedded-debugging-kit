"""Keep legacy standalone MicroPython entry points compatible."""
from pathlib import Path
import unittest


class DistributionTests(unittest.TestCase):
    def test_standalone_copies_match_maintained_sources(self):
        root = Path(__file__).resolve().parents[1]
        for source, destination in [("code/robot_arm.py", "robot_arm.py"), ("code/main.py", "example.py")]:
            with self.subTest(destination=destination):
                self.assertEqual((root / source).read_bytes(), (root / destination).read_bytes())
