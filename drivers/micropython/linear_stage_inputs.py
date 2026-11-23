"""Legacy PC import; copy linear_stage/linear_stage_inputs.py itself to MicroPython."""
import sys
from .linear_stage import linear_stage_inputs as _implementation
sys.modules[__name__] = _implementation
