"""Compatibility entry point for cv_pipeline.phase_r_background."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("cv_pipeline.phase_r_background", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("cv_pipeline.phase_r_background")
