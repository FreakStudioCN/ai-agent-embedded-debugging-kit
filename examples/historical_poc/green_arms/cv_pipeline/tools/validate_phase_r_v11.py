"""Historical-video replay and labelled faults; zero hardware transports.

Run after the dedicated regression tests. Simulation outputs live under offline/;
they cannot replace the root real LOCKOUT or a physical experiment baseline.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import sys
import time
import cv2
import numpy as np
ROOT=_WORKSPACE_ROOT;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent/'Mr-Robot-Arm'))
from cv_pipeline.phase_r_v11 import PhaseRV11
from cv_pipeline.phase_r import ControllerEvidence
from experiment_safety import ExperimentGate,VIEWS,SafetyError,REFERENCE
from cv_pipeline.experiment_cv import projected
from cv_pipeline.vision_subpixel import tracker_class
from mr_robot_desktop.fused_pose import FusedTracker


def main():
    run=Path(sys.argv[1]);out=run/'offline';out.mkdir(exist_ok=True);events=[]
    def emit(event,**details):
        row=dict(schema_version='1.1',run_id=run.name,mode='OFFLINE_SIMULATED_CONTROLLER',timestamp_utc=datetime.now(timezone.utc).isoformat(),
            monotonic_ms=time.monotonic_ns()/1e6,event=event,motion_id=details.get('motion_id'),details=details)
        events.append(row)
        with (out/'experiment_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    source=ROOT/'.runtime/experiment_20261117T075459_750e71b2/media/recording/vision.mkv'
    capture=cv2.VideoCapture(str(source));ok,frame=capture.read()
    if not ok:raise RuntimeError('Historical recording unreadable')
    frame=cv2.rotate(frame,cv2.ROTATE_180)
    w=dict(window_ms=11000,valid_ratio=1.,confidence_median=.95,rms_px_median=.5,angle_std_deg=.1,angle_drift_deg_per_s=0)
    base=dict(valid=True,windows=[w.copy(),w.copy()],std_limit_deg=1.,simulation=True)
    def fixture(name):
        r=PhaseRV11(out/(name+'.json'),emit,'OFFLINE-'+name,recovery_dir=out/name/'recovery')
        r.authorize_manual_recovery('SIMULATED GRANT','SIMULATED FIX','SIMULATED CLEAR','SIMULATED A')
        r.d['background_reference']=dict(window_s=3.1,simulation=True)
        r.confirm_manual_reference('A','SIMULATED',frame,base,ControllerEvidence(True,True,'IDLE',VIEWS['A']),'SIMULATED')
        return r
    r=fixture('historical-counterfactual-idle');replay=[];index=0;first_pause=None
    fps=capture.get(cv2.CAP_PROP_FPS)
    while True:
        ok,f=capture.read()
        if not ok:break
        index+=1
        if index%max(1,int(fps/2)):continue
        pts=capture.get(cv2.CAP_PROP_POS_MSEC);metric=r.background.compare(cv2.rotate(f,cv2.ROTATE_180))
        state=r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A'],source='SIMULATED counterfactual idle; recorded movement may have been authorized'),metric,now=pts/1000)
        replay.append(dict(pts_ms=pts,metric=metric,state=state))
        if state in ('PAUSED','RECOVERY_LOCKOUT') and first_pause is None:first_pause=pts
    capture.release()
    if first_pause is None:raise AssertionError('Historical scene change not detected')
    (out/'replay_background.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in replay),encoding='utf-8')
    cases=[]
    def case(name,operation,expected):
        x=fixture(name);operation(x);actual=x.snapshot()['state']
        if actual!=expected:raise AssertionError((name,actual,expected))
        cases.append(dict(name=name,expected=expected,actual=actual,passed=True,simulation=True,motor_commands=0))
        return x
    controller=ControllerEvidence(True,True,'IDLE',VIEWS['A'])
    case('untrusted-controller',lambda x:x.observe(ControllerEvidence(True,False,'UNKNOWN'),dict(valid=True)),'PAUSED')
    case('USB-drop-reconnect',lambda x:(x.observe(controller,{},False),x.observe(controller,dict(valid=True,drift_px=0),True)),'PAUSED')
    case('low-texture-occlusion',lambda x:x.observe(controller,dict(valid=False,reason='too_few_features')),'PAUSED')
    case('RANSAC-mismatch',lambda x:x.observe(controller,dict(valid=False,reason='RANSAC_failed')),'PAUSED')
    def drift(x):
        transformed=cv2.warpAffine(frame,np.float32([[1,0,16],[0,1,0]]),(1280,720))
        metric=x.background.compare(transformed)
        if not metric['valid']:raise AssertionError('Injected translation not trackable')
        for t in (0,.51,1.01):x.observe(controller,metric,now=t)
    case('uncommanded-drift',drift,'PAUSED')
    def legal(x,fail=False):
        gate=ExperimentGate('SIM');gate.authorize('SIM','SIMULATED');gate.recovery_guard=x
        x.begin_verified_move(gate,'B-small','legal');x.segment_started('seg',VIEWS['A'],VIEWS['B-small'])
        x.observe(ControllerEvidence(True,True,'MOVING',VIEWS['A'],motion_id='seg'),dict(valid=False,reason='legal motion blur'))
        x.segment_arrived(ControllerEvidence(True,True,'IDLE',VIEWS['B-small']),True)
        c=ControllerEvidence(True,True,'IDLE',VIEWS['B-small'])
        for i in range(2 if fail else 1):x.attempt_recalibration(c,True,frame,lambda:dict(valid=False) if fail else base,lambda deadline:dict(window_s=3.1,simulation=True))
    legal_r=case('legal-view-rebase',legal,'NORMAL')
    try:legal_r.assert_comparable(dict(calibration_version='OLD',camera_pose_id='A',measurement_mode='projected'))
    except SafetyError:cases.append(dict(name='cross-version-reject',passed=True,simulation=True,motor_commands=0))
    else:raise AssertionError('Accepted old version')
    locked=case('two-failed-rebases',lambda x:legal(x,True),'RECOVERY_LOCKOUT')
    again=PhaseRV11(locked.path,emit,'OFFLINE-restart',recovery_dir=out/'restart'/'recovery')
    assert again.snapshot()['state']=='RECOVERY_LOCKOUT' and again.d['attempts']==2
    cases.append(dict(name='restart-retains-lockout-budget',passed=True,simulation=True,motor_commands=0))
    case('rolling-three-repeat-faults',lambda x:[x.report_repeated_fault('USB recurrence') for _ in range(3)],'RECOVERY_LOCKOUT')
    # Genuine background frames with synthetic moving green/person rectangles.
    x=fixture('green-and-person-exclusion');box=(600,100,160,500);x.background.anchor(frame,[box])
    changed=frame.copy();cv2.rectangle(changed,(620,150),(740,500),(0,255,0),-1)
    metric=x.background.compare(changed,[box]);x.observe(controller,metric,now=1)
    assert metric['valid'] and metric['drift_px']<1 and x.snapshot()['state']=='NORMAL'
    cases.append(dict(name='green-motion-and-person-mask',passed=True,simulation=True,motor_commands=0,
        limitation='Labelled external person box verifies exclusion path; not a measured human-detector recall benchmark'))
    # Read-only algorithm comparison on newly recorded static clip, no threshold changes.
    video=run/'media/recording/vision.mkv';comparisons={};raw=[]
    for cls,name in [(FusedTracker,'original'),(tracker_class(),'subpixel_candidate_NOT_SELECTED')]:
        tracker=cls();cap=cv2.VideoCapture(str(video));rows={1:[],2:[]};n=0
        while True:
            ok,f=cap.read()
            if not ok:break
            n+=1;pts=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            for p in tracker.update(cv2.rotate(f,cv2.ROTATE_180),pts,REFERENCE):
                if p['status']!='visual_constrained':continue
                angle=projected(p['joints'])[1]['elbow'];rows[p['arm_id']].append((angle,p['quality_score'],p['plate_rms_px']*2**.5))
                raw.append(dict(algorithm=name,source_pts_s=pts,arm_id=p['arm_id'],angle_deg=angle,Q=p['quality_score'],rms_px=p['plate_rms_px']*2**.5))
        cap.release();comparisons[name]={}
        for arm,data in rows.items():
            a=np.array(data,float)
            comparisons[name][str(arm)]=dict(valid_ratio=len(data)/n,frames=n,valid_frames=len(data),angle_std_deg=float(np.std(a[:,0],ddof=1)),
                Q_median=float(np.median(a[:,1])),rms_px_median=float(np.median(a[:,2]))) if len(a) else dict(valid_ratio=0,frames=n)
    (out/'localization_comparison.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in raw),encoding='utf-8')
    result=dict(mode='OFFLINE_ONLY',status='PASS',real_motor_commands=0,source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        parent_run_id='experiment_20261117T082708_670b76b1',first_counterfactual_pause_pts_ms=first_pause,replay_samples=len(replay),cases=cases,
        static_algorithm_comparison=comparisons,notes='Injected faults and controller arrivals are simulated, never physical success. Recall/false alarm only applies to labelled limited test matrix; no physical detector performance estimate.')
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='PASS',cases=len(cases),first_pause_ms=first_pause,algorithm_comparison=comparisons),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
