"""Phase R: persistent visual-reference admission, never a motion controller.

Background registration is evidence of image-plane drift, not an encoder or
metric hand-eye calibration. Unknown position/camera faults close admission;
there is no G28/G1/release/reconnect in this module. A legal observer transaction
may only collect a new baseline at its registered verified destination.
"""
from dataclasses import dataclass,asdict
from pathlib import Path
import json
import math
import threading
import time
import uuid

import cv2
import numpy as np
from experiment_safety import SafetyError,VIEWS,EDGES


@dataclass(frozen=True)
class ControllerEvidence:
    connected: bool
    position_trusted: bool
    motion_state: str  # IDLE / MOVING / WAIT_SETTLE / UNKNOWN; source explicit
    position: tuple | None = None
    source: str = 'host lifecycle; no independent position sensor'
    motion_id: str | None = None


class BackgroundTracker:
    """Static non-green features; LK forward/back check + RANSAC similarity.

    >=20 inliers, ratio>=0.65; image-plane drift threshold5px/0.75deg/1.5%.
    Green targets are excluded. Independently moving non-green backgrounds can
    invalidate evidence; they are not treated as permission to recalibrate.
    """
    def __init__(self):self.gray=None;self.points=None

    def anchor(self,frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        green=cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(27,51,52),(78,255,255))
        mask=255-cv2.dilate(green,np.ones((25,25),np.uint8))
        points=cv2.goodFeaturesToTrack(gray,240,.02,8,mask=mask)
        if points is None or len(points)<20:raise SafetyError('Insufficient static background features')
        self.gray=gray;self.points=points
        return dict(features=len(points),width=gray.shape[1],height=gray.shape[0])

    def compare(self,frame):
        if self.gray is None:return dict(valid=False,reason='no_anchor')
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        if gray.shape!=self.gray.shape:return dict(valid=False,reason='image_size_changed')
        moved,forward,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,None,winSize=(31,31),maxLevel=4)
        if moved is None:return dict(valid=False,reason='LK_failed')
        back,backward,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,moved,None,winSize=(31,31),maxLevel=4)
        if back is None:return dict(valid=False,reason='reverse_LK_failed')
        keep=forward.ravel().astype(bool)&backward.ravel().astype(bool)
        keep &= np.linalg.norm((back-self.points).reshape(-1,2),axis=1)<1
        a=self.points.reshape(-1,2)[keep];b=moved.reshape(-1,2)[keep]
        if len(a)<20:return dict(valid=False,reason='too_few_background_matches',matches=len(a))
        affine,inliers=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2)
        if affine is None:return dict(valid=False,reason='background_RANSAC_failed')
        good=inliers.ravel().astype(bool);ratio=float(good.mean())
        if good.sum()<20 or ratio<.65:return dict(valid=False,reason='background_incoherent',inlier_ratio=ratio)
        displacement=float(np.median(np.linalg.norm(b[good]-a[good],axis=1)))
        angle=math.degrees(math.atan2(affine[1,0],affine[0,0]))
        scale=float(math.hypot(affine[0,0],affine[1,0]))
        return dict(valid=True,median_shift_px=displacement,rotation_deg=angle,scale=scale,
                    inliers=int(good.sum()),inlier_ratio=ratio,
                    drift=bool(displacement>5 or abs(angle)>.75 or abs(scale-1)>.015))


class PhaseR:
    STATES=('UNINITIALIZED','READY','MOVING','SETTLING','RECALIBRATING','PAUSED','LOCKOUT')
    MAX_RECALIBRATIONS=2

    @staticmethod
    def valid_baseline(baseline):
        if not baseline.get('valid'):return False
        limit=baseline.get('std_limit_deg',1.5)
        if not 0<limit<=3.5:return False
        windows=baseline.get('windows',[])
        if len(windows)!=2:return False
        try:
            return all(w['window_ms']>=10000 and w['valid_ratio']>=.85 and w['confidence_median']>=.80
                and w['rms_px_median'] is not None and w['rms_px_median']<=5 and w['angle_std_deg']<=limit
                and abs(w['angle_drift_deg_per_s'])<=1 for w in windows)
        except (KeyError,TypeError):return False

    def __init__(self,path,emit,run_id,on_pause=None):
        self.path=Path(path);self.emit=emit;self.run_id=run_id;self.on_pause=on_pause
        self.lock=threading.RLock();self.background=BackgroundTracker()
        self.d=dict(state='UNINITIALIZED',calibration_version=None,calibration_valid=False,revision=0,
                    position=None,position_trusted=False,view_id=None,attempts=0,consecutive_anomalies=0,
                    plan=None,baseline=None,reason='No trusted current reference',last_incident=None)
        if self.path.exists():
            try:
                old=json.loads(self.path.read_text(encoding='utf-8'))
                if old['state'] not in self.STATES:raise ValueError('Bad recovery state')
                self.d.update(old)
                # A process restart never restores controller trust or a pixel
                # anchor. LOCKOUT and anomaly/attempt budgets survive intact.
                if self.d['state']!='LOCKOUT':self.d.update(state='PAUSED',position_trusted=False,calibration_valid=False,reason='New process needs fresh controller/visual evidence',plan=None)
            except Exception as exc:
                self.d.update(state='LOCKOUT',reason='Unreadable persisted recovery state: '+repr(exc))
        self._persist()

    def _persist(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        data=dict(self.d,schema_version='1.0',last_run_id=self.run_id,updated_monotonic_ms=time.monotonic_ns()/1e6)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(self.path)

    def _event(self,event,**details):
        self.emit(event,phase='R',calibration_version=self.d['calibration_version'],recovery_state=self.d['state'],**details)

    def pause(self,reason,incident_id=None):
        with self.lock:
            if self.d['state']=='LOCKOUT':return
            incident_id=incident_id or str(reason)
            if self.d['last_incident']==incident_id and self.d['state']=='PAUSED':return
            self.d['consecutive_anomalies']+=1
            state='LOCKOUT' if self.d['consecutive_anomalies']>=2 else 'PAUSED'
            self.d.update(state=state,reason=str(reason),last_incident=incident_id,position_trusted=False,calibration_valid=False)
            self._persist();self._event('lockout' if state=='LOCKOUT' else 'safety_pause',reason=str(reason),new_motion_prohibited=True,automatic_G28_or_G1=False)
            if self.on_pause:self.on_pause(str(reason))

    def confirm_manual_reference(self,view_id,evidence,frame,baseline,controller,clearance):
        """Explicit operator-position evidence, not just a motion authorization.

        Does not clear LOCKOUT. It also does not change any motor output.
        """
        with self.lock:
            if self.d['state']=='LOCKOUT':raise SafetyError('Persistent PhaseR LOCKOUT needs explicit manual reset/review')
            if view_id not in VIEWS or not evidence or not clearance:raise SafetyError('Explicit verified-view/operator clearance evidence required')
            if not controller.connected or not controller.position_trusted or controller.motion_state!='IDLE' or tuple(controller.position or ())!=tuple(VIEWS[view_id]):
                raise SafetyError('Controller/reference evidence is not trusted and idle')
            if not self.valid_baseline(baseline):raise SafetyError('Fresh manual reference baseline invalid')
            self.background.anchor(frame)
            self.d.update(view_id=view_id,position=list(VIEWS[view_id]),position_trusted=True,plan=None,attempts=0)
            self._commit(baseline,'operator_verified_reference',evidence)

    def _commit(self,baseline,cause,evidence=None):
        previous=self.d['calibration_version'];self.d['revision']+=1
        version='cal-'+str(self.d['revision'])+'-'+uuid.uuid4().hex[:10]
        self.d.update(state='READY',calibration_version=version,calibration_valid=True,baseline=baseline,
                      reason=None,consecutive_anomalies=0,last_incident=None,plan=None)
        self._persist()
        self._event('calibration_updated',previous_version=previous,new_version=version,cause=cause,evidence=evidence,baseline=baseline)
        self._event('comparisons_invalidated',previous_version=previous,new_version=version,require_new_E0_and_E1=True,old_samples_retained=True)

    def require_motion_allowed(self,kind='generic',origin=None,target=None):
        with self.lock:
            if self.d['state']=='READY' and self.d['position_trusted'] and self.d['calibration_valid']:return
            plan=self.d.get('plan')
            if self.d['state']=='MOVING' and kind=='observer' and plan and self.d['position_trusted']:
                step=plan['steps'][plan['step_index']]
                if np.allclose(origin,step['origin'],atol=1e-7,rtol=0) and np.allclose(target,step['target'],atol=1e-7,rtol=0):return
            raise SafetyError('PhaseR blocks motion: '+self.d['state']+'; '+str(self.d['reason']))

    def begin_verified_move(self,gate,destination,motion_id):
        with self.lock:
            self.require_motion_allowed()
            if destination not in VIEWS:raise SafetyError('Unknown viewpoint')
            edge=(self.d['view_id'],destination)
            if edge not in EDGES and edge[::-1] not in EDGES:raise SafetyError('Unverified view edge')
            start=np.array(self.d['position'],float);end=np.array(VIEWS[destination],float)
            n=max(1,int(math.ceil(np.linalg.norm(end-start)/5)))
            steps=[];origin=start.tolist()
            for i in range(1,n+1):
                target=(start+(end-start)*i/n).tolist()
                gate.observer_path(origin,target,edge,5)  # Original admission checks, no I/O.
                steps.append(dict(origin=origin,target=target));origin=target
            self.d.update(state='MOVING',calibration_valid=False,attempts=0,reason='Expected verified observer transaction',
                plan=dict(motion_id=motion_id,destination=destination,edge=list(edge),steps=steps,step_index=0,active_segment_id=None))
            self._persist();self._event('calibration_invalidated',cause='verified_view_move_started',old_version=self.d['calibration_version'])
            return steps

    def segment_started(self,motion_id,origin,target):
        with self.lock:
            self.require_motion_allowed('observer',origin,target)
            self.d['plan']['active_segment_id']=motion_id;self._persist()
            self._event('observer_segment_registered',motion_id=motion_id,origin=origin,target=target)

    def segment_arrived(self,controller,stationary):
        with self.lock:
            plan=self.d.get('plan')
            if self.d['state']!='MOVING' or not plan:raise SafetyError('No expected observer segment')
            if not plan.get('active_segment_id'):raise SafetyError('No registered segment start')
            if not controller.connected or not controller.position_trusted or controller.motion_state not in ('IDLE','WAIT_SETTLE') or not stationary:
                self.pause('Unexpected controller/settling evidence during legal move');raise SafetyError(self.d['reason'])
            step=plan['steps'][plan['step_index']]
            if tuple(controller.position or ())!=tuple(step['target']):
                self.pause('Observer target acknowledgement mismatch');raise SafetyError(self.d['reason'])
            self.d['position']=step['target'];plan['step_index']+=1
            plan['active_segment_id']=None
            if plan['step_index']==len(plan['steps']):
                self.d.update(state='SETTLING',view_id=plan['destination'],reason='Await stationary background and fresh baseline')
            self._persist()

    def observe(self,controller,background,camera_healthy=True,incident_id=None):
        with self.lock:
            if self.d['state']=='LOCKOUT':return self.d['state']
            if not camera_healthy:
                self.pause('Camera anomaly',incident_id or 'camera_anomaly');return self.d['state']
            if not controller.connected or not controller.position_trusted or controller.motion_state=='UNKNOWN':
                self.pause('Controller position/state untrusted',incident_id or 'controller_untrusted');return self.d['state']
            if self.d['state']=='PAUSED':return 'PAUSED'
            expected=self.d['state'] in ('MOVING','SETTLING','RECALIBRATING') and self.d.get('plan')
            if controller.motion_state=='MOVING' and not expected:
                self.pause('Unregistered controller movement',incident_id);return self.d['state']
            if controller.motion_state=='MOVING' and expected and controller.motion_id!=self.d['plan'].get('active_segment_id'):
                self.pause('Controller motion ID contradicts registered segment',incident_id);return self.d['state']
            if not background.get('valid'):
                self.pause('Static background unavailable: '+str(background.get('reason')),incident_id);return self.d['state']
            if background.get('drift') and not expected:
                self.pause('Uncommanded static-background displacement',incident_id);return self.d['state']
            if self.d['state']=='READY' and controller.motion_state!='IDLE':
                self.pause('Controller motion contradicts static reference',incident_id)
            return self.d['state']

    def attempt_recalibration(self,controller,stationary,frame,collect_baseline):
        """One measurement-only attempt; caller may retry at most once.

        Unsafe conditions never trigger a retry or an automatic recovery move.
        """
        before_stationary=stationary() if callable(stationary) else stationary
        with self.lock:
            if self.d['state'] not in ('SETTLING','RECALIBRATING') or not self.d.get('plan'):raise SafetyError('No legal arrival available for recalibration')
            if not controller.connected or not controller.position_trusted or controller.motion_state!='IDLE' or not before_stationary:
                self.pause('Untrusted/nonstationary recalibration request');return False
            if self.d['attempts']>=2:raise SafetyError('Automatic recalibration budget exhausted')
            self.d['attempts']+=1;self.d['state']='RECALIBRATING';self._persist();self._event('recalibration_attempt',attempt=self.d['attempts'],maximum=2)
        try:baseline=collect_baseline()
        except Exception as exc:baseline=dict(valid=False,invalid_reason=repr(exc))
        after_stationary=stationary() if callable(stationary) else stationary
        with self.lock:
            if self.d['state']!='RECALIBRATING':return False
            if not self.valid_baseline(baseline):
                self._event('recalibration_failed',attempt=self.d['attempts'],baseline=baseline)
                if self.d['attempts']>=2:
                    self.d.update(state='LOCKOUT',calibration_valid=False,position_trusted=False,reason='Two automatic recalibration attempts failed',consecutive_anomalies=max(2,self.d['consecutive_anomalies']))
                    self._persist();self._event('lockout',reason=self.d['reason'],automatic_G28_or_G1=False)
                    if self.on_pause:self.on_pause(self.d['reason'])
                return False
            if not after_stationary:
                self.pause('Background did not remain stationary through recalibration');return False
            self.background.anchor(frame() if callable(frame) else frame)
            self._commit(baseline,'verified_view_stationary_recalibration')
            return True

    def assert_comparable(self,*measurements):
        versions={m.get('calibration_version') for m in measurements}
        modes={m.get('measurement_mode') for m in measurements}
        views={m.get('camera_pose_id') for m in measurements}
        if not self.d['calibration_valid'] or len(versions)!=1 or None in versions or self.d['calibration_version'] not in versions or len(modes)!=1 or len(views)!=1:
            self._event('comparison_rejected',versions=list(versions),reason='Cross-version/view/method or invalidated baseline; remeasure E0/E1')
            raise SafetyError('Cannot compare errors across calibration versions/views/methods')

    def snapshot(self):
        with self.lock:return json.loads(json.dumps(self.d))
