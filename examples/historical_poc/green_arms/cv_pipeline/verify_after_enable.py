"""Fault follow-up: read-only register/state and camera verification, no moves."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import json
import time
from cv_pipeline.experiment_cv import CVStream
from cv_pipeline.recovery_workflow import registers,snapshots,save
from experiment_safety import REFERENCE,SafeExecutor,SafetyError


def session_action(session,out,event,args):
    uid=session.rpc("__import__('machine').unique_id().hex()")
    before=registers(session);state=session.rpc('d.status()')
    SafeExecutor.check_hardware(uid,before,state)
    event('preflight',purpose='Read-only verification after host CV API error',uid=uid,pca=before,state=state,motion_allowed=False)
    cv=CVStream(out,event);cv.camera_pose_id='initial_reference_unhomed';cv.start()
    start=time.monotonic()
    try:
        while time.monotonic()-start<12:time.sleep(.1)
        stats=cv.stats(start)
        stationary=all(w and w['stationary'] for cams in stats.values() for w in cams.values())
        frames=snapshots(out,'post-enable-verification',event)
        after=registers(session);final_state=session.rpc('d.status()')
        if before!=after:raise SafetyError('Registers changed during read-only verification')
        result=dict(uid=uid,pca=after,state=final_state,statistics=stats,all_camera_windows_stationary=stationary,cv_fault=cv.failure,
                    frames=frames,outputs_unchanged=True,motion_commands_sent=0,purpose='diagnostic stationary reference data; experiment paused',
                    original_recovery_run='embodied_20261117T073535_da6de203')
        save(out,'reference_verification.json',result)
        event('phase_result',phase='reference_recovery_verification',stationary=stationary,statistics=stats,formal_experiment_resumed=False)
        return result
    finally:cv.close()
