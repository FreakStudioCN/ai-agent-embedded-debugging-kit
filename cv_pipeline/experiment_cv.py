"""Continuous structured CV, fixed command priors, per-camera settled windows.

The existing FusedTracker supplies visually constrained projections. B/S remain
fixed mounting model estimates, E/TCP are plate-PnP/link-constrained estimates.
Angles below are PROJECTED estimates, never absolute measured servo angles.
The reference count prior is held constant throughout a batch, regardless of
motor commands, so PWM changes cannot manufacture measured angular response.
Confidence is the original uncalibrated Q=visible/4*exp(-rms_coordinate/3), with
original prediction/lost penalties. Window thresholds are not relaxed.
"""
from collections import deque
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np
from monitor_core import VideoReader
from experiment_safety import REFERENCE


def projected(points):
    def direction(a,b):
        x,y=np.subtract(points[b],points[a])
        if math.hypot(x,y)<5:raise ValueError('Projected link too short')
        return math.degrees(math.atan2(y,x))
    upper=direction('S','E');forearm=direction('E','TCP')
    return dict(upper=upper,forearm=forearm),dict(elbow=(forearm-upper+180)%360-180)


def window_stats(rows, minimum_ms=1200, std_limit=1.5):
    if not rows:return None
    span=rows[-1]['monotonic_ms']-rows[0]['monotonic_ms']
    good=[r for r in rows if r['track_valid'] and r['joint_angles_deg'].get('elbow') is not None]
    angles=np.array([r['joint_angles_deg']['elbow'] for r in good],float)
    times=np.array([r['monotonic_ms'] for r in good],float)/1000
    angles=np.degrees(np.unwrap(np.radians(angles)))
    ratio=len(good)/len(rows)
    confidence=float(np.median([r['confidence'] for r in good])) if good else None
    rms=[r['rms_px'] for r in good if r['rms_px'] is not None]
    jitter=float(np.std(angles,ddof=1)) if len(angles)>1 else None
    drift=float(np.polyfit(times-times[0],angles,1)[0]) if len(times)>1 and times[-1]>times[0] else None
    versions={r.get('calibration_version') for r in rows}
    stable_view=len({r['camera_pose_id'] for r in rows})==1 and len(versions)==1 and not any(r['camera_moving'] for r in rows)
    stationary=(span>=minimum_ms and len(good)>=3 and ratio>=.85 and confidence is not None and confidence>=.80
        and rms and float(np.median(rms))<=5 and jitter is not None and jitter<=std_limit
        and drift is not None and abs(drift)<=1 and stable_view)
    return dict(camera_id=rows[-1]['camera_id'],camera_pose_id=rows[-1]['camera_pose_id'],arm_id=rows[-1]['arm_id'],
        joint='elbow',window_ms=span,valid_frames=len(good),total_frames=len(rows),valid_ratio=ratio,
        confidence_median=confidence,rms_px_median=float(np.median(rms)) if rms else None,
        angle_median_deg=float(np.median(angles)) if len(angles) else None,angle_std_deg=jitter,
        angle_drift_deg_per_s=drift,stationary=bool(stationary),measurement_mode='pnp_constrained_2d_projected',parameter_version='cv-wrist-global-region-v2',
        calibration_version=next(iter(versions)) if len(versions)==1 else None,
        cv_version=rows[-1].get('cv_version','cv-wrist-global-region-v2'))


def baseline_threshold(sigma):
    """User revision: min(3.5, max(1.5,3*sigma)); no other gate is changed."""
    if type(sigma) not in (int,float) or not math.isfinite(sigma) or sigma<0:
        raise ValueError('Invalid baseline sigma')
    return min(3.5,max(1.5,3*sigma))


def coarse_regions(frame):
    """Global camera: HSV regions only; never infer invisible joint angles.

    Confidence=area adequacy capped at1, area target0.2% of full frame. Two
    separated, upright regions >=60px high are required; this is a visibility
    score, not a probability or person detector. IDs follow fixed left/right
    mounting, valid for this experiment's fixed bases and one pitch joint.
    """
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(27,51,52),(78,255,255))
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        area=float(cv2.contourArea(contour));x,y,w,h=cv2.boundingRect(contour)
        if area>=frame.shape[0]*frame.shape[1]*.001 and h>=60 and h>w*.8:
            candidates.append(dict(box=[x,y,w,h],area=area,centroid=[x+w/2,y+h/2],confidence=min(1.,area/(frame.shape[0]*frame.shape[1]*.002))))
    candidates=sorted(sorted(candidates,key=lambda c:c['area'],reverse=True)[:2],key=lambda c:c['centroid'][0])
    if len(candidates)!=2:return {}
    if candidates[1]['box'][0]<=candidates[0]['box'][0]+candidates[0]['box'][2]:return {}
    return dict(enumerate(candidates,1))


def coarse_window_stats(rows):
    if not rows:return None
    good=[r for r in rows if r['track_valid'] and r.get('region_centroid_px')]
    span=rows[-1]['monotonic_ms']-rows[0]['monotonic_ms'];ratio=len(good)/len(rows)
    jitter=float(np.max(np.std([r['region_centroid_px'] for r in good],axis=0))) if good else None
    return dict(camera_id='global_8769',camera_pose_id='global_fixed_01',arm_id=rows[-1]['arm_id'],measurement_mode='region_only',
        window_ms=span,valid_frames=len(good),valid_ratio=ratio,confidence_median=float(np.median([r['confidence'] for r in good])) if good else None,
        rms_px_median=None,angle_median_deg=None,angle_std_deg=None,angle_drift_deg_per_s=None,region_centroid_std_max_px=jitter,
        stationary=bool(span>=1200 and ratio>=.85 and jitter is not None and jitter<=3))


class CVStream:
    def __init__(self,folder,emit):
        self.folder=Path(folder);self.emit=emit;self.run_id=self.folder.name
        self.stop=threading.Event();self.lock=threading.Lock();self.history={};self.failure=None
        self.camera_pose_id='unverified_initial';self.camera_moving=False;self.motion_id=None
        self.readers={cid:VideoReader('http://127.0.0.1:%d/stream.mjpg'%port,rotation)
            for cid,port,rotation in [('wrist_8768',8768,180),('global_8769',8769,0)]}
        self.threads=[threading.Thread(target=self.worker,args=(cid,),daemon=True) for cid in self.readers]
        self.reset_generation=0
        self.std_limit=1.5
        self.on_failure=None
        self.background_callback=None
        self.calibration_provider=None
        self.tracker_factory=None
        self.cv_version='cv-wrist-global-region-v2'

    def fail(self,reason):
        """Latch the first failure immediately; callback never sends hardware I/O."""
        with self.lock:
            if self.failure is not None:return
            self.failure=str(reason)
        self.emit('safety_pause',reason=str(reason),source='CV worker',new_motion_prohibited=True,release_requested=False)
        if self.on_failure:self.on_failure(str(reason))

    def start(self):
        self.started=time.monotonic()
        for r in self.readers.values():r.thread.start()
        for t in self.threads:t.start()

    def worker(self,cid):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Mr-Robot-Arm'))
        from mr_robot_desktop.fused_pose import FusedTracker
        if self.tracker_factory:FusedTracker=self.tracker_factory()
        tracker=FusedTracker();seq=-1;generation=self.reset_generation;bad_since={}
        reader=self.readers[cid]
        try:
            while not self.stop.is_set():
                frame,n,received,_,error=reader.latest()
                if frame is None or n==seq:
                    if time.monotonic()-getattr(self,'started',time.monotonic())>3 and (frame is None or time.monotonic()-received>1):
                        self.fail(cid+' camera timeout/no fresh frame')
                    self.stop.wait(.01);continue
                seq=n;now=time.monotonic()
                if self.reset_generation!=generation:
                    if cid=='wrist_8768':tracker.reset()
                    generation=self.reset_generation
                stale=bool(error) or now-received>1
                moving=self.camera_moving and cid=='wrist_8768'
                source=cv2.cvtColor(np.asarray(frame),cv2.COLOR_RGB2BGR)
                if cid=='wrist_8768' and self.background_callback:
                    self.background_callback(source,received,not stale)
                calibration=self.calibration_provider() if self.calibration_provider else {}
                coarse=coarse_regions(source) if cid=='global_8769' and not stale else {}
                poses={} if stale or moving or cid=='global_8769' else {p['arm_id']:p for p in tracker.update(source,received,REFERENCE)}
                for arm in (1,2):
                    pose=poses.get(arm);region=coarse.get(arm)
                    valid=(region is not None) if cid=='global_8769' else (pose is not None and pose['status']=='visual_constrained')
                    reason=None if valid else ('camera_stale' if stale else 'camera_moving' if moving else 'PnP_or_tracking_invalid')
                    links={};joints={};keypoints={k:None for k in ('base','shoulder','elbow','tip')}
                    if pose:
                        keypoints=dict(zip(keypoints,[pose['joints'][k] for k in ('B','S','E','TCP')]))
                        if valid:
                            try:links,joints=projected(pose['joints'])
                            except ValueError as exc:valid=False;reason=str(exc)
                    row=dict(schema_version='1.0',run_id=self.run_id,timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        monotonic_ms=received*1000,processed_monotonic_ms=now*1000,frame_id=n,camera_id=cid,
                        camera_pose_id=self.camera_pose_id if cid=='wrist_8768' else 'global_fixed_01',camera_moving=moving,arm_id='green_'+str(arm),motion_id=self.motion_id,
                        track_valid=valid,invalid_reason=reason,keypoints_px=keypoints,
                        link_angles_deg={k:links.get(k) for k in ('upper','forearm')},joint_angles_deg={'elbow':joints.get('elbow')},
                        measurement_mode='region_only' if cid=='global_8769' else 'pnp_constrained_2d_projected',rms_px=float(pose['plate_rms_px'])*math.sqrt(2) if pose and valid else None,
                        confidence=float(region['confidence']) if region else float(pose['quality_score']) if pose else None,is_stationary=False,
                        fixed_reference_count_prior=True,joint_centers_measured=False,keypoint_sources=pose.get('joint_sources') if pose else None,
                        region_box_px=region['box'] if region else None,region_centroid_px=region['centroid'] if region else None,
                        calibration_version=calibration.get('calibration_version'),calibration_valid=calibration.get('calibration_valid',False),
                        visible_plate_features=pose.get('visible_plate_features') if pose else 0,cv_version=self.cv_version)
                    with self.lock:
                        history=self.history.setdefault((cid,arm),deque(maxlen=3000))
                        history.append(row)
                        window=[r for r in history if row['monotonic_ms']-r['monotonic_ms']<=1400]
                        stats=coarse_window_stats(window) if cid=='global_8769' else window_stats(window,std_limit=self.std_limit)
                        row['is_stationary']=bool(stats and stats['stationary'])
                        if moving:
                            bad_since.pop(arm,None)
                        elif not valid or row['confidence'] is None or row['confidence']<.60:
                            bad_since.setdefault(arm,now)
                            if now-bad_since[arm]>=2 and self.failure is None:
                                # Defer callback until after releasing history lock.
                                bad_reason=cid+' green_'+str(arm)+' tracking/confidence failure >=2s'
                        else:bad_since.pop(arm,None)
                    with self.lock:
                        with (self.folder/'pose_stream.jsonl').open('a',encoding='utf-8') as f:
                            f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
                    if 'bad_reason' in locals():
                        self.fail(bad_reason);del bad_reason
                self.stop.wait(.005)
        except BaseException as exc:
            self.fail(cid+': '+repr(exc))
            self.emit('tracking_failure',camera_id=cid,error=repr(exc))

    def stats(self,after=0):
        with self.lock:
            return {cid:{str(arm):(coarse_window_stats([r for r in self.history.get((cid,arm),[]) if r['monotonic_ms']>=after*1000]) if cid=='global_8769' else window_stats([r for r in self.history.get((cid,arm),[]) if r['monotonic_ms']>=after*1000],minimum_ms=10000,std_limit=self.std_limit))
                for arm in (1,2)} for cid in self.readers}

    def global_ready(self):
        with self.lock:
            for arm in (1,2):
                rows=self.history.get(('global_8769',arm),[])
                if not rows or time.monotonic()*1000-rows[-1]['monotonic_ms']>750 or not rows[-1]['track_valid']:
                    return False
            return True

    def settled(self,after,camera='wrist_8768',arm=2,std_limit=1.5):
        with self.lock:
            rows=list(self.history.get((camera,arm),[]))
            now=time.monotonic()*1000
            if not rows or now-rows[-1]['monotonic_ms']>750:return None
            rows=[r for r in rows if r['monotonic_ms']>=max(after*1000,now-1500)]
            return window_stats(rows,std_limit=std_limit)

    def close(self):
        self.stop.set()
        for r in self.readers.values():r.stop.set()
        for t in self.threads:t.join(3)
