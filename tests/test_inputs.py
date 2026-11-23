import unittest
from linear_stage_inputs import SwitchInputs, IncrementalEncoder


class InputTests(unittest.TestCase):
    def test_reserved_inputs_are_unknown(self):
        switches = SwitchInputs(active_levels=(1, 1, 1))
        self.assertEqual(switches.read(), dict(center=None, minimum=None, maximum=None))
        feedback = IncrementalEncoder().read()
        self.assertIsNone(feedback['count'])
        self.assertIsNone(feedback['position_mm'])
        self.assertEqual(feedback['source'], 'unconfigured')

    def test_switch_polarity_after_conditioning(self):
        switches = SwitchInputs(active_levels=(0, 1, 0), center=lambda: 0,
                                minimum=lambda: 0, maximum=lambda: 1)
        self.assertEqual(switches.read(), dict(center=True, minimum=False, maximum=False))

    def test_invalid_switch_levels_are_not_inactive(self):
        for value in (None, 2, '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SwitchInputs(active_levels=(1, 1, 1), center=lambda: value).read()
        with self.assertRaises(ValueError):
            SwitchInputs(active_levels=(True, 1, 1))

    def test_input_failure_propagates(self):
        def broken():
            raise OSError('input unavailable')
        with self.assertRaises(OSError):
            SwitchInputs(active_levels=(1, 1, 1), minimum=broken).read()
        with self.assertRaises(OSError):
            IncrementalEncoder(read_count=broken, decoding=4).read()

    def test_encoder_multipliers_and_sign(self):
        for decoding in (1, 2, 4):
            feedback = IncrementalEncoder(read_count=lambda: 600 * decoding,
                                          decoding=decoding, sign=-1).read()
            self.assertEqual(feedback['counts_per_rev'], 600 * decoding)
            self.assertEqual(feedback['shaft_turns_from_counter_origin'], -1)
            self.assertFalse(feedback['absolute_position_known'])
            self.assertIsNone(feedback['position_mm'])

    def test_invalid_decoder_configuration(self):
        for args in (dict(read_count=1), dict(read_count=lambda: 1),
                     dict(decoding=3), dict(decoding=True), dict(sign=0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                IncrementalEncoder(**args)
        with self.assertRaises(ValueError):
            IncrementalEncoder(read_count=lambda: True, decoding=4).read()

    def test_zero_count_is_not_missing(self):
        result = IncrementalEncoder(read_count=lambda: 0, decoding=4).read()
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['shaft_turns_from_counter_origin'], 0)
        self.assertEqual(result['source'], 'external_ab_decoder')
