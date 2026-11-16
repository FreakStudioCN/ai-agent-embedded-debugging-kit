"""Compatibility entry point for the canonical implementation in code/."""
import importlib.util
from pathlib import Path
import runpy
import sys

_path = Path(__file__).resolve().parent / "code" / "pc_control.py"
if __name__ == "__main__":
    runpy.run_path(str(_path), run_name="__main__")
else:
    _spec = importlib.util.spec_from_file_location(__name__, _path)
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[__name__] = _module
    _spec.loader.exec_module(_module)
