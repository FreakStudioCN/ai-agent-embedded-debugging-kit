"""Offline video benchmark. No serial ports, camera devices or motion authority.

Each selected source frame is independently detected. Legacy replay exists only
for comparison and is never imported by contour_axis_2d.py. All overlays show
current accepted/rejected candidates; no held angle is displayed on loss.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse
import hashlib
import json
import math
import sys
import time
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cv_pipeline.contour_axis_2d import ContourAxisDetector,AxisConfig,VERSION,MODE,axial_difference,draw_axis_overlay


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def statistics(rows,start=None,end=None):
    selected=[r for r in rows if (start is None or r['source_pts_s']>=start) and (end is None or r['source_pts_s']<=end)]
    good=[r for r in selected if r['measurement_valid'] and r.get('axis_angle_deg') is not None]
    result=dict(frames=len(selected),valid_frames=len(good),valid_ratio=len(good)/len(selected) if selected else 0,
        loss_rate=1-len(good)/len(selected) if selected else None,
        invalid_reasons=dict(Counter(r.get('invalid_reason') for r in selected if not r['measurement_valid'])),
        true_wrong_tracking_rate=None,wrong_tracking_limitation='No independent per-frame physical link/angle ground truth in source video')
    if len(good)<3:return dict(result,axis_median_deg=None,axis_std_deg=None,drift_deg_per_s=None,endpoint_shift_deg=None,temporal_window_repeatability_deg=None)
    factor=2 if good[0]['measurement_mode']==MODE else 1
    angles=np.degrees(np.unwrap(np.radians([r['axis_angle_deg']*factor for r in good])))/factor
    times=np.array([r['source_pts_s'] for r in good]);duration=times[-1]-times[0]
    block_width=2.;blocks=[];block_coverage=[]
    if duration>0:
        for low in np.arange(times[0],times[-1],block_width):
            use=(times>=low)&(times<low+block_width)
            if use.sum()>=3:blocks.append(float(np.median(angles[use])));block_coverage.append(int(use.sum()))
    endpoint_width=min(10,max(1,duration/4));head=angles[times<=times[0]+endpoint_width];tail=angles[times>=times[-1]-endpoint_width]
    std=float(np.std(angles,ddof=1));trend=float(np.polyfit(times-times[0],angles,1)[0]) if duration>0 else None
    result.update(axis_median_deg=float(np.median(angles)),axis_std_deg=std,drift_deg_per_s=trend,
        endpoint_shift_deg=float(np.median(tail)-np.median(head)),max_min_range_deg=float(np.ptp(angles)),
        temporal_window_repeatability_deg=float(np.std(blocks,ddof=1)) if len(blocks)>1 else None,temporal_window_medians_deg=blocks,
        repeatability_definition='Spread of nonoverlapping2s medians; NOT independent servo-return repeatability',
        diagnostic_quality_pass=bool(result['valid_ratio']>=.85 and max(1.,3*std)<=1.5 and trend is not None and abs(trend)<=1))
    return result


def legacy_rows(tracker,frame,pts,source_id,frame_id):
    from cv_pipeline.experiment_cv import projected
    poses={p['arm_id']:p for p in tracker.update(frame,pts,{1:[307,287,297],2:[307,307,307]})};result=[]
    for arm in (1,2):
        pose=poses.get(arm);raw=None
        if pose and pose['status']=='visual_constrained':
            try:raw=projected(pose['joints'])[1]['elbow']
            except ValueError:pass
        Q=pose.get('quality_score') if pose else None;rms=pose.get('plate_rms_px')*math.sqrt(2) if pose and pose.get('plate_rms_px') is not None else None
        valid=raw is not None and Q is not None and Q>=.8 and rms is not None and rms<=5
        result.append(dict(schema_version='1.1',run_id=source_id,source_pts_s=pts,monotonic_ms=pts*1000,frame_id=frame_id,
            camera_id='wrist_8768',camera_pose_id=source_id,arm_id='green_'+str(arm),measurement_mode='legacy_pnp_fk_projected',
            cv_version='upstream-fused-pose-replay',parameter_version='original-fixed-count-prior',calibration_version='analysis-only-legacy-'+source_id,
            calibration_valid=False,measurement_valid=bool(valid),axis_angle_deg=raw if valid else None,raw_axis_angle_deg=raw,
            confidence=Q,pnp_rms_px=rms,invalid_reason=None if valid else 'legacy_tracking_or_Q_RMS_gate'))
    return result


def evaluate_clip(job):
    cv2.setNumThreads(1)
    sys.path.insert(0,str(ROOT.parent/'Mr-Robot-Arm'))
    from mr_robot_desktop.fused_pose import FusedTracker
    source=ROOT/job['source'];folder=Path(job['output'])/job['id'];folder.mkdir()
    detector=ContourAxisDetector();legacy=FusedTracker();capture=cv2.VideoCapture(str(source));fps=capture.get(cv2.CAP_PROP_FPS) or 10
    capture.set(cv2.CAP_PROP_POS_MSEC,job['start']*1000)
    rows=[];old=[];costs=[];writer=None;n=0;source_frames=0;pts_previous=None;gaps=[];audit=[];start=time.monotonic()
    try:
        while True:
            ok,frame=capture.read()
            if not ok:break
            pts=capture.get(cv2.CAP_PROP_POS_MSEC)/1000
            if pts>job['end']:break
            source_frames+=1
            if (source_frames-1)%job.get('stride',1):continue
            if job.get('rotation',180):frame=cv2.rotate(frame,cv2.ROTATE_180)
            n+=1;before=time.monotonic();detected=detector.detect(frame);costs.append(time.monotonic()-before)
            for row in detected:
                row.update(schema_version='1.1',run_id=folder.parent.name,source_run_id=job['source_run_id'],source_video=str(source),source_pts_s=pts,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),monotonic_ms=pts*1000,processed_monotonic_ms=time.monotonic_ns()/1e6,
                    time_domain='source_video_pts',frame_id=source_frames,camera_id='wrist_8768',camera_pose_id=job['id'],camera_moving=False,
                    calibration_version='analysis-only-'+job['id']+'-'+detector.config.parameter_version,calibration_valid=False,
                    analysis_only=True,motion_authorized=False,delta_angle_deg=None,reference_qualified=False,
                    target_joint='CH9' if job.get('ch9_motion') else None,target_joint_response_verified=False)
                rows.append(row)
            old.extend(legacy_rows(legacy,frame,pts,job['id'],source_frames))
            overlay=draw_axis_overlay(frame,detected,pts)
            if writer is None:
                writer=cv2.VideoWriter(str(folder/'roi_overlay.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps/job.get('stride',1),(frame.shape[1],frame.shape[0]))
                if not writer.isOpened():raise RuntimeError('Cannot open overlay writer')
            writer.write(overlay)
            if pts_previous is not None and pts-pts_previous>max(.5,3/fps*job.get('stride',1)):gaps.append(dict(previous_s=pts_previous,current_s=pts,gap_s=pts-pts_previous))
            pts_previous=pts
            if n in (1,50,150) or abs(pts-job.get('audit_time',-99))<.05:
                path=folder/('overlay_frame_%05d.jpg'%n);cv2.imwrite(str(path),overlay);audit.append(dict(frame_id=source_frames,source_pts_s=pts,image=path.name))
            if n%50==0:print(json.dumps(dict(clip=job['id'],analyzed=n,source_pts_s=pts)),flush=True)
    finally:
        capture.release()
        if writer:writer.release()
    summaries={}
    baseline_end=job.get('baseline_end',job['start']+12)
    for algorithm,data in [('contour_axis_2d',rows),('legacy_fused_pose',old)]:
        summaries[algorithm]={}
        for arm in ('green_1','green_2'):
            selected=[r for r in data if r['arm_id']==arm]
            summary=statistics(selected)
            baseline=statistics(selected,job.get('baseline_start',job['start']),baseline_end)
            summary['baseline']=baseline
            if job.get('ch9_motion'):
                summary['before_motion']=statistics(selected,130,141);summary['after_motion']=statistics(selected,148,159)
                a=summary['before_motion'];b=summary['after_motion'];effect=None
                if a.get('axis_median_deg') is not None and b.get('axis_median_deg') is not None:effect=axial_difference(b['axis_median_deg'],a['axis_median_deg'])
                summary['diagnostic_motion_delta_deg']=effect
                summary['response_valid']=bool(effect is not None and a['valid_ratio']>=.85 and b['valid_ratio']>=.85 and abs(effect)>3*math.hypot(a.get('axis_std_deg') or 0,b.get('axis_std_deg') or 0))
            summaries[algorithm][arm]=summary
            if algorithm=='contour_axis_2d':
                reference=baseline.get('axis_median_deg');qualified=baseline.get('diagnostic_quality_pass',False)
                for row in selected:
                    row.update(reference_angle_deg=reference,reference_qualified=qualified,
                        diagnostic_delta_angle_deg=axial_difference(row['axis_angle_deg'],reference) if row['measurement_valid'] and reference is not None else None)
                    if qualified and row['measurement_valid']:row['delta_angle_deg']=row['diagnostic_delta_angle_deg']
    for filename,data in [('pose_stream.jsonl',rows),('legacy_pose_stream.jsonl',old)]:
        (folder/filename).write_text(''.join(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n' for row in data),encoding='utf-8')
    result=dict(id=job['id'],source=str(source),source_sha256=digest(source),rotation=job.get('rotation',180),source_start_s=job['start'],source_end_s=job['end'],
        frame_stride=job.get('stride',1),decoded_source_frames=source_frames,analyzed_frames=n,source_fps=fps,
        summaries=summaries,processing_median_ms=float(np.median(costs))*1000 if costs else None,processing_p95_ms=float(np.percentile(costs,95))*1000 if costs else None,
        wall_s=time.monotonic()-start,source_gaps=gaps,overlay_keyframes=audit,real_motor_commands=0,
        true_joint_angle_accuracy=None,physical_servo_repeatability=None,
        limitation='Legacy FK elbow and contour link image axis are different observables; quality diagnostics only, never mixed E0/E1.')
    (folder/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);parser.add_argument('--workers',type=int,default=2);parser.add_argument('--quick',action='store_true');args=parser.parse_args()
    run='contour_validation_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    out=args.output or ROOT/'.runtime'/run;out.mkdir(parents=True,exist_ok=False)
    (ROOT/'.runtime/contour_evaluation_output.txt').write_text(str(out.resolve()),encoding='utf-8')
    state=ROOT/'.runtime/phase_r_state.json';state_hash=digest(state)
    jobs=[dict(id='long_static',source='.runtime/experiment_20261117T075459_750e71b2/media/recording/vision.mkv',source_run_id='experiment_20261117T075459_750e71b2',start=2.,end=45.,baseline_start=2.,baseline_end=14.),
          dict(id='B_CH9_actual',source='.runtime/experiment_20261117T092542_cd2ffd8d/media/recording/vision.mkv',source_run_id='experiment_20261117T092542_cd2ffd8d',start=106.,end=161.,baseline_start=108.,baseline_end=120.,ch9_motion=True,audit_time=130.)]
    if args.quick:
        for job in jobs:job['stride']=5
    for job in jobs:job.update(output=str(out.resolve()),rotation=180)
    (out/'dataset_manifest.json').write_text(json.dumps(dict(run_id=run,mode='OFFLINE_ONLY',jobs=jobs,config=detector_config(),current_state_sha256=state_hash),ensure_ascii=False,indent=2),encoding='utf-8')
    results=[]
    with ProcessPoolExecutor(max_workers=max(1,min(2,args.workers))) as pool:
        futures={pool.submit(evaluate_clip,job):job['id'] for job in jobs}
        for future in as_completed(futures):
            result=future.result();results.append(result);print(json.dumps(dict(completed=result['id'],frames=result['analyzed_frames'])),flush=True)
    record=dict(run_id=run,mode='OFFLINE_ONLY_NO_HARDWARE',cv_version=VERSION,results=results,root_paused_state_unchanged=digest(state)==state_hash,
        actual_motion_commands=0,main_cv_switched=False,legacy_new_E0_E1_comparisons=0)
    (out/'validation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(out),completed=[r['id'] for r in results],paused_state_unchanged=record['root_paused_state_unchanged']),ensure_ascii=False),flush=True)


def detector_config():
    from dataclasses import asdict
    return dict(parameters=asdict(AxisConfig()),parameter_version=AxisConfig().parameter_version,source_sha256=digest(ROOT/'cv_pipeline/contour_axis_2d.py'))


if __name__=='__main__':main()
