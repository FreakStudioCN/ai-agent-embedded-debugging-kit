"""In-tree ownership, historical provenance and compatible imports; no device IO."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LinearStageSourceTests(unittest.TestCase):
    def test_sources_are_regular_kit_files_not_a_submodule(self):
        self.assertFalse((ROOT / '.gitmodules').exists())
        self.assertFalse((ROOT / 'drivers/micropython/linear_stage/.git').exists())
        for name in ['tb6600.py', 'linear_stage_inputs.py']:
            path = 'drivers/micropython/linear_stage/' + name
            self.assertTrue((ROOT / path).is_file())
            staged = subprocess.check_output(['git', 'ls-files', '--stage', path], cwd=ROOT, text=True)
            self.assertTrue(staged.startswith('100644 '), staged)
        self.assertFalse((ROOT / 'tools/sync_linear_stage.py').exists())
        self.assertFalse((ROOT / 'hardware/linear_stage/source-lock.json').exists())

    def test_historical_provenance_is_kept_without_locking_current_sources(self):
        manifest = json.loads((ROOT / 'hardware/linear_stage/provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['source_commit']), 40)
        for path, digest in manifest['archive_file_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest(), digest)
        self.assertIn('MIT', (ROOT / 'drivers/micropython/linear_stage/LICENSE').read_text())

    def test_legacy_imports_use_the_in_tree_implementation(self):
        for name in ['tb6600', 'linear_stage_inputs']:
            self.assertIs(importlib.import_module('drivers.micropython.' + name),
                          importlib.import_module('drivers.micropython.linear_stage.' + name))
