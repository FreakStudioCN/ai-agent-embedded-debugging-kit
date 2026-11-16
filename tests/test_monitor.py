"""Regression tests for real-event state and streaming input; no hardware."""
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor_core import EventTail, MonitorState, jpeg_frames


class MonitorTests(unittest.TestCase):
    def test_ack_is_separate_from_visual_completion(self):
        state = MonitorState()
        state.apply({"event": "sending", "command": "G1X5Y179F5"})
        self.assertEqual(state.target, {"X": 5, "Y": 179, "Z": None})
        state.apply({"event": "acknowledged", "command": "G1X5Y179F5"})
        self.assertIn("待确认", state.motion)
        state.apply({"event": "motion_verified", "command": "G1 X0", "frame": "old.jpg"})
        self.assertIn("待确认", state.motion)
        state.apply({"event": "motion_verified", "command": "G1X5Y179F5", "frame": "fresh.jpg", "text": "背景稳定", "text_en": "Background settled"})
        self.assertEqual(state.motion, "Agent 已视觉确认停稳")
        state.apply({"event": "sending", "command": "G1 Z125"})
        self.assertIn("待确认", state.motion)

    def test_stream_handles_split_jpeg_markers(self):
        class Chunked(BytesIO):
            def read1(self, size):
                return self.read(3)

        data = Chunked(b"--boundary\r\n\xff\xd8frame1\xff\xd9\r\n--boundary\xff\xd8frame2\xff\xd9")
        self.assertEqual(list(jpeg_frames(data)), [b"\xff\xd8frame1\xff\xd9", b"\xff\xd8frame2\xff\xd9"])

    def test_tail_preserves_incomplete_utf8_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent-events.jsonl"
            encoded = (json.dumps({"event": "observation", "text": "真实画面"}, ensure_ascii=False) + "\n").encode("utf8")
            path.write_bytes(encoded[:-3])
            tail = EventTail(directory)
            self.assertEqual(tail.read(), [])
            with path.open("ab") as stream:
                stream.write(encoded[-3:])
            original = tail.read()[0]
            self.assertEqual(original["text"], "真实画面")
            self.assertEqual(tail.read(), [])
            (Path(directory) / "export.jsonl").write_text(json.dumps(original) + "\n", encoding="utf8")
            self.assertEqual(tail.read(), [])
            path.write_text('{"event":"note"}\n', encoding="utf8")
            self.assertEqual(tail.read()[0]["event"], "note")


if __name__ == "__main__":
    unittest.main()
