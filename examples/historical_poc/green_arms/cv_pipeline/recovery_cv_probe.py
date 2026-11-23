"""Read-only feasibility probe callable within the existing connected session."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import time
from cv_pipeline.experiment_cv import CVStream
from cv_pipeline.recovery_workflow import STATE,save
from experiment_safety import SafetyError


def session_action(session,out,event,args):
    if not STATE.get('frequency_restored'):raise SafetyError('Frequency not restored')
    cv=CVStream(out,event)
    cv.start();start=time.monotonic()
    try:
        while time.monotonic()-start<12:time.sleep(.1)
        result=dict(purpose='pre-enable all-off visual feasibility, NOT reference baseline',statistics=cv.stats(start),fault=cv.failure,
                    duration_s=time.monotonic()-start,reference_pose_verified=False)
        save(out,'all_off_cv_probe.json',result)
        if cv.failure:
            STATE['vision_paused']=True
            event('safety_pause',reason=cv.failure,no_new_motion=True,stage='pre-enable read-only CV probe')
        return result
    finally:cv.close()
