import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class KitReorganizationTests(unittest.TestCase):
    def test_standalone_distribution_bytes(self):
        source = (ROOT / "drivers/micropython/robot_arm.py").read_bytes()
        for path in ["robot_arm.py", "code/robot_arm.py"]:
            self.assertEqual(source, (ROOT / path).read_bytes())
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["urls"], [["robot_arm.py", "code/robot_arm.py"]])

    def test_legacy_identity_is_preserved(self):
        for old, new in [("camera_server", "camera.server"), ("experiment_recorder", "recording.recorder"), ("experiment_safety", "safety.experiment"), ("pc_control", "host_control.pc_uart"), ("cv_pipeline.contour_axis_2d", "examples.historical_poc.green_arms.cv_pipeline.contour_axis_2d")]:
            self.assertIs(importlib.import_module(old), importlib.import_module(new))

    def test_generic_geometry_has_no_device_dependency(self):
        code = "import sys; from perception.algorithms.axis import fit_axis; assert not any('mr_robot' in n or 'experiment_safety' in n or n == 'serial' for n in sys.modules); r=fit_axis([(x,2*x) for x in range(20)]); assert r['residual_p95_px'] < .01"
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)

    def test_static_assets_and_traversal(self):
        from simulator.serve import Handler
        h = object.__new__(Handler)
        h.directory = str(ROOT / "simulator")
        for path in ["/models/custom_gripper/model.json", "/models/upstream/CAD Files/robot_arm.step", "/models/gripper_camera_mount/assembly.step", "/mechanical/photo_reconstruction/parts/base.stl"]:
            self.assertTrue(Path(h.translate_path(path)).is_file(), path)
        for path in ["/mechanical/../.runtime/secret", "/models/upstream/../../README.md"]:
            self.assertFalse(Path(h.translate_path(path)).is_file(), path)

    def test_direct_image_is_actual_jpeg_without_algorithm_import(self):
        from observation.multimodal import snapshot
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"\xff\xd8example\xff\xd9"
        with tempfile.TemporaryDirectory() as d, patch("observation.multimodal.urlopen", return_value=Response()):
            path = Path(d) / "frame.jpg"
            record = snapshot("http://camera", path)
            self.assertTrue(path.read_bytes().startswith(b"\xff\xd8"))
            self.assertEqual(record.frame_id, json.loads(path.with_suffix(".json").read_text())["frame_id"])

if __name__ == "__main__": unittest.main()
