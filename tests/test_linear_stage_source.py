"""Pin, source integrity and legacy imports need no sibling checkout or hardware."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LinearStageSourceTests(unittest.TestCase):
    def test_pinned_files_match_recorded_source_hashes(self):
        manifest = json.loads((ROOT / 'hardware/linear_stage/source-lock.json').read_text())
        module = ROOT / manifest['submodule_path']
        actual = subprocess.check_output(['git', '-C', str(module), 'rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual(actual, manifest['source_commit'])
        staged = subprocess.check_output(['git', 'ls-files', '--stage', manifest['submodule_path']], cwd=ROOT, text=True)
        self.assertEqual(staged.split()[:2], ['160000', actual])
        for record in manifest['files']:
            with self.subTest(path=record['target']):
                source = subprocess.check_output(['git', '-C', str(module), 'show', actual + ':' + record['source']])
                self.assertEqual((module / record['source']).read_bytes().replace(b'\r\n', b'\n'), source)
                target = (ROOT / record['target']).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(target, source)
                self.assertEqual(hashlib.sha256(target).hexdigest(), record['sha256'])

    def test_legacy_imports_use_the_submodule_implementation(self):
        for name in ['tb6600', 'linear_stage_inputs']:
            self.assertIs(importlib.import_module('drivers.micropython.' + name),
                          importlib.import_module('drivers.micropython.linear_stage.' + name))
