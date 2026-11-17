"""Staged real-hardware v1 experiment using a persistent authorized session.

No action runs on import. Calls are admitted by the additional safety gate and
the unchanged on-board DualArm / UART drivers. See docs/experiment-safety.md.
"""
import importlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

import cv2
import numpy as np

import experiment_safety
from cv_pipeline.experiment_cv import CVStream
from cv_pipeline.recovery_workflow import STATE,registers,snapshots,save,board_exec
from cv_pipeline.embodied_demo import PCUART,RobotArm,ROOT
sys.path.insert(0,str(ROOT/'code'))
from exploration_events import emit as public_emit

RUNNER=None


def validate_cv_adapter(adapter):
    """Fail before sending PWM if a stale/incompatible CV module was loaded."""
    for name in ('start','settled','stats','close'):
        if not callable(getattr(adapter,name,None)):
            raise experiment_safety.SafetyError('Incompatible CV adapter: missing '+name)


class Runner:
    def __init__(self,session,out,event):
        importlib.reload(experiment_safety)
        self.s=session;self.out=out;self.event=event
        self.gate=experiment_safety.ExperimentGate(out.name)
        cv_module=importlib.reload(importlib.import_module('cv_pipeline.experiment_cv'))
        self.cv=cv_module.CVStream(out,event);self.cv.camera_pose_id='initial_unhomed'
        self.cv.on_failure=self.gate.pause
        self.ex=None;self.uart=None;self.observer=None;self.position=None;self.view='initial_unhomed'
        self.counts={1:(307,287,297),2:(307,307,307)}
        self.primary='wrist_8768';self.std_limit=1.5;self.parameter_version='compensation-v0';self.trials=[]
        self.last_ack=None;self.recording=None

    def summary(self,kind,zh,en,**fields):
        public_emit(kind,zh,text_en=en,**fields)
        self.event(kind,text=zh,text_en=en,**fields)

    def check(self):
        self.gate.admit()
        if self.cv.failure:raise experiment_safety.SafetyError(self.cv.failure)
        for reader in self.cv.readers.values():
            frame,_,received,_,error=reader.latest()
            if frame is None or error or time.monotonic()-received>1:
                raise experiment_safety.SafetyError('Camera stale before command')

    def spacing(self):
        if self.gate.last_completed is not None:
            time.sleep(max(0,2.05-(time.monotonic()-self.gate.last_completed)))

    def measure(self,motion_id,counts=None,approach=None):
        ack=self.last_ack if self.last_ack is not None else time.monotonic()
        deadline=ack+5
        while time.monotonic()<deadline:
            if self.cv.failure:raise experiment_safety.SafetyError(self.cv.failure)
            windows=[self.cv.settled(ack+.5,cid,arm,self.std_limit) for cid in self.cv.readers for arm in (1,2)]
            if all(w and w['stationary'] for w in windows):
                photos=snapshots(self.out,motion_id+'-settled',self.event)
                for w in windows:
                    arm=int(w['arm_id'][-1]);values=(counts or self.counts)[arm]
                    w.update(pwm_counts=values[2],approach_direction=approach,
                        parameter_version=self.parameter_version,delay_from_trajectory_ack_ms=(time.monotonic()-ack)*1000)
                    self.event('settled_measurement',motion_id=motion_id,**w)
                chosen=next(w for w in windows if w['camera_id']==self.primary and w['arm_id']=='green_2')
                return dict(stationary=True,evidence_path=photos[self.primary]['path'],windows=windows,primary=chosen)
            time.sleep(.05)
        self.event('settle_timeout',motion_id=motion_id,timeout_s=5)
        raise experiment_safety.SafetyError('No compliant stationary window within5s')

    def rpc(self,expression):
        value=self.s.rpc(expression)
        if expression.startswith('d.run_segment'):self.last_ack=time.monotonic()
        return value

    def start(self):
        validate_cv_adapter(self.cv)
        if not STATE.get('dual_initialized'):raise experiment_safety.SafetyError('DualArm not initialized')
        if STATE.get('vision_paused'):raise experiment_safety.SafetyError('Vision pause latched')
        state=self.s.rpc('d.status()');pca=registers(self.s)
        if state['enabled'] or pca['prescale']!=121 or any(v!=[0,0,0,16] for ch,v in pca['pwm']):
            raise experiment_safety.SafetyError('Expected all-off50Hz reference acquisition state')
        confirmation='User authorized recovery/S1 and replied1: arms physically placed at known reference pose, safe to apply reference PWM; workspace clear, G28 path safe, power switch ready.'
        self.event('human_clearance_granted',operator_confirmation=confirmation,source='Current conversation; explicit choice1',scope='Current connected session and unchanged windows; reference enable and S1')
        self.gate.authorize(self.out.name,confirmation)
        save(self.out,'safety_gate.json',dict(stage='S1',motion_allowed=True,operator_confirmation=confirmation,connection_id=self.out.name))
        self.cv.start();time.sleep(.3)
        command='d.enable((307,287,297),(307,307,307))'
        self.event('move_requested',motion_id='reference-acquisition',device='COM8',command=command,origin_kind='operator_confirmed_physical_reference',target_counts=self.counts,
            first_enable_velocity_limited=False,expected_motion='no commanded pose change; PWM acquisition')
        self.gate.begin('reference-acquisition')
        self.event('move_started',motion_id='reference-acquisition',device='COM8',command=command)
        self.s.rpc(command);self.last_ack=time.monotonic()
        evidence=self.measure('reference-acquisition',self.counts)
        self.s.rpc('d.confirm_settled(%r)'%evidence['evidence_path'])
        self.gate.finish('reference-acquisition',evidence)
        experiment_safety.SafeExecutor.check_hardware(self.s.rpc("__import__('machine').unique_id().hex()"),registers(self.s),self.s.rpc('d.status()'))
        self.ex=experiment_safety.SafeExecutor(self.gate,self.rpc,self.event,self.counts)
        self.summary('result','参考脉宽已接通，双摄窗口确认两臂停稳。','Reference PWM acquired; dual-camera windows confirmed both arms stationary.',frame=evidence['evidence_path'])
        return self.baseline('initial-baseline')

    def baseline(self,label):
        start=time.monotonic()
        while time.monotonic()-start<10.5:
            if self.cv.failure:raise experiment_safety.SafetyError(self.cv.failure)
            time.sleep(.1)
        stats=self.cv.stats(start)
        if not all(stats[cid][str(arm)] and stats[cid][str(arm)]['stationary'] for cid in stats for arm in (1,2)):
            raise experiment_safety.SafetyError('Static baseline does not meet protocol thresholds')
        save(self.out,label+'.json',dict(camera_pose_id=self.view,statistics=stats,cv_version='cv-fixed-prior-v1'))
        self.event('phase_result',phase='0',label=label,statistics=stats)
        self.baseline_stats=stats
        return stats

    def green(self,target,label,approach=None):
        self.spacing();self.check()
        targets={1:self.counts[1],2:(307,307,int(target))}
        self.cv.motion_id=label
        evidence=self.ex.green(targets,label,lambda _:self.measure(label,targets,approach),speed=2)
        self.counts=targets
        row=dict(evidence['primary']);row.update(motion_id=label,pwm_counts=int(target),approach_direction=approach,
                 parameter_version=self.parameter_version)
        self.trials.append(row)
        self.event('trial_result',motion_id=label,measurement=row)
        return row

    def close(self):
        self.cv.close()
        if self.uart:self.uart.deinit()


def session_action(session,out,event,args):
    global RUNNER
    if RUNNER is None:RUNNER=Runner(session,out,event)
    try:
        op=args['operation']
        if op=='start':return RUNNER.start()
        if op=='baseline':return RUNNER.baseline(args.get('label','baseline'))
        if op=='close':RUNNER.close();return dict(closed=True,outputs_held=True)
        raise ValueError('Unknown experiment stage')
    except BaseException as exc:
        RUNNER.gate.pause(exc)
        event('safety_pause',reason=repr(exc),hold_last_output=True,release_requested=False,automatic_resume=False)
        save(out,'safety_gate.json',dict(stage='S1_SAFETY_PAUSE',motion_allowed=False,reason=repr(exc),pending_motion=RUNNER.gate.pending))
        raise
