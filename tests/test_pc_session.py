"""Regression checks for the persistent session; simulated UART only."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import pc_session
from test_robot_arm import FakeUART


class SessionTests(unittest.TestCase):
    def test_bad_wait_is_rejected_before_sending(self):
        for value in (-1, 61, float("nan"), float("inf"), {}, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pc_session.request(json.dumps({"command": "G1 X5", "settle": value}))

    def test_session_keeps_connection_and_logs_uncertain_completion(self):
        uart = FakeUART()
        uart.deinit = lambda: None
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            argv = ["pc_session", "--output-dir", directory]
            incoming = io.StringIO('G4 S0\n{"command":"G1 X5 F5","settle":0}\n:status\n:quit\n')
            with patch.object(sys, "argv", argv), patch.object(sys, "stdin", incoming), \
                 patch.object(pc_session, "PCUART", return_value=uart) as open_uart, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(pc_session.main(), 0)
            open_uart.assert_called_once_with("COM23")
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(uart.tx, b"G4 S0\nG1 X5 F5\n")
            replies = [r for r in records if r["event"] == "acknowledged"]
            self.assertEqual(len(replies), 2)
            self.assertTrue(all(r["physical_completion"] == "unverified" for r in replies))
            self.assertEqual(records[-1]["event"], "closed")
            self.assertEqual(len(list(Path(directory).glob('*.jsonl'))), 1)


if __name__ == "__main__":
    unittest.main()
