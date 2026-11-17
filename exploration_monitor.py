"""Compatibility entry point for visual_observation.monitor."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("visual_observation.monitor", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("visual_observation.monitor")
