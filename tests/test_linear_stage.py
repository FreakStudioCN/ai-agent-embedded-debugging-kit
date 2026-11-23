"""Synthetic calibration tests; no device protocol or hardware acceptance."""
import json
from pathlib import Path
import unittest
from host_control.linear_stage import AxisCalibration, audit_profile


class LinearStageTests(unittest.TestCase):
    def axis(self, **changes):
        values = dict(full_steps_per_motor_rev=200, microsteps=16,
                      motor_revs_per_output_rev=2, mm_per_output_rev=8,
                      direction=1, minimum_mm=-10, maximum_mm=10)
        values.update(changes)
        return AxisCalibration(**values)

    def test_conversion_and_direction(self):
        for direction in (-1, 1):
            axis = self.axis(direction=direction)
            self.assertEqual(axis.steps_per_mm, 800)
            self.assertEqual(axis.displacement_to_steps(1.5), direction * 1200)
            self.assertEqual(axis.steps_to_displacement(direction * 1200), 1.5)

    def test_signed_half_pulse_rounding(self):
        axis = self.axis()
        self.assertEqual(axis.displacement_to_steps(0.000625), 1)
        self.assertEqual(axis.displacement_to_steps(-0.000625), -1)

    def test_round_trip_error_bounded(self):
        axis = self.axis()
        for mm in (-9.9981, -0.71, 0, 0.71, 9.9981):
            result = axis.steps_to_displacement(axis.displacement_to_steps(mm))
            self.assertLessEqual(abs(result - mm), 0.5 / axis.steps_per_mm)

    def test_limits_and_quantized_boundary(self):
        axis = self.axis()
        for target in (-10, 10):
            self.assertEqual(axis.check_target(target), target)
        for target in (-10.001, 10.001, float('nan'), float('inf'), True):
            with self.subTest(target=target), self.assertRaises(ValueError):
                axis.check_target(target)
        with self.assertRaisesRegex(ValueError, 'quantized'):
            self.axis(maximum_mm=0.0007).check_target(0.0007)

    def test_invalid_calibration(self):
        for changes in (dict(microsteps=0), dict(microsteps=1.5),
                        dict(full_steps_per_motor_rev=True), dict(direction=True),
                        dict(direction=0), dict(mm_per_output_rev=0),
                        dict(motor_revs_per_output_rev=float('inf')),
                        dict(minimum_mm=10), dict(maximum_mm=float('nan'))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.axis(**changes)

    def test_inventory_remains_unknown(self):
        path = Path(__file__).resolve().parents[1] / 'hardware/linear_stage/inventory.json'
        report = audit_profile(json.loads(path.read_text(encoding='utf-8')))
        self.assertIn('stage_model', report['missing'])
        self.assertIn('calibration.mm_per_output_rev', report['missing'])
        self.assertFalse(report['motion_available'])
        self.assertIsNone(report['steps_per_mm'])

    def test_complete_profile_never_claims_hardware_ready(self):
        path = Path(__file__).resolve().parents[1] / 'hardware/linear_stage/inventory.json'
        profile = json.loads(path.read_text(encoding='utf-8'))
        profile = {key: 'synthetic evidence' for key in profile}
        profile['calibration'] = vars(self.axis())
        report = audit_profile(profile)
        self.assertEqual(report['missing'], [])
        self.assertEqual(report['errors'], [])
        self.assertFalse(report['motion_available'])
        self.assertFalse(report['hardware_verified'])
        self.assertEqual(report['position_source'], 'none')
        profile['calibration'] = dict(microsteps=0, **{k:v for k,v in vars(self.axis()).items() if k != 'microsteps'})
        self.assertTrue(audit_profile(profile)['errors'])

    def test_invalid_profile(self):
        with self.assertRaises(ValueError):
            audit_profile([])
