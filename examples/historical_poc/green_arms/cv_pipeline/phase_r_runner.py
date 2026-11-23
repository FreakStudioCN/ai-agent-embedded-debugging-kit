"""Phase R integration above unchanged motor bounds and the existing CV/JSONL.

No automatic homing: an operator-confirmed current verified view is necessary.
Controller evidence is labelled host protocol lifecycle + manual reference,
because the current UART firmware exposes no verified position/status query.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import time
import cv2
import numpy as np

from cv_pipeline.experiment_phases import RevisedRunner
from cv_pipeline.phase_r import PhaseR,ControllerEvidence
from experiment_safety import SafetyError,VIEWS
from cv_pipeline.embodied_demo import PCUART,RobotArm,ROOT
from cv_pipeline.recovery_workflow import save


class PhaseRRunner(RevisedRunner):
    RECOVERY_CLASS=PhaseR
    def __init__(self,s,out,event,manual_view=None,manual_evidence=None):
        super().__init__(s,out,event)
        self.manual_view=manual_view;self.manual_evidence=manual_evidence
        self._position_trusted=False;self._observer_active=False;self._active_id=None
        self.r=self.RECOVERY_CLASS(ROOT/'.runtime/phase_r_state.json',event,out.name,self._pause_from_r)
        self.gate.recovery_guard=self.r
        self.cv.on_failure=lambda reason:self.r.pause(reason,'cv:'+reason)
        self.cv.background_callback=self._observe_background
        self.cv.calibration_provider=self.r.snapshot
        self.last_r_baseline=None

    def _state(self):
        snapshot=self.r.snapshot()
        return snapshot.get('legacy_state',snapshot['state'])

    def _fresh_baseline(self,label):
        return RevisedRunner.baseline(self,label)

    def _manual_clearance(self):
        return 'Current user explicitly confirmed S0->S1 clearance and current homed state'

    def _pause_from_r(self,reason):
        self._position_trusted=False;self.gate.pause(reason)

    def controller_evidence(self):
        try:
            connected=bool(self.uart and self.uart.serial.is_open and self.s.port.is_open)
            if connected:
                self.uart.any();self.s.port.in_waiting
            trusted=self._position_trusted and connected and not self.s.failed and not getattr(self.observer,'_fault',False)
        except Exception:connected=False;trusted=False
        return ControllerEvidence(connected,trusted,'MOVING' if self._observer_active else 'IDLE' if trusted else 'UNKNOWN',
            tuple(self.position) if self.position is not None else None,
            'operator-confirmed reference + host UART ACK/pending lifecycle + background; no encoder feedback',self._active_id)

    def _observe_background(self,frame,received,healthy):
        state=self._state()
        if state in ('UNINITIALIZED','PAUSED','LOCKOUT'):return
        with self.r.lock:background=self.r.background.compare(frame)
        self.r.observe(self.controller_evidence(),background,healthy)

    def current_frame(self):
        frame,_,received,_,error=self.cv.readers['wrist_8768'].latest()
        if frame is None or error or time.monotonic()-received>1:raise SafetyError('No fresh frame for PhaseR anchor')
        return cv2.cvtColor(np.asarray(frame),cv2.COLOR_RGB2BGR)

    def package(self,stats):
        return dict(valid=True,windows=[stats['wrist_8768'][str(a)] for a in (1,2)],std_limit_deg=self.std_limit,
                    camera_pose_id=self.view,measurement_mode='pnp_constrained_2d_projected',cv_version='cv-wrist-global-region-v2')

    def activate_after_keyframe_review(self):
        if self.manual_view not in VIEWS or not self.manual_evidence:
            self.r.pause('No explicit operator-confirmed current verified view','missing_manual_reference')
            raise SafetyError('PhaseR forbids automaticG28/G1 from unknown position')
        if self._state()=='LOCKOUT':raise SafetyError('Persistent PhaseR LOCKOUT requires manual review')
        # Nonmotion communication check. No G28 or enable is sent.
        self.uart=PCUART('COM3');self.observer=RobotArm(self.uart,timeout_ms=120000)
        self.observer_command('G4 S0')
        self.position=VIEWS[self.manual_view];self.view=self.manual_view;self.cv.camera_pose_id=self.view
        self._position_trusted=True
        stats=self._fresh_baseline('manual-reference-current-baseline')
        self.r.confirm_manual_reference(self.view,self.manual_evidence,self.current_frame(),self.package(stats),self.controller_evidence(),
            self._manual_clearance())
        result=super().activate_after_keyframe_review()
        self.observer_command('M17')
        self.event('phase_result',phase='R',status='MANUAL_REFERENCE_ESTABLISHED',state=self.r.snapshot())
        return result

    def home(self):
        # Called by legacy views(); PhaseR already needs a known starting view.
        self.r.require_motion_allowed()
        if self.position is None:raise SafetyError('Unknown position; automatic homing forbidden')

    def observer_command(self,command):
        if command=='G28':raise SafetyError('PhaseR never issues automatic G28')
        if command.startswith('G1 '):
            if self._state()!='MOVING':raise SafetyError('No registered verified observer transaction')
        elif command=='M17':self.r.require_motion_allowed()
        elif command!='G4 S0':raise SafetyError('Unsupported PhaseR observer command')
        return super().observer_command(command)

    def measure(self,*args,**kwargs):
        result=super().measure(*args,**kwargs)
        self.r.assert_comparable(*result['windows'])
        return result

    def camera_segment(self,target,label,edge,speed=5):
        self.spacing()
        if self.cv.failure:raise SafetyError(self.cv.failure)
        self.gate.observer_path(self.position,target,edge,speed)
        self.gate.begin(label,kind='observer',origin=self.position,target=target)
        self.r.segment_started(label,self.position,target)
        self.cv.camera_moving=True;self.cv.motion_id=label;self._observer_active=True;self._active_id=label
        self.event('camera_move_started',motion_id=label,origin=self.position,target=target,edge=edge,speed_mm_s=speed,
                   calibration_version=self.r.snapshot()['calibration_version'])
        command='G1 X%.6f Y%.6f Z%.6f F5'%tuple(target)
        self.observer_command(command);time.sleep(max(3,np.linalg.norm(np.subtract(target,self.position))/5+2))
        evidence=self.raw_camera_stationary(label)
        if self.gate.paused:raise SafetyError(self.gate.pause_reason)
        self.position=tuple(target);self._observer_active=False
        self.r.segment_arrived(self.controller_evidence(),True)
        self.cv.camera_pose_id=label;self.cv.reset_generation+=1;self.cv.camera_moving=False
        self.gate.finish(label,evidence)
        self.summary('motion_verified','原安全路径子段已由新鲜背景画面确认停稳。','Fresh background frames confirmed settling on the original safe path.',command=command,frame=evidence['evidence_path'])
        self.event('camera_move_completed',motion_id=label,target=target,evidence=evidence)

    def camera_to(self,name):
        if name==self.view:return
        steps=self.r.begin_verified_move(self.gate,name,'view-'+name)
        edge=(self.view,name)
        for i,step in enumerate(steps):self.camera_segment(step['target'],name+'-segment'+str(i+1),edge)
        self.view=name;self.cv.camera_pose_id=name
        self.last_r_baseline=None
        def collect():
            stats=self._fresh_baseline('R-'+name+'-attempt'+str(self.r.snapshot()['attempts']))
            self.last_r_baseline=stats
            return self.package(stats)
        def stationary():
            self.raw_camera_stationary('R-'+name+'-check');return True
        while self._state() in ('SETTLING','RECALIBRATING'):
            if self.r.attempt_recalibration(self.controller_evidence(),stationary,self.current_frame,collect):break
        if self._state()!='READY':raise SafetyError('PhaseR recalibration failed or locked out')
        self.last_r_version=self.r.snapshot()['calibration_version']
        save(self.out,'R-'+name+'-calibration.json',dict(state=self.r.snapshot(),statistics=self.last_r_baseline))

    def baseline(self,label):
        if self.last_r_baseline and self.r.snapshot()['calibration_version']==getattr(self,'last_r_version',None):
            # Reuse the same measured baseline, not a second hidden anchor update.
            save(self.out,label+'.json',dict(valid=True,statistics=self.last_r_baseline,calibration_version=self.last_r_version,
                baseline_alias=True,source='PhaseR verified-arrival baseline',std_limit_deg=self.std_limit))
            self.baseline_stats=self.last_r_baseline
            return self.last_r_baseline
        return RevisedRunner.baseline(self,label)

    def phase1(self):
        self.r.require_motion_allowed();result=super().phase1()
        self.r.assert_comparable(*result['samples'])
        result.update(calibration_version=self.r.snapshot()['calibration_version'],camera_pose_id=self.view,measurement_mode='pnp_constrained_2d_projected')
        save(self.out,'local_pwm_response.json',result);return result

    def repeated(self,*args,**kwargs):
        if self.local_model:self.r.assert_comparable(self.local_model)
        result=super().repeated(*args,**kwargs);self.r.assert_comparable(*result['samples'])
        result['calibration_version']=self.r.snapshot()['calibration_version'];return result

    def phase2(self):
        self.r.assert_comparable(self.local_model)
        result=super().phase2();result.update(calibration_version=self.r.snapshot()['calibration_version'],camera_pose_id=self.view,measurement_mode='pnp_constrained_2d_projected')
        save(self.out,'backlash_trials.json',result);return result

    def phase3(self):
        self.r.assert_comparable(self.backlash,self.local_model)
        return super().phase3()
