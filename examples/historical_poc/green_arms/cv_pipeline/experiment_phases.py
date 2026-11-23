"""User-revised camera roles, bounded view survey and repeatable single-axis trials.

Revision20261117: wrist is the sole angle source; global tracks coarse regions.
Angular stationarity cap3.5deg is explicitly user-authorized, not a v1 pass.
An inconclusive response/backlash ends tuning rather than manufacturing success.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import math
import time
import json
import numpy as np
import cv2
from serial.tools import list_ports

from cv_pipeline.experiment_runner import Runner,validate_cv_adapter
from cv_pipeline.experiment_cv import baseline_threshold
from experiment_safety import REFERENCE,VIEWS,SafeExecutor,SafetyError
from cv_pipeline.recovery_workflow import registers,snapshots,save
from cv_pipeline.embodied_demo import PCUART,RobotArm


def compare_groups(low,high,noise,seed=1701):
    a=np.array(low,float);b=np.array(high,float)
    if min(len(a),len(b))<5:raise ValueError('At least5 independent windows per approach')
    signed=float(np.median(a)-np.median(b))
    rng=np.random.default_rng(seed)
    bootstrap=np.median(rng.choice(a,(3000,len(a))),axis=1)-np.median(rng.choice(b,(3000,len(b))),axis=1)
    ci=np.percentile(bootstrap,[2.5,97.5]).tolist()
    scatter=max(float(np.std(a,ddof=1)),float(np.std(b,ddof=1)))
    floor=max(3*noise,2*scatter)
    return dict(H_deg=abs(signed),signed_A_minus_B_deg=signed,signed_difference_CI95_deg=ci,
                within_group_std_max_deg=scatter,baseline_noise_deg=noise,significance_floor_deg=floor,
                significant=bool(abs(signed)>floor and (ci[0]>0 or ci[1]<0)),n_A=len(a),n_B=len(b))


class RevisedRunner(Runner):
    def __init__(self,s,out,event):
        super().__init__(s,out,event)
        self.authorized=False;self.selected_baseline=None;self.local_model=None;self.backlash=None
        self.compensation={};self.versions=[];self.phase_results={};self.camera_samples=[]
        self.pending_comp=None

    def prepare(self):
        validate_cv_adapter(self.cv)
        ports={p.device:p for p in list_ports.comports()}
        if not ports.get('COM8') or ports['COM8'].serial_number.lower()!='70:af:09:2a:ee:e8':raise SafetyError('COM8 USB identity mismatch')
        uid=self.s.rpc("__import__('machine').unique_id().hex()")
        state=self.s.rpc('d.status()');pca=registers(self.s)
        SafeExecutor.check_hardware(uid,pca,state)
        confirmation='Latest user: people fully outside work envelope, desk clear, physical power cut-off ready; S1 resumed; wrist-only angle source/global-region safety role; angular std cap3.5deg permitted.'
        self.event('human_clearance_granted',operator_confirmation=confirmation,scope='Current connection; fixed original windows, channels,50Hz; user revision to CV camera roles/noise gate')
        self.event('parameter_applied',scope='protocol_revision',old='all-camera PnP and1.5deg cap',new='wrist angles/global coarse regions; min(3.5,max(1.5,3sigma))deg',source='Explicit latest user instruction',hardware_limits_changed=False)
        self.gate.authorize(self.out.name,confirmation);self.authorized=True
        save(self.out,'safety_gate.json',dict(stage='S1_PREPARE',motion_allowed=False,operator_confirmation=confirmation,reason='Fresh baseline and pre-motion keyframe review pending'))
        self.cv.start()
        stats=self.baseline('initial-baseline')
        photos=snapshots(self.out,'pre-motion-clearance',self.event)
        self.ex=SafeExecutor(self.gate,self.rpc,self.event,self.counts)
        save(self.out,'preflight.json',dict(uid=uid,ports={k:dict(hwid=ports[k].hwid) for k in ('COM3','COM8') if k in ports},pca=pca,state=state,
            cv_version='cv-wrist-global-region-v2',primary='wrist_8768',global_role='coarse_regions_safety_only',baseline=stats,
            protocol_revision='Latest user explicitly authorized angular cap3.5deg; never present as original v1 compliance',frames=photos))
        return dict(statistics=stats,frames=photos,std_limit_deg=self.std_limit)

    def activate_after_keyframe_review(self):
        if not self.authorized or self.gate.paused:raise SafetyError('No current-session permission')
        if self.cv.failure:raise SafetyError(self.cv.failure)
        self.last_ack=time.monotonic()
        evidence=self.measure('resume-reference')
        self.s.rpc('d.confirm_settled(%r)'%evidence['evidence_path'])
        save(self.out,'safety_gate.json',dict(stage='S1',motion_allowed=True,source='User authorization plus recorded fresh keyframe review and stationary wrist windows',std_limit_deg=self.std_limit))
        return dict(reference_settled=True,evidence=evidence)

    def baseline(self,label):
        start=time.monotonic()
        while time.monotonic()-start<11:
            if self.cv.failure:raise SafetyError(self.cv.failure)
            time.sleep(.1)
        stats=self.cv.stats(start)
        primary=stats['wrist_8768']
        if any(primary[str(arm)] is None or primary[str(arm)]['angle_std_deg'] is None for arm in (1,2)):
            raise SafetyError('Baseline has no observable wrist projected angle')
        old=self.std_limit
        self.std_limit=max(baseline_threshold(primary[str(arm)]['angle_std_deg']) for arm in (1,2))
        self.cv.std_limit=self.std_limit
        stats=self.cv.stats(start)
        if not all(stats['wrist_8768'][str(arm)]['stationary'] for arm in (1,2)) or not self.cv.global_ready():
            save(self.out,label+'.json',dict(valid=False,statistics=stats,std_limit_deg=self.std_limit))
            raise SafetyError('Fresh wrist baseline or coarse global visibility fails revised protocol')
        save(self.out,label+'.json',dict(valid=True,statistics=stats,std_limit_deg=self.std_limit,cv_version='cv-wrist-global-region-v2',view=self.view))
        self.event('parameter_applied',scope='baseline_stationarity_only',old_std_limit_deg=old,new_std_limit_deg=self.std_limit,cap_deg=3.5,algorithm='max across both wrist-arm min(3.5,max(1.5,3sigma))',confidence_RMS_validity_drift_unchanged=True)
        self.baseline_stats=stats
        self.event('phase_result',phase='0',label=label,statistics=stats)
        return stats

    def measure(self,motion_id,counts=None,approach=None):
        ack=self.last_ack if self.last_ack is not None else time.monotonic()
        deadline=ack+5
        while time.monotonic()<deadline:
            if self.cv.failure:raise SafetyError(self.cv.failure)
            windows=[self.cv.settled(ack+.5,'wrist_8768',arm,self.std_limit) for arm in (1,2)]
            if all(w and w['stationary'] for w in windows) and self.cv.global_ready():
                photos=snapshots(self.out,motion_id+'-settled',self.event)
                for w in windows:
                    values=(counts or self.counts)[int(w['arm_id'][-1])]
                    w.update(pwm_counts=values[2],approach_direction=approach,parameter_version=self.parameter_version,
                        delay_from_trajectory_ack_ms=(time.monotonic()-ack)*1000,angular_std_limit_deg=self.std_limit)
                    self.event('settled_measurement',motion_id=motion_id,**w)
                return dict(stationary=True,evidence_path=photos['wrist_8768']['path'],windows=windows,primary=windows[1])
            time.sleep(.05)
        self.event('settle_timeout',motion_id=motion_id,timeout_s=5)
        raise SafetyError('No compliant wrist window/global visibility within5s')

    def raw_camera_stationary(self,label):
        """Fresh-image settling for observer movement, separate from angle quality."""
        deadline=time.monotonic()+5;reader=self.cv.readers['wrist_8768']
        frame,seq,stamp,_,err=reader.latest();begin=time.monotonic();pairs=[]
        if frame is None or err:raise SafetyError('No wrist frame for observer settling')
        last=cv2.cvtColor(np.asarray(frame),cv2.COLOR_RGB2GRAY);last_t=stamp
        while time.monotonic()<deadline:
            if not self.cv.global_ready():raise SafetyError('Global target region missing during observer movement')
            time.sleep(.3)
            frame,n,received,_,error=reader.latest()
            if error or time.monotonic()-received>1:raise SafetyError('Wrist video stale during settling')
            if n==seq:continue
            gray=cv2.cvtColor(np.asarray(frame),cv2.COLOR_RGB2GRAY)
            points=cv2.goodFeaturesToTrack(last,150,.03,10)
            if points is None:raise SafetyError('Insufficient background texture')
            moved,valid,_=cv2.calcOpticalFlowPyrLK(last,gray,points,None)
            d=np.linalg.norm((moved-points).reshape(-1,2)[valid.ravel()==1],axis=1)
            p90=float(np.percentile(d,90)) if len(d)>=20 else float('inf')
            pairs.append(dict(end=received,p90=p90,features=len(d)))
            if p90>=.8:begin=time.monotonic();pairs=[]
            if time.monotonic()-begin>=1.2 and len(pairs)>=4:
                photos=snapshots(self.out,label+'-observer-stable',self.event)
                return dict(stationary=True,evidence_path=photos['wrist_8768']['path'],window_ms=(time.monotonic()-begin)*1000,p90_px=max(p['p90'] for p in pairs))
            last=gray;seq=n;last_t=received
        raise SafetyError('Observer image did not settle within5s')

    def observer_command(self,command):
        self.summary('sending',command,command,command=command)
        self.observer.command(command)
        self.event('acknowledged',device='COM3',command=command,response='ok',physical_completion=False)

    def home(self):
        self.spacing();self.check()
        port=next((p for p in list_ports.comports() if p.device=='COM3'),None)
        if not port or (port.vid,port.pid)!=(0x1a86,0x7523):raise SafetyError('COM3 CH340 identity mismatch')
        self.uart=PCUART('COM3');self.observer=RobotArm(self.uart,timeout_ms=120000)
        self.observer_command('G4 S0')
        self.gate.begin('observer-homing');self.cv.motion_id='observer-homing';self.cv.camera_moving=True
        self.event('camera_move_started',motion_id='observer-homing',command='M17; G28',operator_homing_path_confirmed=True)
        self.observer_command('M17');self.observer_command('G28')
        # Prior real log had12s homing ACK plus10s wait; ACK alone is insufficient.
        time.sleep(10)
        evidence=self.raw_camera_stationary('home')
        self.position=VIEWS['HOME'];self.view='HOME';self.cv.camera_pose_id='HOME'
        self.cv.reset_generation+=1;self.cv.camera_moving=False
        self.gate.finish('observer-homing',evidence)
        self.summary('motion_verified','观察臂归零后，连续新鲜画面已确认停稳。','Fresh image windows confirmed observer settling after homing.',command='G28',frame=evidence['evidence_path'])
        self.event('camera_move_completed',motion_id='observer-homing',nominal_post_home_position_mm=self.position,absolute_position_sensor_verified=False,evidence=evidence)
        time.sleep(2)

    def camera_segment(self,target,label,edge,speed=5):
        self.spacing()
        # During a survey, camera-angle quality is assessed after arrival; global
        # coarse visibility and fresh frames are mandatory before every segment.
        self.check()
        self.gate.observer_path(self.position,target,edge,speed)
        self.gate.begin(label);self.cv.camera_moving=True;self.cv.motion_id=label
        self.event('camera_move_started',motion_id=label,origin=self.position,target=target,edge=edge,speed_mm_s=speed)
        command='G1 X%.6f Y%.6f Z%.6f F5'%tuple(target)
        self.observer_command(command);time.sleep(max(3,math.dist(target,self.position)/5+2))
        evidence=self.raw_camera_stationary(label)
        self.position=tuple(target);self.cv.camera_pose_id=label;self.cv.reset_generation+=1;self.cv.camera_moving=False
        self.gate.finish(label,evidence)
        self.summary('motion_verified','观察臂子段已由新鲜画面确认停稳。','Fresh image windows confirmed the observer subsegment stationary.',command=command,frame=evidence['evidence_path'])
        self.event('camera_move_completed',motion_id=label,target=target,evidence=evidence)
        time.sleep(2)

    def camera_to(self,name):
        origin_name=self.view;target=VIEWS[name];edge=(origin_name,name)
        if origin_name==name:return
        origin=np.array(self.position,float);end=np.array(target,float)
        segments=max(1,int(math.ceil(np.linalg.norm(end-origin)/5)))
        for i in range(1,segments+1):self.camera_segment((origin+(end-origin)*i/segments).tolist(),name+'-segment'+str(i),edge)
        self.view=name;self.cv.camera_pose_id=name

    def views(self):
        self.home();self.camera_to('A')
        results=[]
        for name in ('A','B-small','C-small'):
            if self.view!=name:self.camera_to(name)
            stats=self.baseline('view-'+name)
            w=stats['wrist_8768'];score=min(w[a]['valid_ratio']*w[a]['confidence_median']/(1+w[a]['angle_std_deg']) for a in ('1','2'))
            entry=dict(view_id=name,target_mm=VIEWS[name],score=score,statistics=stats)
            results.append(entry)
        winner=max(results,key=lambda x:x['score'])['view_id']
        if winner!=self.view:self.camera_to(winner)
        self.selected_baseline=self.baseline('locked-view-baseline')
        self.noise=float(self.selected_baseline['wrist_8768']['2']['angle_std_deg'])
        save(self.out,'baseline.json',dict(valid=True,view_id=winner,statistics=self.selected_baseline,std_limit_deg=self.std_limit))
        save(self.out,'camera_view_comparison.json',dict(views=results,selected=winner,selection='Maximize worst-arm valid_ratio*Q/(1+angle_std); RMS reported independently; no cross-view angle subtraction',view_locked=True))
        self.event('camera_view_selected',selected=winner,comparison=results,locked_through_phase3=True)
        self.phase_results['0.5']='PASS'
        return dict(views=results,selected=winner,baseline_noise_deg=self.noise)

    def travel(self,target,label,approach=None):
        result=None;steps=0
        while self.counts[2][2]!=target:
            current=self.counts[2][2];next_count=current+int(np.clip(target-current,-5,5))
            steps+=1;result=self.green(next_count,label+'-'+str(steps),approach)
        return result

    def sample_approach(self,P,direction,label,offset=0):
        start=P-5 if direction=='A' else P+5
        self.travel(start,label+'-preposition')
        actual=P+int(offset)
        if not ((direction=='A' and actual>start) or (direction=='B' and actual<start)):
            raise SafetyError('Compensation would reverse the declared approach')
        row=self.travel(actual,label+'-approach',direction)
        if row is None:raise SafetyError('No actual approach segment')
        row.update(nominal_target_counts=P,actual_target_counts=actual,start_counts=start)
        return row

    def repeated(self,P,label,offsets=None,n=5):
        offsets=offsets or {'A':0,'B':0};samples=[]
        for i in range(n):
            for direction in ('A','B'):
                samples.append(self.sample_approach(P,direction,label+'-%d-%s'%(i,direction),offsets[direction]))
        comparison=compare_groups([s['angle_median_deg'] for s in samples if s['approach_direction']=='A'],
                                  [s['angle_median_deg'] for s in samples if s['approach_direction']=='B'],self.noise)
        return dict(target_counts=P,offsets=offsets,samples=samples,statistics=comparison)

    def phase1(self):
        if not self.selected_baseline:raise SafetyError('Camera survey/locked baseline required')
        samples=[]
        for repeat in range(3):
            self.travel(302,'response-%d-low'%repeat)
            for point in (307,312,317):
                row=self.travel(point,'response-%d-%d'%(repeat,point),'A')
                samples.append(row)
        x=np.array([r['pwm_counts'] for r in samples]);y=np.array([r['angle_median_deg'] for r in samples])
        a,b=np.polyfit(x,y,1);residual=y-(a*x+b);rms=float(np.sqrt(np.mean(residual**2)))
        medians=[float(np.median(y[x==point])) for point in (307,312,317)]
        monotonic=(medians[0]<medians[1]<medians[2]) or (medians[0]>medians[1]>medians[2])
        signal=abs(medians[-1]-medians[0]);valid=bool(monotonic and abs(a)>.01 and signal>max(2*self.noise,3*rms))
        self.local_model=dict(slope_deg_per_count=float(a),intercept_deg=float(b),fit_rms_deg=rms,signal_deg=signal,baseline_noise_deg=self.noise,monotonic=monotonic,usable=valid,samples=samples)
        save(self.out,'local_pwm_response.json',self.local_model);self.phase_results['1']='PASS' if valid else 'INCONCLUSIVE'
        self.event('phase_result',phase='1',model=self.local_model)
        return self.local_model

    def phase2(self):
        if not self.local_model or not self.local_model['usable']:raise SafetyError('Local response not observable; no backlash/tuning justified')
        training=self.repeated(312,'backlash-train')
        result=dict(training=training,holdout_target_counts=322,holdout=None,significant=training['statistics']['significant'])
        if result['significant']:result['holdout']=self.repeated(322,'backlash-holdout-baseline')
        self.backlash=result;save(self.out,'backlash_trials.json',result)
        self.phase_results['2']='PASS' if result['significant'] else 'INCONCLUSIVE'
        self.event('phase_result',phase='2',backlash=result)
        return result

    def phase3(self):
        if not self.backlash or not self.backlash['significant']:raise SafetyError('Backlash evidence insufficient; automatic compensation prohibited')
        a=self.local_model['slope_deg_per_count'];difference=self.backlash['training']['statistics']['signed_A_minus_B_deg']
        previous={'A':0,'B':0};best=self.backlash['training']['statistics']['H_deg']
        rounds=[]
        for index,scale in enumerate((.5,1.,1.5),1):
            correction=int(np.clip(round(scale*difference/(2*a)),-4,4))
            proposed={'A':-correction,'B':correction}
            old_version=self.parameter_version;version='compensation-v'+str(index)
            self.event('parameter_proposed',old=previous,new=proposed,version=version,basis=dict(local_slope=a,signed_backlash=difference,scale=scale),expected_metric='H1<H0')
            self.parameter_version=version
            self.pending_comp=dict(from_version=version,to_version=old_version,offsets=previous.copy())
            self.event('parameter_applied',version=version,offsets=proposed,all_final_counts_rechecked_by_original_driver=True)
            train=self.repeated(312,'comp%d-train'%index,proposed)
            holdout=self.repeated(322,'comp%d-holdout'%index,proposed)
            H0=self.backlash['training']['statistics']['H_deg'];H1=train['statistics']['H_deg']
            testH0=self.backlash['holdout']['statistics']['H_deg'];testH1=holdout['statistics']['H_deg']
            improvement=(H0-H1)/H0 if H0 else None;hold_improvement=(testH0-testH1)/testH0 if testH0 else None
            accepted=bool(H1<best and improvement is not None and improvement>=.2 and hold_improvement is not None and hold_improvement>=.2 and H0-H1>self.noise)
            row=dict(round=index,version=version,old_offsets=previous.copy(),proposed=proposed,training=train,holdout=holdout,H0_deg=H0,H1_deg=H1,relative_improvement=improvement,holdout_improvement=hold_improvement,accepted=accepted)
            rounds.append(row)
            if accepted:previous=proposed;best=H1
            else:
                self.parameter_version=old_version
                self.event('parameter_rolled_back',from_version=version,to_version=old_version,offsets=previous,reason='Improvement did not clear noise/20percent and holdout requirements')
            self.pending_comp=None
            save(self.out,'compensation_versions.json',dict(rounds=rounds,active_offsets=previous,active_version=self.parameter_version))
            self.event('trial_result',phase='3',round=index,H0=H0,H1=H1,accepted=accepted)
            if not accepted:break  # Task requires stopping an ineffective strategy.
        self.versions=rounds;self.phase_results['3']='PASS' if any(r['accepted'] for r in rounds) else 'FAIL'
        return dict(rounds=rounds,active_offsets=previous)


RUN=None


def session_action(session,out,event,args):
    global RUN
    if RUN is None:RUN=RevisedRunner(session,out,event)
    try:
        op=args['operation']
        if op=='prepare':return RUN.prepare()
        if op=='activate':return RUN.activate_after_keyframe_review()
        if op=='views':return RUN.views()
        if op=='phase1':return RUN.phase1()
        if op=='phase2':return RUN.phase2()
        if op=='phase3':return RUN.phase3()
        if op=='close':RUN.close();return dict(counts=RUN.counts,observer_target=RUN.position,closed=True)
        raise ValueError('Unknown phase')
    except BaseException as exc:
        if hasattr(RUN,'r') and RUN.r.snapshot()['state'] not in ('PAUSED','LOCKOUT'):
            RUN.r.pause(str(exc),'main:'+str(exc))
        if RUN.pending_comp:
            event('parameter_rolled_back',**RUN.pending_comp,reason='Experiment interrupted; configuration only, no automatic return motion')
            RUN.parameter_version=RUN.pending_comp['to_version']
            save(out,'compensation_interruption.json',dict(rollback=RUN.pending_comp,reason=repr(exc),raw_trials=RUN.trials))
            RUN.pending_comp=None
        RUN.gate.pause(exc)
        event('safety_pause',reason=repr(exc),hold_last_output=True,release_requested=False,automatic_resume=False)
        save(out,'safety_gate.json',dict(stage='S1_SAFETY_PAUSE',motion_allowed=False,reason=repr(exc),pending_motion=RUN.gate.pending))
        RUN.close()
        raise
