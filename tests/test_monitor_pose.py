"""Check latest-frame inference and source image pairing."""
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from monitor_pose import PoseWorker, CameraMotionGuard, CommandModel


class PoseWorkerTests(unittest.TestCase):
    def test_partial_command_log_is_retried_after_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device-COM8-test.jsonl'
            state = {'enabled': True, 'command_counts': {1: [307, 287, 297], 2: [307, 307, 307]}}
            record = json.dumps({'event': 'device_received', 'text': repr(state)})
            path.write_text(record[:-3], encoding='utf-8')
            model = CommandModel(directory)
            self.assertEqual(model.sample(0), {})
            with path.open('a', encoding='utf-8') as stream:
                stream.write(record[-3:] + '\n')
            self.assertEqual(model.sample(0), state['command_counts'])

    def test_camera_motion_waits_for_matching_visual_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'session-test.jsonl'
            records = [dict(time='2026-11-17T00:00:01Z',event='sending',command='G1 Z125 F5'),
                       dict(time='2026-11-17T00:00:02Z',event='acknowledged',command='G1 Z125 F5')]
            path.write_text(''.join(json.dumps(row)+'\n' for row in records))
            guard = CameraMotionGuard(directory)
            self.assertTrue(guard.update()[0])
            with path.open('a') as stream:
                stream.write(json.dumps(dict(time='2026-11-17T00:00:03Z',event='motion_verified',command='G1 Z125 F5',frame='real.jpg'))+'\n')
            self.assertFalse(guard.update()[0])

    def test_slow_inference_skips_old_frames_and_logs_source_sequence(self):
        try:
            import cv2
            import numpy
        except ImportError:
            self.skipTest('OpenCV vision dependencies are optional')
        entered, release, processed_latest = threading.Event(), threading.Event(), threading.Event()
        calls = []

        class Video:
            sequence = 1

            def latest(self):
                value = self.sequence
                return Image.new('RGB', (8, 8), (value, 0, 0)), value, time.monotonic(), 10, ''

        def detect(frame):
            calls.append(int(frame[0, 0, 2]))
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            else:
                processed_latest.set()
            return []

        engine = SimpleNamespace(detect_skeletons=detect, draw_skeletons=lambda frame, arms: frame)
        video = Video()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'poses.jsonl'
            worker = PoseWorker(video, directory, path)
            with patch('monitor_pose.importlib.import_module', return_value=engine):
                worker.thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    video.sequence = 2
                    video.sequence = 3
                    release.set()
                    self.assertTrue(processed_latest.wait(2))
                    deadline = time.monotonic()+2
                    while worker.latest()[1] != 3 and time.monotonic() < deadline:
                        time.sleep(.01)
                    image, sequence, _, stats = worker.latest()
                    self.assertEqual(sequence, 3)
                    self.assertEqual(image.getpixel((0, 0))[0], sequence)
                    self.assertEqual(stats['arms'], 0)
                    self.assertEqual(calls, [1, 3])
                finally:
                    release.set()
                    worker.stop.set()
                    worker.thread.join(3)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([item['source_sequence'] for item in records], [1, 3])


if __name__ == '__main__':
    unittest.main()
