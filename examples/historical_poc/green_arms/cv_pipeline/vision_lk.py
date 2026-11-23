"""Versioned CV adapter retaining validated subpixel LK feature observations.

The upstream forward/back LK, blob-presence checks, feature identities, PnP
selection, geometry, confidence definition and motion priors are unchanged.
Only integer peak snapping is removed after optical flow; no temporal smoothing
is added. This reduces pixel quantization without inventing a servo angle.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import hashlib
import importlib
import inspect
import types


def tracker_class():
    original=importlib.import_module('mr_robot_desktop.fused_pose')
    source=inspect.getsource(original);needle='observed[index] = x+ix-6,y+iy-6'
    if source.count(needle)!=1:raise RuntimeError('Upstream LK edit point changed; review required')
    module=types.ModuleType('mr_robot_desktop._fused_pose_lk_v11');module.__package__='mr_robot_desktop'
    exec(compile(source.replace(needle,'observed[index] = point'),original.__file__+'::lk_v11','exec'),module.__dict__)
    module.FusedTracker.upstream_source_sha256=hashlib.sha256(source.encode()).hexdigest()
    module.FusedTracker.measurement_version='cv-lk-subpixel-v11'
    return module.FusedTracker
