"""Package migration regressions using imports and mocked UI, without hardware."""
import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_legacy_imports_share_canonical_module_state(self):
        for name in ('contour_axis_2d', 'experiment_cv', 'experiment_phases',
                     'experiment_runner', 'phase_r_runner', 'phase_r_v11',
                     'operator_homing', 'monitor_pose'):
            with self.subTest(module=name):
                self.assertIs(importlib.import_module(name),
                              importlib.import_module('cv_pipeline.' + name))
        self.assertIs(importlib.import_module('exploration_monitor'),
                      importlib.import_module('visual_observation.monitor'))

    def test_moved_modules_keep_original_runtime_root(self):
        for name in ('embodied_demo', 'recovery_workflow', 'run_embodied_experiment'):
            with self.subTest(module=name):
                self.assertEqual(importlib.import_module('cv_pipeline.' + name).ROOT, ROOT)

    def test_visual_import_has_no_cv_or_serial_dependency(self):
        program = (
            'import sys; import visual_observation.monitor; '
            'assert not any(n == "cv_pipeline" or n.startswith("cv_pipeline.") '
            'for n in sys.modules); '
            'assert "cv2" not in sys.modules; assert "serial" not in sys.modules'
        )
        result = subprocess.run([sys.executable, '-B', '-c', program], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_visual_and_legacy_defaults_and_paths(self):
        from visual_observation import monitor
        for default_skeleton in (False, True):
            with self.subTest(default_skeleton=default_skeleton):
                with patch.object(monitor.tk, 'Tk'), patch.object(monitor, 'Monitor') as window:
                    monitor.main([], default_skeleton=default_skeleton)
                arguments = window.call_args.args[1]
                self.assertEqual(arguments.no_skeleton, not default_skeleton)
                self.assertEqual(arguments.events, ROOT / '.runtime')
                self.assertEqual(arguments.pose_library, ROOT.parent / 'Mr-Robot-Arm')


if __name__ == '__main__':
    unittest.main()
