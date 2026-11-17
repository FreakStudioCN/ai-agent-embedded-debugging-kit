"""Regression checks for epoch timing and real-event subtitles."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import experiment_recorder as recorder


class RecorderTests(unittest.TestCase):
    def test_epoch_matroska_duration(self):
        data = {"streams": [{"start_time": "1794829126.16", "width": 1280,
                            "height": 720, "codec_name": "mjpeg"}],
                "format": {"duration": "1794829134.44"}}
        with patch.object(recorder.subprocess, "run") as run:
            run.return_value.stdout = json.dumps(data)
            media = recorder.probe(Path("real-recording.mkv"))
        self.assertAlmostEqual(media["duration"], 8.28, places=5)

    def test_subtitles_only_include_current_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            records = [
                {"time": "2026-11-16T11:00:00+00:00", "event": "observation",
                 "text": "历史事件", "text_en": "Historical event"},
                {"time": "2026-11-16T11:00:11+00:00", "event": "observation",
                 "text": "蓝色键盘", "text_en": "Blue keyboard"},
                {"time": "2026-11-16T11:00:12+00:00", "event": "acknowledged",
                 "command": "G1 X0 F5", "response": "ok"}]
            (folder / "events.jsonl").write_text(
                "\n".join(json.dumps(record) for record in records), encoding="utf-8")
            start = recorder.event_time(records[0]) + 10
            output = folder / "captions.ass"
            recorder.subtitles(folder, start, 5, 1920, 1080, output)
            captions = output.read_text(encoding="utf-8-sig")
            self.assertNotIn("Historical event", captions)
            self.assertIn("Blue keyboard", captions)
            self.assertIn("Physical settling unverified", captions)
            self.assertIn("0:00:01.00", captions)

    def test_external_original_and_measured_negative_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "session"
            folder.mkdir()
            recorder.save_json(folder / "manifest.json", {
                "state": "complete", "started_utc": "2026-11-16T11:00:00+00:00"})
            source = root / "external.mp4"
            source.write_bytes(b"test fixture for copy integrity")
            args = argparse.Namespace(folder=folder, file=source, offset=-3.5,
                                      evidence="Measured marker alignment, uncertainty 0.1 s")
            with patch.object(recorder, "probe", return_value={"duration": 20}):
                recorder.import_external(args)
            saved = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            item = saved["imports"]["external"]
            self.assertEqual(item["offset_seconds"], -3.5)
            self.assertEqual(item["sha256"], recorder.digest(source))
            self.assertEqual((folder / item["file"]).read_bytes(), source.read_bytes())

    def test_invalid_story_is_rejected_before_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            recorder.save_json(folder / "manifest.json", {})
            recorder.save_json(folder / "landscape-three.json", {
                "utc_start": "2026-11-16T11:39:24.1+00:00", "duration": 272.7})
            plan = folder / "plan.json"
            recorder.save_json(plan, {"segments": [{"source_start": 30, "duration": 5}]})
            args = argparse.Namespace(folder=folder, plan=plan, layout="landscape")
            with patch.object(recorder.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    recorder.edit_story(args)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
