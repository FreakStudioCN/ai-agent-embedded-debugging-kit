"""Timing-plan checks, not physical speed or waveform measurements."""
import importlib.util
from pathlib import Path
import unittest


class RPMProfileTests(unittest.TestCase):
    def test_count_ramp_and_no_commanded_overspeed(self):
        path = Path(__file__).resolve().parents[1] / 'firmware/linear_stage/rpm_300_test.py'
        spec = importlib.util.spec_from_file_location('rpm_profile', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        waveform = module.make_profile()
        self.assertEqual(len(waveform), 6400)
        self.assertTrue(all(waveform[i] == 10 for i in range(0, 6400, 2)))
        periods = tuple(waveform[i] + waveform[i+1] for i in range(0, 6400, 2))
        self.assertEqual(min(periods), 63)
        self.assertEqual(max(periods), 625)
        self.assertEqual(periods[:400], periods[-400:][::-1])
        self.assertTrue(all(a >= b for a, b in zip(periods[:399], periods[1:400])))
        self.assertLessEqual(1000000 / min(periods) * 60 / 3200, 300)
        self.assertEqual(sum(waveform), 426798)

    def test_extended_count_and_invalid_bounds(self):
        path = Path(__file__).resolve().parents[1] / 'firmware/linear_stage/rpm_300_test.py'
        spec = importlib.util.spec_from_file_location('rpm_profile_bounds', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        waveform = module.make_profile(32000)
        self.assertEqual(len(waveform), 64000)
        self.assertEqual(sum(waveform), 2241198)
        self.assertEqual(len(waveform) // 64, 1000)
        for pulses in (True, 799, 32001, 32000.0):
            with self.subTest(pulses=pulses), self.assertRaises(ValueError):
                module.make_profile(pulses)
