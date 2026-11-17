from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from phase_r_runner_v11 import PhaseRRunnerV11


class RunnerV11AdmissionTests(unittest.TestCase):
    def test_missing_new_grant_cannot_reuse_legacy_prepare_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'run';out.mkdir()
            class Session:
                def rpc(self,*a,**k):raise AssertionError('No board call before new human grant')
            with patch('phase_r_runner.ROOT',root),patch('experiment_runner.importlib.reload',side_effect=lambda module:module):
                r=PhaseRRunnerV11(Session(),out,lambda *a,**k:None,manual_view='A',manual_evidence='Old position statement')
            self.assertFalse(r.gate.authorized)
            with self.assertRaisesRegex(RuntimeError,'Fresh explicit'):r.prepare()
            self.assertFalse(r.gate.authorized)
            self.assertFalse(r.r.snapshot()['s1_authorized'])
            self.assertIsNone(r.uart)


if __name__=='__main__':unittest.main()
