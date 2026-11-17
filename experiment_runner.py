"""Compatibility entry point for cv_pipeline.experiment_runner."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("cv_pipeline.experiment_runner", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("cv_pipeline.experiment_runner")
