from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from operator_homing import OperatorHomingRunner


class ExplicitHomingTests(unittest.TestCase):
    def test_homing_cannot_be_called_by_fault_or_without_explicit_user_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'run';out.mkdir()
            class Session:
                def rpc(self,*a,**k):raise AssertionError('No hardware call authorized')
            with patch('phase_r_runner.ROOT',root),patch('experiment_runner.importlib.reload',side_effect=lambda module:module):
                r=OperatorHomingRunner(Session(),out,lambda *a,**k:None)
            with self.assertRaisesRegex(RuntimeError,'Explicit current-session'):r.prepare_homing()
            with self.assertRaisesRegex(RuntimeError,'No admitted'):r.operator_home()
            with self.assertRaisesRegex(RuntimeError,'never issues automatic'):r.observer_command('G28')
            self.assertIsNone(r.uart)


if __name__=='__main__':unittest.main()
