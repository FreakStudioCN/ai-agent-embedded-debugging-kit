"""Offline TB6600 behavior tests with injected pins and RMT."""
import unittest
from drivers.micropython.tb6600 import TB6600


class Pin:
    def __init__(self):
        self.values = []

    def value(self, value):
        self.values.append(value)


class RMT:
    def __init__(self):
        self.done = True
        self.sent = []
        self.closed = False

    def write_pulses(self, durations, level):
        self.sent.append((durations, level))
        self.done = False

    def wait_done(self, *, timeout):
        return self.done

    def deinit(self):
        self.closed = True


class TB6600Tests(unittest.TestCase):
    def make(self, budget=8, level=1):
        self.ena, self.direction, self.pulse = Pin(), Pin(), Pin()
        self.rmt = RMT()
        self.stage = TB6600(self.ena, self.direction, self.pulse, self.rmt,
                            lambda us: None, enable_level=level, pulse_budget=budget)
        return self.stage

    def test_init_and_accept_do_not_send_pulses(self):
        stage = self.make()
        self.assertEqual(self.ena.values, [0])
        stage.start(3, 1)
        self.assertEqual(stage.status()['state'], 'accepted')
        self.assertEqual(self.rmt.sent, [])

    def test_finite_completion_not_physical_position(self):
        stage = self.make()
        stage.start(3, 0)
        for _ in range(4):
            stage.update()
            self.rmt.done = True
        status = stage.status()
        self.assertEqual(status['state'], 'completed')
        self.assertEqual(status['completed_pulses'], 3)
        self.assertEqual(len(self.rmt.sent), 3)
        self.assertEqual(self.rmt.sent[0], ((10, 9990), 1))
        self.assertIsNone(status['physical_motion_complete'])
        self.assertIsNone(status['position_mm'])

    def test_stop_waits_one_pulse_and_preserves_enable(self):
        stage = self.make()
        stage.start(8, 1)
        stage.update()
        self.assertEqual(stage.stop()['state'], 'stopping')
        for _ in range(5):
            stage.update()
        self.assertEqual(len(self.rmt.sent), 1)
        self.rmt.done = True
        self.assertEqual(stage.update()['state'], 'stopped')
        self.assertEqual(self.ena.values[-1], 1)

    def test_stop_before_first_pulse(self):
        stage = self.make()
        stage.start(4, 0)
        self.assertEqual(stage.stop()['state'], 'stopped')
        self.assertEqual(self.rmt.sent, [])

    def test_invalid_arguments_no_enable(self):
        stage = self.make()
        for args in ((0, 1, 100), (9, 1, 100), (True, 1, 100),
                     (1, 2, 100), (1, 1, 3201), (1, 1, float('nan'))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                stage.start(*args)
        self.assertEqual(self.ena.values, [0])
        self.assertEqual(self.rmt.sent, [])

    def test_cumulative_budget_and_busy_rejection(self):
        stage = self.make(budget=1)
        stage.start(1, 0)
        with self.assertRaises(RuntimeError):
            stage.start(1, 0)
        stage.update()
        self.rmt.done = True
        stage.update()
        with self.assertRaises(ValueError):
            stage.start(1, 1)

    def test_failure_never_retries_or_claims_completed(self):
        stage = self.make()
        def fail(*args):
            raise OSError('RMT failed')
        self.rmt.write_pulses = fail
        stage.start(2, 0)
        with self.assertRaises(OSError):
            stage.update()
        self.assertEqual(stage.status()['state'], 'fault')
        self.assertTrue(stage.status()['pending_pulse'])
        with self.assertRaises(RuntimeError):
            stage.start(1, 0)

    def test_deinit_rejects_pending_then_drops_torque(self):
        stage = self.make(level=0)
        stage.start(2, 1)
        stage.update()
        with self.assertRaises(RuntimeError):
            stage.deinit()
        stage.stop()
        self.rmt.done = True
        stage.update()
        stage.deinit()
        stage.deinit()
        self.assertEqual(self.ena.values[-1], 1)
        self.assertTrue(self.rmt.closed)

    def test_confirmed_active_low_enable_and_stop(self):
        stage = self.make(level=0)
        self.assertEqual(self.ena.values, [1])
        stage.start(2, 1)
        self.assertEqual(self.ena.values[-1], 0)
        stage.update()
        stage.stop()
        self.rmt.done = True
        self.assertEqual(stage.update()['state'], 'stopped')
        self.assertEqual(self.ena.values[-1], 0)
        stage.deinit()
        self.assertEqual(self.ena.values[-1], 1)

    def test_board_enable_polarity_default(self):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / 'firmware/linear_stage/bringup.py'
        spec = importlib.util.spec_from_file_location('stage_bringup', path)
        board = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(board)
        self.assertEqual(board.ENABLE_LEVEL, 0)
        self.assertEqual(board.create.__kwdefaults__['enable_level'], 0)

    def test_authorized_longer_move_and_session_limits(self):
        stage = self.make(budget=12800)
        with self.assertRaises(ValueError):
            stage.start(6401, 0)
        for direction in (0, 1):
            stage.start(6400, direction)
            for _ in range(6401):
                stage.update()
                self.rmt.done = True
            self.assertEqual(stage.status()['state'], 'completed')
        self.assertEqual(len(self.rmt.sent), 12800)
        with self.assertRaises(ValueError):
            stage.start(1, 0)
        with self.assertRaises(ValueError):
            self.make(budget=12801)

    def test_stop_large_request_cancels_remaining(self):
        stage = self.make(budget=12800, level=0)
        stage.start(6400, 0)
        stage.update()
        stage.stop()
        self.rmt.done = True
        for _ in range(100):
            stage.update()
        self.assertEqual(len(self.rmt.sent), 1)
        self.assertEqual(stage.status()['state'], 'stopped')

    def test_1600hz_batches_exact_count_and_tail(self):
        stage = self.make(budget=12800)
        stage.start(65, 0, 1600)
        for _ in range(4):
            stage.update()
            self.rmt.done = True
        self.assertEqual(stage.status()['state'], 'completed')
        self.assertEqual(stage.status()['completed_pulses'], 65)
        self.assertEqual([len(item[0]) // 2 for item in self.rmt.sent], [32, 32, 1])
        self.assertEqual(self.rmt.sent[0][0], (10, 615) * 32)

    def test_1600hz_stop_finishes_only_current_batch(self):
        stage = self.make(budget=12800, level=0)
        stage.start(6400, 1, 1600)
        stage.update()
        self.assertEqual(stage.stop()['state'], 'stopping')
        self.rmt.done = True
        for _ in range(100):
            stage.update()
        self.assertEqual(stage.status()['state'], 'stopped')
        self.assertEqual(stage.status()['completed_pulses'], 32)
        self.assertEqual(len(self.rmt.sent), 1)
        self.assertEqual(self.ena.values[-1], 0)

    def test_2400hz_rounded_period_and_exact_batch_count(self):
        stage = self.make(budget=12800)
        stage.start(33, 0, 2400)
        for _ in range(3):
            stage.update()
            self.rmt.done = True
        self.assertEqual(stage.status()['completed_pulses'], 33)
        self.assertEqual(self.rmt.sent[0][0], (10, 407) * 32)
        self.assertEqual(self.rmt.sent[1][0], (10, 407))
        self.assertEqual(stage.status()['state'], 'completed')

    def test_2400hz_stop_does_not_submit_second_batch(self):
        stage = self.make(budget=12800, level=0)
        stage.start(6400, 1, 2400)
        stage.update()
        stage.stop()
        self.rmt.done = True
        for _ in range(10):
            stage.update()
        self.assertEqual(stage.status()['completed_pulses'], 32)
        self.assertEqual(stage.status()['state'], 'stopped')
        self.assertEqual(len(self.rmt.sent), 1)

    def test_3200hz_period_tail_and_stop_boundary(self):
        stage = self.make(budget=12800, level=0)
        stage.start(33, 0, 3200)
        for _ in range(3):
            stage.update()
            self.rmt.done = True
        self.assertEqual(stage.status()['completed_pulses'], 33)
        self.assertEqual(self.rmt.sent[0][0], (10, 303) * 32)
        self.assertEqual(self.rmt.sent[1][0], (10, 303))
        self.assertEqual(stage.status()['state'], 'completed')
        stage.start(6400, 1, 3200)
        stage.update()
        stage.stop()
        self.rmt.done = True
        for _ in range(100):
            stage.update()
        self.assertEqual(stage.status()['state'], 'stopped')
        self.assertEqual(stage.status()['completed_pulses'], 65)
        self.assertEqual(len(self.rmt.sent), 3)
        self.assertEqual(self.ena.values[-1], 0)
