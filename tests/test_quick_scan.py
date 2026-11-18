"""Check route order and failure handling without connecting to hardware."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from quick_scan import Camera as UsbCamera, Frame, ROUTES, ScanError, execute


class Arm:
    pending = None

    def __init__(self, reject=None):
        self.commands = []
        self.pose = 0
        self.reject = reject

    def command(self, command):
        self.commands.append(command)
        if command == self.reject:
            raise OSError("controller alarm")
        if command.startswith("G1"):
            self.pose += 1


class Camera:
    def __init__(self, arm, scores, displaced=False):
        self.arm = arm
        self.scores = iter(scores)
        self.sequence = 0
        self.displaced = displaced

    def capture(self, after=0):
        self.sequence += 1
        return Frame(self.sequence, b"raw", self.arm.pose + self.displaced)

    def settle(self, frame, origin=None, region=None):
        return self.capture(after=frame.sequence)

    @staticmethod
    def displacement(first, second):
        return 8 if first != second else 0

    def sharpness(self, frame):
        return next(self.scores)

    @staticmethod
    def save_upright(path, frame):
        path.write_bytes(frame.jpeg)


class QuickScanTests(unittest.TestCase):
    def run_scan(self, arm, scores, displaced=False):
        return execute(ROUTES["cruise"], arm, Camera(arm, scores, displaced), 0,
                       self.folder, lambda *args, **kwargs: None)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name) / "scan"
        sleep = patch("quick_scan.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_blur_retry_marks_direction_then_completes(self):
        arm = Arm()
        report, _ = self.run_scan(arm, [100, 5, 6, 100, 100])
        self.assertEqual(arm.commands, [
            "G4 S0", "G1 X-10 Y164 Z120 F7", "G1 X0 Y164 Z125 F7", "G1 X0 Y164 Z120 F7",
        ])
        self.assertEqual(report["missing"], ["right", "down"])
        self.assertEqual([view["direction"] for view in report["views"]], ["left", "up", "front"])
        self.assertEqual([view["quality"] for view in report["views"]], ["blurred", "clear", "clear"])
        self.assertEqual([view["capture_attempts"] for view in report["views"]], [2, 1, 1])

    def test_controller_rejection_stops_remaining_transitions(self):
        arm = Arm(reject="G1 X0 Y164 Z125 F7")
        with self.assertRaisesRegex(OSError, "controller alarm"):
            self.run_scan(arm, [100, 100])
        self.assertEqual(len(arm.commands), 3)
        report = json.loads((self.folder / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["state"], "stopped")
        self.assertEqual(report["last_verified_target_mm"], [-10, 164, 120])
        self.assertEqual([view["direction"] for view in report["views"]], ["left"])

    def test_unknown_origin_blocks_all_commands(self):
        arm = Arm()
        with self.assertRaisesRegex(ScanError, "calibrated front"):
            self.run_scan(arm, [], displaced=True)
        self.assertEqual(arm.commands, [])

    def test_stationary_frames_from_before_delayed_motion_do_not_count(self):
        camera = UsbCamera("http://unused", None, None)
        camera.capture = Mock(side_effect=[Frame(2, b"", 0), Frame(3, b"", 5), Frame(4, b"", 5)])
        camera.displacement = lambda first, second: abs(first - second)
        settled = camera.settle(Frame(1, b"", 0), origin=0)
        self.assertEqual(settled.sequence, 4)

    def test_recording_loss_stops_before_next_motion(self):
        arm = Arm()
        check = Mock(side_effect=[None, ScanError("USB recording lost")])
        with self.assertRaisesRegex(ScanError, "USB recording lost"):
            execute(ROUTES["demo"], arm, Camera(arm, [100, 100]), 0,
                    self.folder, Mock(), recording=check)
        self.assertEqual(arm.commands, ["G4 S0", "G1 X0 Y164 Z130 F7"])

    def test_biped_walk_is_held_at_low_view_and_turns_overlap_camera_moves(self):
        arm = Arm()
        biped = Mock()
        motion_starts = []
        biped.start.side_effect = lambda motion: motion_starts.append((motion["action"], arm.commands[-1]))
        report, _ = execute(ROUTES["demo"], arm, Camera(arm, [100] * 8), 0,
                            self.folder, Mock(), biped=biped)
        self.assertEqual(motion_starts, [
            ("forward", "G1 X0 Y164 Z70 F5"),
            ("turn_left", "G1 X17 Y164 Z120 F7"),
            ("turn_right", "G1 X0 Y164 Z120 F7"),
        ])
        self.assertTrue(report["biped_actions"][0]["swing_arms"])
        self.assertEqual(report["biped_actions"][0]["repeat"], 1)
        self.assertEqual(biped.wait.call_count, 3)
