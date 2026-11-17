"""Replay-only evaluation of plate-registration CV, including fault rejection."""
from pathlib import Path
from datetime import datetime,timezone
import sys
import json
import time
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent/'Mr-Robot-Arm'))
from cv_pipeline.vision_planar_registration import PlanarRegistrationTracker,VERSION


def main():
    parent=Path(sys.argv[1]);out=parent/('planar_registration_'+datetime.now(timezone.utc).strftime('%H%M%S'))
    out.mkdir();rows=[];cap=cv2.VideoCapture(str(parent/'media/recording/vision.mkv'));cap.set(cv2.CAP_PROP_POS_MSEC,104000)
    tracker=PlanarRegistrationTracker();first=None;begin=time.monotonic();frames=0
    while True:
        ok,f=cap.read()
        if not ok:break
        pts=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
        if pts>165:break
        frame=cv2.rotate(f,cv2.ROTATE_180)
        if first is None:first=frame.copy()
        frames+=1
        for row in tracker.update(frame,pts):
            rows.append(dict(schema_version='1.1',run_id=out.name,mode='HISTORICAL_VIDEO_REPLAY_NO_MOTORS',
                timestamp_utc=datetime.now(timezone.utc).isoformat(),monotonic_ms=time.monotonic_ns()/1e6,source_pts_s=pts,**row))
    cap.release();statistics={}
    for arm in (1,2):
        statistics[str(arm)]={}
        for label,low,high in [('baseline',108,119),('before_motion',130,141),('after_motion',148,159)]:
            selected=[x for x in rows if x['arm_id']==arm and low<=x['source_pts_s']<=high];good=[x for x in selected if x['track_valid']]
            if len(good)<3:statistics[str(arm)][label]=dict(valid_ratio=len(good)/len(selected) if selected else 0,invalid_reasons=sorted({x.get('invalid_reason','') for x in selected}));continue
            angle=np.array([x['relative_plate_rotation_deg'] for x in good]);image=np.array([x['image_axis_delta_deg'] for x in good])
            vectors=np.array([x['relative_rotation_vector_deg'] for x in good]);times=np.array([x['source_pts_s'] for x in good]);sigma=float(angle.std(ddof=1));Q=float(np.median([x['confidence'] for x in good]));rms=float(np.median([x['pnp_rms_px'] for x in good]));ratio=len(good)/len(selected)
            statistics[str(arm)][label]=dict(samples=len(good),valid_ratio=ratio,rotation_median_deg=float(np.median(angle)),rotation_std_deg=sigma,
                rotation_vector_component_std_deg=vectors.std(axis=0,ddof=1).tolist(),image_axis_median_deg=float(np.median(image)),image_axis_std_deg=float(image.std(ddof=1)),
                Q_median=Q,pnp_rms_median_px=rms,trend_deg_per_s=float(np.polyfit(times-times[0],angle,1)[0]),
                candidate_quality_pass=bool(ratio>=.85 and Q>=.8 and rms<=5 and max(1.,3*sigma)<=1.5))
    # Faults are injected in recorded images only, never USB or physical hardware.
    fault_cases=[]
    for name,change in [('blank',lambda f:np.full_like(f,127)),('occluded-plate',lambda f:cv2.rectangle(f.copy(),(0,0),(f.shape[1],int(f.shape[0]*.6)),(30,30,30),-1))]:
        probe=PlanarRegistrationTracker();probe.update(first,0);result=probe.update(change(first),.1)
        rejected=bool(result) and all(not r['track_valid'] or r.get('confidence',0)<.8 for r in result)
        fault_cases.append(dict(name=name,rejected=rejected,mode='SYNTHETIC_IMAGE_FAULT_NO_MOTORS',results=result))
    # Static repeated image must not create large relative rotation.
    static=PlanarRegistrationTracker();static_rows=[]
    for i in range(20):static_rows.extend(static.update(first,i*.1))
    static_max=max((r['relative_plate_rotation_deg'] for r in static_rows if r['track_valid']),default=None)
    result=dict(cv_version=VERSION,mode='REPLAY_ONLY_NOT_PHYSICAL_ACCEPTANCE',source=str(parent/'media/recording/vision.mkv'),source_run_id=parent.name,
        statistics=statistics,fault_cases=fault_cases,static_repeat_max_rotation_deg=static_max,frames=frames,processing_wall_s=time.monotonic()-begin,
        real_motor_commands=0,implementation='Frozen plate ROI -> direct reference features -> RANSAC H -> masked ECC -> relative plate orientation; no FK or command count geometry',
        caveats=['Relative plate rotation is a single-joint proxy; absolute anatomical joint angle is not measured.',
                 'Approximate intrinsics remain uncalibrated; no claim of accurate absolute degrees.',
                 'No E0/E1 compensation measurements were performed; algorithm quality is not backlash improvement.',
                 'Replay fault tests do not establish physical detector recall or safe human clearance.'])
    (out/'pose_stream.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,allow_nan=False)+'\n' for x in rows),encoding='utf-8')
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(out=str(out),statistics=statistics,fault_rejections=[(x['name'],x['rejected']) for x in fault_cases],static_repeat_max_deg=static_max,real_motor_commands=0),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
