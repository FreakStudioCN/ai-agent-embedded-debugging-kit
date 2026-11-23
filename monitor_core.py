"""Compatibility entry for visual_observation.core."""
import sys
from pathlib import Path
_root = next(p for p in Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_root) not in sys.path: sys.path.insert(0, str(_root))
if __name__ == "__main__":
    import runpy
    runpy.run_module("visual_observation.core", run_name="__main__")
else:
    import importlib
    sys.modules[__name__] = importlib.import_module("visual_observation.core")
