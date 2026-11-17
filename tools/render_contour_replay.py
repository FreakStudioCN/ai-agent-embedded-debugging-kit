"""Compatibility entry point for cv_pipeline.tools.render_contour_replay."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib
import runpy

if __name__ == "__main__":
    runpy.run_module("cv_pipeline.tools.render_contour_replay", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("cv_pipeline.tools.render_contour_replay")
