"""Compatibility entry for host_control.quick_scan."""
import sys
from pathlib import Path
_root = next(p for p in Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_root) not in sys.path: sys.path.insert(0, str(_root))
if __name__ == "__main__":
    import runpy
    runpy.run_module("host_control.quick_scan", run_name="__main__")
else:
    import importlib
    sys.modules[__name__] = importlib.import_module("host_control.quick_scan")
