"""S0 only: reads identity/registers/shared camera streams; never motor writes."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import sys
import threading
import time
from urllib.request import urlopen
ROOT=_WORKSPACE_ROOT;sys.path.insert(0,str(ROOT))
from serial.tools import list_ports
from cv_pipeline.embodied_demo import MicroPythonSession
from cv_pipeline.recovery_workflow import registers,snapshots,save
from cv_pipeline.experiment_cv import CVStream
from experiment_safety import SafeExecutor,REFERENCE,WINDOWS,VIEWS,EDGES
from cv_pipeline.phase_r_v11 import strict_noise_limit
from cv_pipeline.phase_r_v11 import PhaseRV11
from cv_pipeline.vision_lk import tracker_class


def main():
    out=Path(sys.argv[1]);lock=ROOT/'.runtime/phase_r_state.json'
    initial_hash=hashlib.sha256(lock.read_bytes()).hexdigest();write_lock=threading.Lock()
    def event(kind,**details):
        row=dict(schema_version='1.1',run_id=out.name,timestamp_utc=datetime.now(timezone.utc).isoformat(),
            monotonic_ms=time.monotonic_ns()/1e6,event=kind,motion_id=details.pop('motion_id',None),details=details)
        with write_lock:
            with (out/'experiment_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    result=dict(protocol='1.1',mode='S0_READ_ONLY',motion_authorized=False,position_trusted=False,
        position='UNKNOWN; last historical nominal target A is not feedback',software_estop='No verified physical emergency-stop/position query in current COM3 protocol',
        physical_switch='Must be freshly confirmed by operator',cable_path='Must be freshly confirmed by operator',
        reference=REFERENCE,windows=WINDOWS,views=VIEWS,edges=EDGES,root_lockout_before=json.loads(lock.read_text(encoding='utf-8')))
    result['ports']={p.device:dict(vid=p.vid,pid=p.pid,serial_number=p.serial_number,hwid=p.hwid) for p in list_ports.comports()}
    session=None
    try:
        p=result['ports'].get('COM8',{})
        if (p.get('serial_number') or '').lower()!='70:af:09:2a:ee:e8':raise RuntimeError('COM8 USB identity mismatch')
        session=MicroPythonSession('COM8')
        result['uid']=session.rpc("__import__('machine').unique_id().hex()",timeout=4)
        result['pca']=registers(session);result['dual_arm']=session.rpc('d.status()',timeout=4)
        result['main_py']=session.rpc("open('/main.py').read()",timeout=4)
        SafeExecutor.check_hardware(result['uid'],result['pca'],result['dual_arm']);result['hardware_config_valid']=True
    except Exception as exc:result['hardware_config_valid']=False;result['hardware_error']=repr(exc);event('safety_pause',reason=repr(exc),stage='S0',motor_writes=0)
    finally:
        if session:session.close();(out/'com8_readonly_transport.jsonl').write_bytes(session.path.read_bytes())
    cv=CVStream(out,event);cv.calibration_provider=lambda:dict(calibration_version='UNVALIDATED-v11-S0',calibration_valid=False)
    if '--lk' in sys.argv:cv.tracker_factory=tracker_class;cv.cv_version='cv-lk-subpixel-v11'
    samples=[];cv.start();start=time.monotonic()
    try:
        while time.monotonic()-start<12:
            row=dict(monotonic_ms=time.monotonic_ns()/1e6,cameras={})
            for camera,port in [('wrist_8768',8768),('global_8769',8769)]:
                try:
                    with urlopen('http://127.0.0.1:%d/api/status'%port,timeout=1) as response:row['cameras'][camera]=json.load(response)
                except Exception as exc:row['cameras'][camera]=dict(healthy=False,error=repr(exc))
            samples.append(row);time.sleep(.08)
        stats=cv.stats(start);result['camera_fault']=cv.failure;result['static_candidate']=stats
        result['static_candidate_duration_s']=time.monotonic()-start
        result['strict_noise_limits']={}
        for arm in (1,2):
            try:result['strict_noise_limits'][str(arm)]=dict(limit_deg=strict_noise_limit(stats['wrist_8768'][str(arm)]['angle_std_deg']),valid=True)
            except Exception as exc:result['strict_noise_limits'][str(arm)]=dict(valid=False,error=repr(exc))
        result['clearance_keyframes']=snapshots(out,'S0-direction-and-clearance',event)
        event('image_inspection',reason='S0 direction verification and clearance assistance; no motion authority',frame_paths=result['clearance_keyframes'],count=2)
        if '--lk' in sys.argv:
            candidate=PhaseRV11(out/'candidate_recovery_state.json',event,out.name,recovery_dir=out/'recovery')
            def sample():
                import cv2,numpy as np
                frame,_,received,_,error=cv.readers['wrist_8768'].latest()
                if error or frame is None:raise RuntimeError('Camera unavailable')
                return cv2.cvtColor(np.asarray(frame),cv2.COLOR_RGB2BGR),received
            result['background_candidate']=candidate.collect_background(sample)
            save(out,'recovery/background_reference.json',dict(candidate_only=True,accepted_for_motion=False,**result['background_candidate']))
    finally:cv.close()
    (out/'camera_status_samples.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in samples),encoding='utf-8')
    continuity={}
    for camera in ('wrist_8768','global_8769'):
        c=[x['cameras'][camera] for x in samples];times=[datetime.fromisoformat(x['frame_utc']).timestamp() for x in c if x.get('frame_utc')]
        gaps=[b-a for a,b in zip(times,times[1:]) if b!=a]
        rows=[json.loads(line) for line in (out/'pose_stream.jsonl').read_text(encoding='utf-8').splitlines()]
        rows=[r for r in rows if r['camera_id']==camera and r['arm_id']=='green_1']
        receive=[r['monotonic_ms'] for r in rows]
        continuity[camera]=dict(all_healthy=all(x.get('healthy') for x in c),timestamp_regressions=sum(b<a for a,b in zip(times,times[1:])),
            max_capture_status_gap_s=max(gaps) if gaps else None,unique_source_frames=len(set(times)),
            cv_unique_frames=len(receive),cv_max_receive_gap_s=max([b-a for a,b in zip(receive,receive[1:])],default=0)/1000,
            rotation_degrees=180 if camera=='wrist_8768' else 0)
    result['continuity']=continuity;result['root_lockout_unchanged']=hashlib.sha256(lock.read_bytes()).hexdigest()==initial_hash
    save(out,'preflight.json',result);save(out,'baseline.json',dict(candidate_only=True,calibration_valid=False,statistics=result['static_candidate'],strict_noise_limits=result['strict_noise_limits']))
    save(out,'camera_continuity.json',continuity);save(out,'safety_gate.json',dict(stage='S0',motion_allowed=False,fresh_S1_granted=False,persistent_lockout_preserved=True))
    event('preflight',result=result,motor_writes=0,COM3_opened=False)
    print(json.dumps(dict(out=str(out),hardware_valid=result['hardware_config_valid'],continuity=continuity,noise=result['strict_noise_limits'],camera_fault=result['camera_fault'],root_unchanged=result['root_lockout_unchanged']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
