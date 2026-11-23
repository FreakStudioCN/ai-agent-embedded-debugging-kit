"""Legacy PC import; copy linear_stage/tb6600.py itself to MicroPython."""
import sys
from .linear_stage import tb6600 as _implementation
sys.modules[__name__] = _implementation
