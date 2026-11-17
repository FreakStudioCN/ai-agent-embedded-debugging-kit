import unittest
from monitor_core import event_time


class V11EventTimestampTests(unittest.TestCase):
    def test_recorder_accepts_protocol_timestamp_without_changing_legacy_order(self):
        stamp='2026-11-17T09:00:00+00:00'
        self.assertEqual(event_time({'timestamp_utc':stamp}),event_time({'time':stamp}))
        self.assertGreater(event_time({'timestamp_utc':stamp}),0)


if __name__=='__main__':unittest.main()
