"""Offline Phase R validation: real video replay plus labelled fault simulation.

No serial imports or hardware operations. Fixture controller/reference inputs
are explicitly simulated and never counted as physical calibration success.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import sys
import time
import uuid
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cv_pipeline.phase_r import PhaseR,BackgroundTracker,ControllerEvidence
from experiment_safety import ExperimentGate,VIEWS,SafetyError


def main():
    run='phase_r_offline_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    out=ROOT/'.runtime'/run;out.mkdir()
    def emit(event,**details):
        with (out/'experiment_events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(schema_version='1.0',run_id=run,timestamp_utc=datetime.now(timezone.utc).isoformat(),monotonic_ms=time.monotonic_ns()/1e6,
                event=event,motion_id=details.pop('motion_id',None),mode='OFFLINE_NO_HARDWARE',details=details),ensure_ascii=False)+'\n')
    source=ROOT/'.runtime/experiment_20261117T075459_750e71b2/media/recording/vision.mkv'
    cap=cv2.VideoCapture(str(source));ok,first=cap.read()
    if not ok:raise RuntimeError('Cannot decode source video')
    frame=cv2.rotate(first,cv2.ROTATE_180)
    w=dict(window_ms=11000,valid_ratio=1,confidence_median=.95,rms_px_median=.5,angle_std_deg=.1,angle_drift_deg_per_s=0)
    baseline=dict(valid=True,windows=[w.copy(),w.copy()],std_limit_deg=1.5,simulation=True)
    def fixture(name):
        gate=ExperimentGate(name);gate.authorize(name,'SIMULATED TEST PERMIT, NOT HUMAN LIVE AUTHORIZATION')
        r=PhaseR(out/(name+'-state.json'),emit,run,gate.pause);gate.recovery_guard=r
        r.confirm_manual_reference('A','SIMULATED reference fixture for algorithm verification only',frame,baseline,ControllerEvidence(True,True,'IDLE',VIEWS['A']),'SIMULATED fixture')
        return r,gate
    r,gate=fixture('recorded-video')
    measurements=[];i=0;first_pause=None;last_pts=0;pts_gaps=[]
    while True:
        ok,f=cap.read()
        if not ok:break
        i+=1;pts=cap.get(cv2.CAP_PROP_POS_MSEC)
        if pts-last_pts>1000:pts_gaps.append(dict(previous_ms=last_pts,current_ms=pts,gap_ms=pts-last_pts))
        last_pts=pts
        if i%5:continue
        image=cv2.rotate(f,cv2.ROTATE_180);metric=r.background.compare(image)
        # Counterfactual idle/no-plan expectation tests whether recorded scene
        # movement would be caught if it were NOT an authorized transaction.
        r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A'],source='REPLAY counterfactual IDLE/no registered motion'),metric)
        row=dict(frame=i,source_pts_ms=pts,background=metric,state=r.snapshot()['state'])
        measurements.append(row)
        if first_pause is None and row['state']=='PAUSED':first_pause=row
    cap.release()
    if not first_pause:raise AssertionError('Recorded observer/background motion was not detected')
    # The original run separately proves a5.10s camera outage; do not reconstruct
    # missing frames or call an automatic recovery move in the replay.
    original_gap=json.loads((ROOT/'.runtime/experiment_20261117T075459_750e71b2/stream_gap_diagnosis.json').read_text(encoding='utf-8'))
    r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A']),dict(valid=True,drift=False),False,'recorded_USB_gap')
    assert r.snapshot()['state']=='LOCKOUT'
    recovered=PhaseR(out/'recorded-video-state.json',emit,run+'-restart')
    assert recovered.snapshot()['state']=='LOCKOUT'
    cases=[]
    for name,success_on in [('first_attempt_success',1),('second_attempt_success',2),('both_attempts_fail',None)]:
        x,g=fixture(name);old=x.snapshot()['calibration_version']
        steps=x.begin_verified_move(g,'B-small','SIMULATED-legal-view-move')
        x.segment_started('sim-step',VIEWS['A'],VIEWS['B-small'])
        x.observe(ControllerEvidence(True,True,'MOVING',VIEWS['A'],motion_id='sim-step'),dict(valid=True,drift=True))
        assert x.snapshot()['state']=='MOVING'
        x.segment_arrived(ControllerEvidence(True,True,'WAIT_SETTLE',VIEWS['B-small']),True)
        for attempt in range(1,3):
            success=x.attempt_recalibration(ControllerEvidence(True,True,'IDLE',VIEWS['B-small']),True,frame,
                lambda attempt=attempt:baseline if attempt==success_on else dict(valid=False,simulation=True))
            if success:break
        expected='READY' if success_on else 'LOCKOUT';assert x.snapshot()['state']==expected
        if success_on:
            assert x.snapshot()['calibration_version']!=old
            try:
                x.assert_comparable(dict(calibration_version=old,camera_pose_id='A',measurement_mode='projected'),dict(calibration_version=x.snapshot()['calibration_version'],camera_pose_id='B-small',measurement_mode='projected'))
            except SafetyError:pass
            else:raise AssertionError('Cross-version comparison was accepted')
        cases.append(dict(name=name,state=expected,attempts=x.snapshot()['attempts'],simulation=True))
    bg=BackgroundTracker();bg.anchor(frame)
    moved=cv2.warpAffine(frame,np.float32([[1,0,14],[0,1,0]]),(frame.shape[1],frame.shape[0]))
    drift=bg.compare(moved);assert drift['valid'] and drift['drift']
    result=dict(schema_version='1.0',run_id=run,mode='OFFLINE_NO_HARDWARE',status='PASS',source=str(source),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sampled_frames=len(measurements),first_unexpected_motion_pause=first_pause,
        replay_state=recovered.snapshot()['state'],source_pts_gaps=pts_gaps,original_gap_evidence=original_gap,
        simulated_cases=cases,simulated_affine_drift=drift,real_motor_commands=0,
        limitations='Replay IDLE is a counterfactual detector test, not a claim that recorded G28 was uncommanded. Simulated legal arrivals/recalibrations are not physical validation.')
    (out/'replay_measurements.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in measurements),encoding='utf-8')
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(out),status='PASS',cases=cases,first_pause_pts_ms=first_pause['source_pts_ms'],motor_commands=0),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
