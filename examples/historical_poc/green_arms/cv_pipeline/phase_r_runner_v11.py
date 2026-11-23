"""Strict v1.1 orchestration, opt-in current-session human authorization.

Does not call legacy prepare(), which contains an obsolete recorded grant.
Legacy hardware limits, executor and approved-path checks are reused intact.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import time
from serial.tools import list_ports
from cv_pipeline.phase_r_v11 import PhaseRV11,strict_noise_limit
from cv_pipeline.phase_r_runner import PhaseRRunner
from experiment_safety import SafeExecutor,SafetyError
from cv_pipeline.experiment_runner import validate_cv_adapter
from cv_pipeline.recovery_workflow import registers,snapshots,save
from cv_pipeline.vision_lk import tracker_class


class PhaseRRunnerV11(PhaseRRunner):
    RECOVERY_CLASS=PhaseRV11

    def __init__(self,*args,authorization=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.authorization=authorization
        self.cv.tracker_factory=tracker_class;self.cv.cv_version='cv-lk-subpixel-v11'
        # Route this run's dedicated recovery files separately from root state.
        self.r.recovery_dir=self.out/'recovery';self.r.recovery_dir.mkdir(exist_ok=True)
        for name in ('drift_events.jsonl','recovery_attempts.jsonl'):(self.r.recovery_dir/name).touch(exist_ok=True)
        self.r._artifacts()

    def prepare(self):
        validate_cv_adapter(self.cv)
        grant=self.authorization or {}
        if not all(grant.get(k) for k in ('operator_confirmation','cause_resolved','clearance','current_view_evidence')):
            raise SafetyError('Fresh explicit S0->S1, cause-resolved and physical reference confirmation required')
        ports={p.device:p for p in list_ports.comports()}
        if not ports.get('COM8') or ports['COM8'].serial_number.lower()!='70:af:09:2a:ee:e8':raise SafetyError('COM8 identity mismatch')
        if not ports.get('COM3') or ports['COM3'].vid!=0x1a86 or ports['COM3'].pid!=0x7523:raise SafetyError('COM3 identity mismatch')
        uid=self.s.rpc("__import__('machine').unique_id().hex()")
        state=self.s.rpc('d.status()');pca=registers(self.s);SafeExecutor.check_hardware(uid,pca,state)
        self.r.authorize_manual_recovery(**grant)
        self.gate.authorize(self.out.name,grant['operator_confirmation']);self.authorized=True
        self.event('human_clearance_granted',operator_confirmation=grant,protocol='1.1',scope='Current session only')
        save(self.out,'safety_gate.json',dict(stage='S1_PREPARE',motion_allowed=False,operator_confirmation=grant))
        self.cv.start()
        self._await_initial_frames()
        self.r.collect_background(self.background_sample)
        stats=self._fresh_baseline('initial-baseline')
        photos=snapshots(self.out,'pre-motion-clearance',self.event)
        self.ex=SafeExecutor(self.gate,self.rpc,self.event,self.counts)
        save(self.out,'preflight.json',dict(uid=uid,pca=pca,state=state,baseline=stats,frames=photos,protocol='1.1',operator_confirmation=grant))
        return dict(statistics=stats,frames=photos,std_limit_deg=self.std_limit)

    def _manual_clearance(self):
        return self.authorization['clearance']

    def package(self,stats):
        result=super().package(stats);result['cv_version']=self.cv.cv_version
        return result

    def background_sample(self):
        frame,_,received,_,error=self.cv.readers['wrist_8768'].latest()
        if error or frame is None or time.monotonic()-received>1:raise SafetyError('Camera anomaly during static background validation')
        return self.current_frame(),received

    def _await_initial_frames(self):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if self.cv.failure:raise SafetyError(self.cv.failure)
            ready=True
            for reader in self.cv.readers.values():
                frame,_,received,_,error=reader.latest()
                ready &= frame is not None and not error and time.monotonic()-received<=1
            if ready:return
            time.sleep(.02)
        raise SafetyError('No fresh initial camera frames within3s')

    def _fresh_baseline(self,label):
        start=time.monotonic()
        while time.monotonic()-start<11:
            if self.cv.failure or self.gate.paused:raise SafetyError(self.cv.failure or self.gate.pause_reason)
            time.sleep(.1)
        stats=self.cv.stats(start);primary=stats['wrist_8768']
        result=dict(valid=False,statistics=stats,std_limit_deg=1.5,protocol='1.1',view=self.view)
        try:
            self.std_limit=max(strict_noise_limit(primary[str(a)]['angle_std_deg']) for a in (1,2))
            self.cv.std_limit=self.std_limit;stats=self.cv.stats(start);result['statistics']=stats
            if not all(stats['wrist_8768'][str(a)]['stationary'] and stats['wrist_8768'][str(a)]['window_ms']>=10000 for a in (1,2)) or not self.cv.global_ready():
                raise SafetyError('v1.1 static baseline validity/Q/RMS/drift fails')
            result.update(valid=True,std_limit_deg=self.std_limit);self.baseline_stats=stats
            return stats
        finally:save(self.out,label+'.json',result)

    def baseline(self,label):
        if self.last_r_baseline and self.r.snapshot()['calibration_version']==getattr(self,'last_r_version',None):return super().baseline(label)
        return self._fresh_baseline(label)

    def camera_to(self,name):
        if name==self.view:return
        # A third legal recovery trigger inside60s is prohibited, not bypassed.
        # Wait in NORMAL with monitoring enabled before requesting another move.
        triggers=self.r.d['recovery_triggers']
        while len([t for t in triggers if time.monotonic()-t<=60])>=2:
            self.r.require_motion_allowed()
            if self.cv.failure:raise SafetyError(self.cv.failure)
            time.sleep(.1)
        steps=self.r.begin_verified_route(self.gate,name,'view-'+name)
        for i,step in enumerate(steps):self.camera_segment(step['target'],name+'-segment'+str(i+1),tuple(step['edge']))
        self.view=name;self.cv.camera_pose_id=name;self.last_r_baseline=None
        def collect():
            self.last_r_baseline=self._fresh_baseline('R-'+name+'-attempt'+str(self.r.d['attempts']))
            return self.package(self.last_r_baseline)
        def stationary():self.raw_camera_stationary('R-'+name+'-check');return True
        while self._state() in ('SETTLING','RECALIBRATING'):
            if self.r.attempt_recalibration(self.controller_evidence(),stationary,self.current_frame,collect,
                lambda deadline:self.r.collect_background(self.background_sample,deadline=deadline)):break
        if self._state()!='READY':raise SafetyError('PhaseR v1.1 Rebase paused/locked out')
        self.last_r_version=self.r.d['calibration_version']
        save(self.out,'R-'+name+'-calibration.json',dict(state=self.r.snapshot(),statistics=self.last_r_baseline))

    def views(self):
        self.r.require_motion_allowed()
        # Compare two protocol-compliant views. A is a safe path waypoint but
        # historical data show poor Q there; do not choose it as the first
        # measurement destination merely because the legacy survey did so.
        candidates=[self.view,'B-small' if self.view!='B-small' else 'C-small'];results=[]
        for name in candidates:
            if self.view!=name:self.camera_to(name)
            stats=self.baseline('view-'+name);w=stats['wrist_8768']
            score=min(w[a]['valid_ratio']*w[a]['confidence_median']/(1+w[a]['angle_std_deg']) for a in ('1','2'))
            results.append(dict(view_id=name,target_mm=__import__('experiment_safety').VIEWS[name],score=score,statistics=stats))
        winner=max(results,key=lambda x:x['score'])['view_id']
        if self.view!=winner:self.camera_to(winner)
        self.selected_baseline=self.baseline('locked-view-baseline');self.noise=self.selected_baseline['wrist_8768']['2']['angle_std_deg']
        save(self.out,'camera_view_comparison.json',dict(views=results,selected=winner,view_locked=True,
            selection='Worst-arm valid_ratio*Q/(1+sigma), with all strict gates retained; HOME/current vs B-small; A transit only due prior low Q'))
        save(self.out,'baseline.json',dict(valid=True,view_id=winner,statistics=self.selected_baseline,std_limit_deg=self.std_limit,cv_version=self.cv.cv_version))
        self.event('camera_view_selected',selected=winner,comparison=results,locked_through_phase3=True)
        self.phase_results['0.5']='PASS';return dict(views=results,selected=winner,baseline_noise_deg=self.noise)

    def _observe_background(self,frame,received,healthy):
        if self._state() in ('UNINITIALIZED','LOCKOUT'):return
        if not self._position_trusted and (self._state()!='PAUSED' or self.r.background.gray is None):return
        # Continue drift diagnostics while paused; it never restores authority.
        with self.r.lock:background=self.r.background.compare(frame)
        self.r.observe(self.controller_evidence(),background,healthy)
