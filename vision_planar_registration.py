"""Compatibility entry point for cv_pipeline.vision_planar_registration."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("cv_pipeline.vision_planar_registration", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("cv_pipeline.vision_planar_registration")
