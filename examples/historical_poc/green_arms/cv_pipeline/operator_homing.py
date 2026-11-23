"""Explicit operator-requested normal G28, separate from automatic Phase R.

Reuses RevisedRunner.home and the original per-connection ExperimentGate.
Never called on faults, reconnect, retries or ordinary activate. The current
operator must explicitly request homing and clear the path before this method.
It establishes a nominal reference, not encoder-verified absolute position.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import time
from serial.tools import list_ports
from experiment_safety import ExperimentGate,SafeExecutor,SafetyError,VIEWS
from cv_pipeline.experiment_phases import RevisedRunner
from cv_pipeline.phase_r_runner_v11 import PhaseRRunnerV11
from cv_pipeline.recovery_workflow import registers,snapshots,save


class OperatorHomingRunner(PhaseRRunnerV11):
    def __init__(self,*args,home_confirmation=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.home_confirmation=home_confirmation;self._manual_homing=False;self._home_prepared=False;self._home_completed=False

    def prepare_homing(self):
        grant=self.authorization or {}
        if not self.home_confirmation or not all(grant.get(k) for k in ('operator_confirmation','cause_resolved','clearance','current_view_evidence')):
            raise SafetyError('Explicit current-session operator homing/clearance/review required')
        ports={p.device:p for p in list_ports.comports()}
        if not ports.get('COM3') or (ports['COM3'].vid,ports['COM3'].pid)!=(0x1a86,0x7523):raise SafetyError('COM3 identity mismatch')
        if not ports.get('COM8') or ports['COM8'].serial_number.lower()!='70:af:09:2a:ee:e8':raise SafetyError('COM8 identity mismatch')
        uid=self.s.rpc("__import__('machine').unique_id().hex()");pca=registers(self.s);state=self.s.rpc('d.status()')
        SafeExecutor.check_hardware(uid,pca,state)
        self.r.authorize_manual_recovery(**grant)
        self.event('human_clearance_granted',operator_confirmation=grant,homing_confirmation=self.home_confirmation,
            scope='Explicit normal homing to establish reference; then original verified-view experiment',automatic_recovery_homing=False)
        self.gate.authorize(self.out.name,grant['operator_confirmation']);self.authorized=True
        self.cv.start();start=time.monotonic()
        while time.monotonic()-start<3:
            if self.cv.failure:raise SafetyError(self.cv.failure)
            time.sleep(.1)
        if not self.cv.global_ready():raise SafetyError('Global visibility unavailable before explicit homing')
        photos=snapshots(self.out,'explicit-homing-clearance',self.event)
        self._home_prepared=True
        save(self.out,'preflight.json',dict(uid=uid,pca=pca,state=state,frames=photos,operator_grant=grant,
            home_confirmation=self.home_confirmation,controller_position_trusted=False,protocol='1.1',cv_version=self.cv.cv_version))
        return dict(frames=photos,position='UNKNOWN until explicit homing and fresh settling',motion_sent=False)

    def operator_home(self):
        if not self._home_prepared or not self.home_confirmation or self.gate.paused or not self.r.d['s1_authorized']:
            raise SafetyError('No admitted explicit homing request')
        original_gate=self.gate;homing_gate=ExperimentGate(self.out.name+'-operator-home')
        homing_gate.authorize(homing_gate.connection_id,self.home_confirmation)
        self.gate=homing_gate;self._manual_homing=True
        try:
            self.event('manual_reference_establishment_started',command='G28',operator_confirmation=self.home_confirmation,
                source='Explicit operator command; original RevisedRunner.home',automatic_recovery=False)
            # Original approved normal homing program, not a Phase R callback.
            RevisedRunner.home(self)
            if self.cv.failure or self.gate.paused or not self.r.d['s1_authorized']:raise SafetyError('Fault during explicit homing')
            self._home_completed=True;self._position_trusted=True
            self.event('manual_reference_establishment_completed',nominal_position=VIEWS['HOME'],independent_encoder_feedback=False)
        except BaseException as exc:
            self.r.pause('Explicit homing interrupted: '+str(exc));original_gate.pause(exc);raise
        finally:self._manual_homing=False;self.gate=original_gate
        # New camera reference must pass the same strict baseline, no bypass.
        self.r.collect_background(self.background_sample)
        stats=self._fresh_baseline('post-homing-baseline')
        self.r.confirm_manual_reference('HOME','Operator-requested G28 ACK + original10s wait + fresh background settling; nominal reference only',
            self.current_frame(),self.package(stats),self.controller_evidence(),self.authorization['clearance'])
        self.last_r_baseline=stats;self.last_r_version=self.r.d['calibration_version']
        self.ex=SafeExecutor(self.gate,self.rpc,self.event,self.counts)
        save(self.out,'baseline.json',dict(valid=True,statistics=stats,calibration_version=self.last_r_version,cv_version=self.cv.cv_version))
        return dict(home_completed=True,nominal_position=self.position,baseline=stats,recovery=self.r.snapshot())

    def observer_command(self,command):
        if self._manual_homing:
            if command not in ('G4 S0','M17','G28'):raise SafetyError('Explicit homing scope forbids other commands')
            if self.gate.paused or not self.gate.authorized or self.cv.failure or not self.r.d['s1_authorized']:
                raise SafetyError('Explicit homing admission closed')
            return RevisedRunner.observer_command(self,command)
        return super().observer_command(command)

    def activate_homed(self):
        if not self._home_completed:raise SafetyError('Explicit homing has not completed')
        self.r.require_motion_allowed()
        return RevisedRunner.activate_after_keyframe_review(self)
