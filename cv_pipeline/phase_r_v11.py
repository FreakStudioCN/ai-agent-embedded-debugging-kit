"""v1.1 recovery admission layer; legacy motor safety and bounds are unchanged.

Internal legacy state names permit reuse of the verified-path transaction code.
Persisted/public state and recovery events use the v1.1 state vocabulary.
No motor transport is available to this class. Timed workers are read-only.
"""
from datetime import datetime,timezone
from pathlib import Path
import json
import math
import queue
import threading
import time
import uuid
import numpy as np
from cv_pipeline.phase_r import PhaseR
from cv_pipeline.phase_r_background import StaticBackground
from experiment_safety import SafetyError,VIEWS,EDGES

NAMES=dict(UNINITIALIZED='PAUSED',READY='NORMAL',MOVING='EXPECTED_MOVE',SETTLING='SETTLING',
    REBASE_PENDING='REBASE_PENDING',RECALIBRATING='REBASE_VALIDATING',PAUSED='PAUSED',LOCKOUT='RECOVERY_LOCKOUT')


def strict_noise_limit(sigma):
    if not isinstance(sigma,(float,int)) or not math.isfinite(sigma) or sigma<0:raise SafetyError('Invalid noise estimate')
    requested=max(1.,3*sigma)
    if requested>1.5:raise SafetyError('Visual noise insufficient: 3*sigma exceeds immutable v1.1 cap1.5deg')
    return requested


class PhaseRV11(PhaseR):
    def __init__(self,path,emit,run_id,on_pause=None,recovery_dir=None,clock=time.monotonic):
        self.path=Path(path);self.emit=emit;self.run_id=run_id;self.on_pause=on_pause;self.clock=clock
        self.lock=threading.RLock();self.background=StaticBackground();self._worker=None
        self._suspect_since=None;self._confirm_since=None;self._drift_episode=False;self._confirmed=False
        self.recovery_dir=Path(recovery_dir) if recovery_dir else self.path.parent/'recovery'
        self.recovery_dir.mkdir(parents=True,exist_ok=True)
        self.d=dict(state='UNINITIALIZED',calibration_version=None,calibration_valid=False,revision=0,
            position=None,position_trusted=False,view_id=None,attempts=0,consecutive_anomalies=0,
            plan=None,baseline=None,reason='Fresh S0/S1 and physical reference required',last_incident=None,
            s1_authorized=False,authorization=None,attempt_id=None,recovery_triggers=[],version_history=[],
            background_reference=None,attempt_started=None)
        if self.path.exists():
            try:
                old=json.loads(self.path.read_text(encoding='utf-8'))
                if old['state'] in NAMES:state=old['state']
                else:state={v:k for k,v in NAMES.items()}[old['state']]
                self.d.update(old);self.d['state']=state
                if state!='LOCKOUT':self.d.update(state='PAUSED',reason='Restart requires new S0/S1 and reference',plan=None)
                self.d.update(position_trusted=False,calibration_valid=False,s1_authorized=False)
                # Reboot/clock regression cannot replenish a rolling budget.
                if self.d['recovery_triggers'] and clock()<max(self.d['recovery_triggers']):
                    self.d.update(state='LOCKOUT',reason='Monotonic clock regressed; operator review required')
            except Exception as exc:self.d.update(state='LOCKOUT',reason='Persisted state unreadable: '+repr(exc))
        if self.path.with_suffix('.lockout').exists():self.d.update(state='LOCKOUT',reason='Persistence fault marker requires manual review')
        self._persist()
        for name in ('drift_events.jsonl','recovery_attempts.jsonl'):(self.recovery_dir/name).touch(exist_ok=True)
        self._artifacts()

    def snapshot(self):
        with self.lock:
            result=json.loads(json.dumps(self.d));result['legacy_state']=result['state']
            result['state']=NAMES[result['state']];result['recovery_state']=result['state']
            result['controller_position_trusted']=result['position_trusted']
            return result

    def _persist(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        value=self.snapshot();value.update(schema_version='1.1',last_run_id=self.run_id,updated_monotonic_ms=self.clock()*1000)
        try:
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');temp.replace(self.path)
        except Exception as exc:
            self._close('Recovery persistence failed')
            self.d.update(state='LOCKOUT',reason='Recovery persistence failed: '+repr(exc))
            try:self.path.with_suffix('.lockout').write_text(self.d['reason'],encoding='utf-8')
            except OSError:pass  # Admission stays closed even if the disk is unwritable.
            raise SafetyError(self.d['reason']) from exc

    def _artifacts(self):
        for name,value in [('calibration_versions.json',self.d['version_history']),('background_reference.json',self.d['background_reference'])]:
            (self.recovery_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (self.recovery_dir/'recovery_summary.md').write_text(
            '# Phase R v1.1\n\nState: '+NAMES[self.d['state']]+'\n\nReason: '+str(self.d['reason'])+
            '\n\nAttempts: '+str(self.d['attempts'])+'; S1: '+str(self.d['s1_authorized'])+
            '\n\nImage-plane evidence is not physical position feedback. No automatic motor recovery.\n',encoding='utf-8')

    def _event(self,event,**details):
        aliases=dict(calibration_invalidated='experiment_baseline_invalidated',comparisons_invalidated='experiment_baseline_invalidated',
            lockout='recovery_lockout',recalibration_attempt='visual_rebase_started',recalibration_failed='visual_rebase_failed')
        event=aliases.get(event,event)
        fields=dict(phase='R',calibration_version=self.d['calibration_version'],recovery_state=NAMES[self.d['state']],
            attempt_id=self.d['attempt_id'],evidence={},controller_position_trusted=self.d['position_trusted'])
        fields.update(details);self.emit(event,**fields)
        row=dict(schema_version='1.1',run_id=self.run_id,timestamp_utc=datetime.now(timezone.utc).isoformat(),
            monotonic_ms=self.clock()*1000,event=event,motion_id=fields.get('motion_id'),details=fields)
        name='drift_events.jsonl' if event.startswith('observer_drift') or event=='DRIFT_UNKNOWN' else 'recovery_attempts.jsonl'
        with (self.recovery_dir/name).open('a',encoding='utf-8') as file:file.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        self._artifacts()

    def _transition(self,state,reason):
        old=NAMES[self.d['state']];self.d.update(state=state,reason=reason);self._persist()
        self._event('recovery_state_changed',previous_state=old,new_state=NAMES[state],reason=reason)

    def _close(self,reason):
        # Atomic admission closure is first; callback must only close the gate.
        self.d.update(s1_authorized=False,calibration_valid=False,position_trusted=False)
        if self.on_pause:self.on_pause(str(reason))

    def _trigger(self,reason):
        now=self.clock();self.d['recovery_triggers']=[t for t in self.d['recovery_triggers'] if now-t<=60]+[now]
        if len(self.d['recovery_triggers'])>=3:
            self._close(reason);self._transition('LOCKOUT','Three recovery triggers in rolling60s: '+reason)
            self._event('recovery_lockout',reason=self.d['reason'],evidence=dict(triggers=self.d['recovery_triggers']))
            return False
        self._persist();self._event('recovery_started',reason=reason,rolling60_count=len(self.d['recovery_triggers']))
        return True

    def pause(self,reason,incident_id=None):
        with self.lock:
            if self.d['state']=='LOCKOUT':return
            repeated=self.d['state']=='PAUSED' and self.d['last_incident']==(incident_id or str(reason))
            self._close(reason)
            if not repeated and not self._trigger(str(reason)):return
            self.d['last_incident']=incident_id or str(reason)
            self._transition('PAUSED',str(reason));self._event('safety_pause',reason=str(reason),new_motion_prohibited=True,automatic_motion_allowed=False)

    def report_repeated_fault(self,reason):
        """Explicit new dropout/drift episode; polling the same episode is not one."""
        self.pause(reason,'episode-'+uuid.uuid4().hex)

    @staticmethod
    def valid_baseline(baseline):
        if baseline.get('std_limit_deg',1.5)>1.5:return False
        return PhaseR.valid_baseline(baseline)

    def require_motion_allowed(self,*args,**kwargs):
        if not self.d['s1_authorized']:raise SafetyError('Current-session S1 authorization absent')
        return super().require_motion_allowed(*args,**kwargs)

    def authorize_manual_recovery(self,operator_confirmation,cause_resolved,clearance,current_view_evidence):
        """Call only with a new explicit operator grant; does NOT establish position."""
        with self.lock:
            if not all((operator_confirmation,cause_resolved,clearance,current_view_evidence)):
                raise SafetyError('Explicit cause-resolved, clearance, newS1 and physical-reference evidence required')
            prior_budget=dict(triggers=self.d['recovery_triggers'][:],attempts=self.d['attempts'],reason=self.d['reason'],run_id=self.run_id)
            self.d.update(s1_authorized=True,authorization=dict(operator_confirmation=operator_confirmation,
                cause_resolved=cause_resolved,clearance=clearance,current_view_evidence=current_view_evidence),
                attempts=0,attempt_id=None,plan=None,last_incident=None)
            # Manual review establishes a new recovery epoch; preserve old budgets as audit history.
            self.d.setdefault('reviewed_epochs',[]).append(prior_budget)
            self.d['recovery_triggers']=[]
            marker=self.path.with_suffix('.lockout')
            if marker.exists():marker.replace(marker.with_name(marker.name+'.reviewed-'+uuid.uuid4().hex[:8]))
            self._transition('PAUSED','Operator authorized review; fresh physical/visual validation pending')
            self._event('recovery_authorized',evidence=self.d['authorization'],automatic_motion_allowed=False)

    def confirm_manual_reference(self,*args,**kwargs):
        if not self.d['s1_authorized']:raise SafetyError('New explicit S1 required')
        if not self.d.get('background_reference') or self.d['background_reference'].get('window_s',0)<3:
            raise SafetyError('Fresh >=3s background validation required')
        return super().confirm_manual_reference(*args,**kwargs)

    def _commit(self,baseline,cause,evidence=None):
        if not self.d['s1_authorized'] or not self.d['position_trusted']:raise SafetyError('Commit cannot restore lost authority/trust')
        previous=self.d['calibration_version'];self.d['revision']+=1
        version='cal-v11-'+str(self.d['revision'])+'-'+uuid.uuid4().hex[:8]
        self.d.update(calibration_version=version,calibration_valid=True,baseline=baseline,plan=None)
        self.d['version_history'].append(dict(previous_version=previous,new_version=version,camera_pose_id=self.d['view_id'],
            cause=cause,old_error_comparisons_invalid=True,require_new_E0_and_E1=True))
        self._persist();self._event('experiment_baseline_invalidated',previous_version=previous,new_version=version,require_new_E0_and_E1=True)
        self._transition('READY',None)
        self._event('visual_rebase_completed',cause=cause,evidence=evidence or {},baseline=baseline)
        self._event('experiment_resumed',evidence=dict(situation='A' if cause!='operator_verified_reference' else 'operator_validated',authorization=self.d['authorization']))

    def begin_verified_move(self,*args,**kwargs):
        with self.lock:
            self.require_motion_allowed()
            # Gate validates before counting/transition; base method performs original path validation.
            result=super().begin_verified_move(*args,**kwargs)
            self._event('recovery_state_changed',previous_state='NORMAL',new_state='EXPECTED_MOVE',evidence=self.d['plan'])
            if not self._trigger('legal viewpoint change'):
                raise SafetyError('Rolling recovery budget locked out before any motion')
            return result

    def begin_verified_route(self,gate,destination,motion_id):
        """One registered macro over existing edges; no new straight-line path.

        Intermediate stops retain segment completion checks. Rebase occurs only
        at the registered final destination. Every segment uses the old gate.
        """
        with self.lock:
            self.require_motion_allowed()
            start=self.d['view_id'];pending=[(start,[start])];seen={start};route=None
            while pending:
                node,path=pending.pop(0)
                if node==destination:route=path;break
                for a,b in EDGES:
                    neighbour=b if a==node else a if b==node else None
                    if neighbour is not None and neighbour not in seen:
                        seen.add(neighbour);pending.append((neighbour,path+[neighbour]))
            if not route or len(route)<2:raise SafetyError('No existing verified route to requested view')
            steps=[]
            for a,b in zip(route,route[1:]):
                origin=np.array(VIEWS[a],float);end=np.array(VIEWS[b],float)
                n=max(1,math.ceil(np.linalg.norm(end-origin)/5));previous=origin.tolist()
                for i in range(1,n+1):
                    target=(origin+(end-origin)*i/n).tolist();gate.observer_path(previous,target,(a,b),5)
                    steps.append(dict(origin=previous,target=target,edge=[a,b]));previous=target
            self.d.update(state='MOVING',calibration_valid=False,attempts=0,reason='Expected registered route over original verified edges',
                plan=dict(motion_id=motion_id,destination=destination,route=route,steps=steps,step_index=0,active_segment_id=None))
            self._persist();self._event('experiment_baseline_invalidated',cause='verified_route_started',require_new_E0_and_E1=True)
            self._event('recovery_state_changed',previous_state='NORMAL',new_state='EXPECTED_MOVE',evidence=self.d['plan'])
            if not self._trigger('legal final-view change via original edges'):raise SafetyError('Rolling recovery budget exhausted before motion')
            return steps

    def segment_arrived(self,*args,**kwargs):
        previous=NAMES[self.d['state']]
        result=super().segment_arrived(*args,**kwargs)
        if previous!=NAMES[self.d['state']]:
            self._event('recovery_state_changed',previous_state=previous,new_state=NAMES[self.d['state']],evidence=self.d.get('plan'))
        return result

    def observe(self,controller,background,camera_healthy=True,incident_id=None,now=None):
        now=self.clock() if now is None else now
        with self.lock:
            if self.d['state']=='LOCKOUT':return 'RECOVERY_LOCKOUT'
            expected=self.d['state'] in ('MOVING','SETTLING','REBASE_PENDING','RECALIBRATING') and bool(self.d.get('plan'))
            if not camera_healthy:self.pause('Camera anomaly',incident_id or 'camera_anomaly');return NAMES[self.d['state']]
            if not controller.connected or not controller.position_trusted or controller.motion_state=='UNKNOWN':
                if self.d['state']!='PAUSED':
                    self.pause('Controller position/state untrusted',incident_id or 'controller_untrusted');return NAMES[self.d['state']]
            if controller.motion_state=='MOVING' and (not expected or controller.motion_id!=self.d['plan'].get('active_segment_id')):
                self.pause('Unregistered or conflicting controller lifecycle',incident_id);return NAMES[self.d['state']]
            if expected and controller.motion_state=='MOVING':return NAMES[self.d['state']]
            if not background.get('valid'):
                self._event('DRIFT_UNKNOWN',evidence=background,motion_id=controller.motion_id)
                self.pause('DRIFT_UNKNOWN: '+str(background.get('reason')),incident_id);return NAMES[self.d['state']]
            if expected:return NAMES[self.d['state']]
            sigma=background.get('sigma_background_px',self.background.sigma)
            suspect=max(5.,3*sigma);confirm=max(12.,6*sigma)
            shift=max(background.get('drift_px',background.get('median_shift_px',0)),background.get('region_max_displacement_px',0))
            self._suspect_since=(now if self._suspect_since is None else self._suspect_since) if shift>suspect else None
            self._confirm_since=(now if self._confirm_since is None else self._confirm_since) if shift>confirm else None
            evidence=dict(background,drift_px=shift,suspected_threshold_px=suspect,confirmed_threshold_px=confirm,
                motion_id=controller.motion_id,controller_position_trusted=controller.position_trusted)
            if self._suspect_since is not None and now-self._suspect_since>=.5 and not self._drift_episode:
                self._drift_episode=True;evidence['duration_ms']=(now-self._suspect_since)*1000
                self._close('Suspected uncommanded drift')
                self._event('observer_drift_suspected',evidence=evidence)
                self.pause('Uncommanded static-background displacement','drift-episode')
            if self._confirm_since is not None and now-self._confirm_since>=1 and not self._confirmed:
                self._confirmed=True;evidence['duration_ms']=(now-self._confirm_since)*1000
                self._event('observer_drift_confirmed',evidence=evidence)
            if shift<=suspect:self._drift_episode=False;self._confirmed=False
            return NAMES[self.d['state']]

    def collect_background(self,sample,seconds=3.,deadline=None):
        """sample -> (BGR, monotonic received timestamp); rejects stale/duplicate/gap."""
        start=self.clock();deadline=min(deadline or start+30,start+30);values=[0.]
        frame,stamp=sample()
        if self.clock()-stamp>1:raise SafetyError('Stale initial background frame')
        with self.lock:self.background.anchor(frame)
        previous=stamp;timestamps=[stamp]
        while timestamps[-1]-timestamps[0]<seconds or len(values)<10:
            if self.clock()>=deadline:raise SafetyError('Background validation deadline exceeded')
            time.sleep(.05);frame,stamp=sample()
            if stamp==previous:continue
            if stamp<previous or stamp-previous>1 or self.clock()-stamp>1:raise SafetyError('Camera timestamp discontinuity')
            previous=stamp
            with self.lock:row=self.background.compare(frame)
            if not row['valid'] or row['region_max_displacement_px']>5:raise SafetyError('Fresh background not stable/distributed')
            values.append(row['drift_px']);timestamps.append(stamp)
        self.background.sigma=float(np.std(values,ddof=1))
        self.d['background_reference']=dict(self.background.metadata,window_s=timestamps[-1]-timestamps[0],wall_duration_s=self.clock()-start,
            first_timestamp=timestamps[0],last_timestamp=timestamps[-1],sigma_background_px=self.background.sigma)
        self._persist();return self.d['background_reference']

    def attempt_recalibration(self,controller,stationary,frame,collect_baseline,collect_background=None):
        with self.lock:
            if self.d['state'] not in ('SETTLING','RECALIBRATING') or not self.d.get('plan'):raise SafetyError('No legal arrival')
            if not self.d['s1_authorized'] or not controller.connected or not controller.position_trusted or controller.motion_state!='IDLE':
                self.pause('Rebase physical/authorization evidence untrusted');return False
            if self._worker and self._worker.is_alive():raise SafetyError('Only one rebase worker permitted')
            if self.d['attempts']>=2:raise SafetyError('Rebase budget exhausted')
            self.d['attempts']+=1;self.d['attempt_id']='recovery-'+uuid.uuid4().hex
            self.d['attempt_started']=self.clock();attempt=self.d['attempt_id'];deadline=self.clock()+30
            self._transition('REBASE_PENDING','Await fresh 3s background');self._event('visual_rebase_started',maximum_attempts=2,deadline_monotonic=deadline)
        result=queue.Queue(maxsize=1)
        def work():
            try:
                if not (stationary() if callable(stationary) else stationary):raise SafetyError('Not stationary')
                if collect_background is None:raise SafetyError('Fresh >=3s background collector required')
                bg=collect_background(deadline)
                if not bg or bg.get('window_s',0)<3:raise SafetyError('Background validation shorter than3s')
                with self.lock:
                    if self.d['attempt_id']!=attempt or self.d['state']!='REBASE_PENDING':return
                    self._transition('RECALIBRATING','Collect >=10s angle baseline')
                baseline=collect_baseline()
                if not (stationary() if callable(stationary) else stationary):raise SafetyError('Baseline background moved')
                result.put((baseline,None))
            except Exception as exc:result.put((None,repr(exc)))
        self._worker=threading.Thread(target=work,daemon=True);self._worker.start()
        self._worker.join(max(0,deadline-self.clock()))
        timed_out=self._worker.is_alive() or self.clock()>deadline
        with self.lock:
            if self.d['state'] not in ('REBASE_PENDING','RECALIBRATING') or self.d['attempt_id']!=attempt:return False
            baseline,error=(None,'30s attempt deadline exceeded') if timed_out else result.get_nowait()
            if error or not self.valid_baseline(baseline or {}):
                self._event('visual_rebase_failed',evidence=dict(error=error,baseline=baseline),elapsed_s=self.clock()-self.d['attempt_started'])
                if timed_out or self.d['attempts']>=2:
                    self._close('Rebase failed budget');self._transition('LOCKOUT','Rebase deadline exceeded' if timed_out else 'Two automatic Rebase failures')
                    self._event('recovery_lockout',reason=self.d['reason'])
                else:self._transition('SETTLING','One rebase attempt failed; one remaining')
                return False
            self.background.anchor(frame() if callable(frame) else frame)
            self._commit(baseline,'verified_view_stationary_recalibration');return True
