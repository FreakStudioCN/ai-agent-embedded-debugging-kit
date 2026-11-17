import unittest
from unittest.mock import Mock
from experiment_runner import validate_cv_adapter,Runner
from experiment_safety import SafetyError


class IntegrationAdmissionTests(unittest.TestCase):
    def test_stale_cv_api_is_rejected_before_enable_or_any_serial_request(self):
        runner=Runner.__new__(Runner)
        runner.cv=Mock(spec=['start','stats','close'])
        runner.s=Mock()
        with self.assertRaisesRegex(SafetyError,'missing settled'):
            runner.start()
        runner.s.rpc.assert_not_called()

    def test_current_cv_api_contains_stationary_window_interface(self):
        from experiment_cv import CVStream
        for method in ('start','settled','stats','close'):
            self.assertTrue(callable(getattr(CVStream,method,None)))


if __name__=='__main__':unittest.main()
