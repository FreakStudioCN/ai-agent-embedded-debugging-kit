import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from phase_r import ControllerEvidence
from phase_r_v11 import PhaseRV11,strict_noise_limit
from phase_r_background import StaticBackground
from experiment_safety import ExperimentGate,SafetyError,VIEWS


def scene(seed=82):
    a=np.random.default_rng(seed).integers(0,256,(360,640),dtype=np.uint8)
    return cv2.cvtColor(a,cv2.COLOR_GRAY2BGR)


def baseline():
    w=dict(window_ms=11000,valid_ratio=1.,confidence_median=.95,rms_px_median=.4,angle_std_deg=.1,angle_drift_deg_per_s=0)
    return dict(valid=True,windows=[w.copy(),w.copy()],std_limit_deg=1.)


class RecoveryV11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.json';self.events=[];self.closed=[]
        self.now=100.;self.r=PhaseRV11(self.path,lambda e,**k:self.events.append((e,k)),'OFFLINE',self.closed.append,clock=lambda:self.now)
        self.frame=scene();self.g=ExperimentGate('fixture');self.g.authorize('fixture','SIMULATED fixture, no hardware')
        self.g.recovery_guard=self.r

    def tearDown(self):self.tmp.cleanup()

    def ready(self):
        self.r.authorize_manual_recovery('SIMULATED new grant','SIMULATED resolved','SIMULATED clear','SIMULATED A')
        self.r.d['background_reference']=dict(window_s=3.1)
        self.r.confirm_manual_reference('A','SIMULATED A',self.frame,baseline(),ControllerEvidence(True,True,'IDLE',VIEWS['A']),'SIMULATED')

    def arrival(self):
        self.ready();self.r.begin_verified_move(self.g,'B-small','approved')
        self.r.segment_started('seg',VIEWS['A'],VIEWS['B-small'])
        self.r.observe(ControllerEvidence(True,True,'MOVING',VIEWS['A'],motion_id='seg'),dict(valid=False,reason='expected blur'))
        self.assertEqual(self.r.snapshot()['state'],'EXPECTED_MOVE')
        self.r.segment_arrived(ControllerEvidence(True,True,'WAIT_SETTLE',VIEWS['B-small']),True)

    def attempt(self,collector=baseline,bg=None):
        return self.r.attempt_recalibration(ControllerEvidence(True,True,'IDLE',VIEWS['B-small']),True,self.frame,collector,
            bg or (lambda deadline:dict(window_s=3.1)))

    def test_strict_noise_and_quality_caps(self):
        self.assertEqual(strict_noise_limit(.1),1.)
        with self.assertRaises(SafetyError):strict_noise_limit(.50001)
        for field,value in [('confidence_median',.7999),('window_ms',9999),('angle_std_deg',1.51)]:
            b=baseline();b['windows'][0][field]=value;self.assertFalse(self.r.valid_baseline(b))
        b=baseline();b['std_limit_deg']=3.5;self.assertFalse(self.r.valid_baseline(b))

    def test_no_grant_no_motion_or_visual_unlock(self):
        with self.assertRaises(SafetyError):self.r.require_motion_allowed()
        with self.assertRaises(SafetyError):self.r.confirm_manual_reference('A','fake',self.frame,baseline(),ControllerEvidence(True,True,'IDLE',VIEWS['A']),'fake')

    def test_legal_rebase_order_invalidates_old_errors_before_completion(self):
        self.arrival();old=self.r.d['calibration_version'];self.events=[]
        self.assertTrue(self.attempt());self.assertEqual(self.r.snapshot()['state'],'NORMAL')
        names=[x[0] for x in self.events]
        self.assertLess(names.index('experiment_baseline_invalidated'),names.index('visual_rebase_completed'))
        with self.assertRaises(SafetyError):self.r.assert_comparable(dict(calibration_version=old,camera_pose_id='A',measurement_mode='projected'))

    def test_two_failed_attempts_lockout_and_restart_preserves_budget(self):
        self.arrival()
        for _ in range(2):self.assertFalse(self.attempt(lambda:dict(valid=False)))
        reloaded=PhaseRV11(self.path,lambda *a,**k:None,'restart',clock=lambda:self.now)
        self.assertEqual(reloaded.snapshot()['state'],'RECOVERY_LOCKOUT');self.assertEqual(reloaded.d['attempts'],2)
        self.assertFalse(reloaded.d['s1_authorized'])
        with self.assertRaises(SafetyError):reloaded.begin_verified_move(self.g,'A','new-id')

    def test_first_failure_second_success(self):
        self.arrival();self.assertFalse(self.attempt(lambda:dict(valid=False)));self.assertTrue(self.attempt())
        self.assertEqual(self.r.d['attempts'],2)

    def test_30second_total_budget_stops_and_locks_without_waiting_real30s(self):
        self.arrival()
        def delay():self.now+=31;return baseline()
        self.assertFalse(self.attempt(delay));self.assertEqual(self.r.snapshot()['state'],'RECOVERY_LOCKOUT')

    def test_background_three_seconds_cannot_be_omitted(self):
        self.arrival();self.assertFalse(self.attempt(bg=lambda d:dict(window_s=2.99)))
        self.assertFalse(self.attempt(bg=lambda d:dict(window_s=0)))
        self.assertEqual(self.r.snapshot()['state'],'RECOVERY_LOCKOUT')

    def test_rolling_three_triggers_includes_same_fault_episodes(self):
        self.ready()
        for _ in range(3):self.r.report_repeated_fault('same USB fault');self.now+=1
        self.assertEqual(self.r.snapshot()['state'],'RECOVERY_LOCKOUT')
        self.assertEqual(len(self.r.d['recovery_triggers']),3)

    def test_pause_closes_admission_before_persistence(self):
        self.ready();order=[];persist=self.r._persist
        self.r.on_pause=lambda reason:order.append('close')
        def logged():order.append('persist');persist()
        self.r._persist=logged;self.r.pause('test')
        self.assertEqual(order[0],'close');self.assertFalse(self.r.d['s1_authorized'])

    def test_drift_uses_duration_and_records_confirmation_after_pause(self):
        self.ready();c=ControllerEvidence(True,True,'IDLE',VIEWS['A'])
        b=dict(valid=True,drift_px=15,region_max_displacement_px=15,background_inliers=40,inlier_ratio=.95)
        for delta in (0,.49,.51,1.01):self.r.observe(c,b,now=100+delta)
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')
        self.assertEqual(sum(e=='observer_drift_suspected' for e,_ in self.events),1)
        self.assertEqual(sum(e=='observer_drift_confirmed' for e,_ in self.events),1)

    def test_unknown_position_camera_reconnect_never_resume(self):
        self.ready();self.r.observe(ControllerEvidence(True,False,'UNKNOWN'),dict(valid=True,drift_px=0))
        self.r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A']),dict(valid=True,drift_px=0),True)
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')
        with self.assertRaises(SafetyError):self.r.require_motion_allowed()

    def test_expected_move_does_not_mask_camera_fault(self):
        self.arrival();self.r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['B-small']),dict(valid=True),False)
        self.assertEqual(self.r.snapshot()['state'],'PAUSED');self.assertFalse(self.r.d['position_trusted'])

    def test_recovery_artifacts_and_required_event_fields(self):
        self.ready();self.r.pause('camera')
        folder=self.path.parent/'recovery'
        for name in ('drift_events.jsonl','recovery_attempts.jsonl','calibration_versions.json','background_reference.json','recovery_summary.md'):
            self.assertTrue((folder/name).exists())
        for line in (folder/'recovery_attempts.jsonl').read_text().splitlines():
            row=json.loads(line);self.assertTrue({'calibration_version','recovery_state','attempt_id','evidence'}<=row['details'].keys())

    def test_low_texture_and_single_patch_fail_closed(self):
        bg=StaticBackground()
        with self.assertRaises(SafetyError):bg.anchor(np.zeros_like(self.frame))
        im=np.zeros_like(self.frame);im[20:90,20:90]=self.frame[20:90,20:90]
        with self.assertRaises(SafetyError):bg.anchor(im)

    def test_people_and_green_regions_excluded_without_false_drift(self):
        bg=StaticBackground();bg.anchor(self.frame,[(250,80,90,230)])
        changed=self.frame.copy();changed[90:280,260:330]=(0,255,0)
        row=bg.compare(changed,[(250,80,90,230)])
        self.assertTrue(row['valid']);self.assertLess(row['drift_px'],1)
        mask,excluded=bg.exclusions(changed,[(250,80,90,230)])
        self.assertEqual(mask[180,280],0)
        self.assertTrue(any(x['kind']=='external_person_or_motion' for x in excluded))

    def test_rotation_scale_and_translation_use_multiple_regions(self):
        bg=StaticBackground();bg.anchor(self.frame)
        transform=cv2.getRotationMatrix2D((320,180),2,1.02);transform[:,2]+=[10,2]
        row=bg.compare(cv2.warpAffine(self.frame,transform,(640,360)))
        self.assertTrue(row['valid']);self.assertGreater(row['region_max_displacement_px'],12)
        self.assertEqual(len(row['region_displacements_px']),9)

    def test_ransac_wrong_matches_are_unknown(self):
        bg=StaticBackground();bg.anchor(self.frame)
        with patch('cv2.estimateAffinePartial2D',return_value=(None,None)):
            row=bg.compare(self.frame)
        self.assertFalse(row['valid'])

    def test_detector_face_and_person_boxes_are_actually_applied(self):
        bg=StaticBackground()
        class Faces:
            def detectMultiScale(self,*a,**k):return [(70,35,30,30)]
        class People:
            def detectMultiScale(self,*a,**k):return ([(180,30,40,110)],[])
        bg.face=Faces();bg.people=People();mask,excluded=bg.exclusions(self.frame)
        self.assertEqual(mask[100,160],0);self.assertEqual(mask[100,380],0)
        self.assertTrue({'face_and_body','person'}<={x['kind'] for x in excluded})

    def test_legacy_real_lockout_migration_does_not_clear_lock(self):
        self.path.write_text(json.dumps(dict(state='LOCKOUT',attempts=2,reason='historical quality failure',calibration_version='old')),encoding='utf-8')
        r=PhaseRV11(self.path,lambda *a,**k:None,'migration',clock=lambda:self.now)
        self.assertEqual(r.snapshot()['state'],'RECOVERY_LOCKOUT');self.assertEqual(r.d['attempts'],2)
        self.assertFalse(r.d['s1_authorized'])

    def test_restart_does_not_replenish_rolling_budget(self):
        self.ready();self.r.report_repeated_fault('USB1');self.r.report_repeated_fault('USB2')
        r=PhaseRV11(self.path,lambda *a,**k:None,'restart',clock=lambda:self.now)
        r.report_repeated_fault('USB3');self.assertEqual(r.snapshot()['state'],'RECOVERY_LOCKOUT')

    def test_candidate_cannot_rebase_paused_state_into_motion(self):
        self.ready();self.r.pause('Uncommanded displacement')
        with self.assertRaises(SafetyError):self.attempt()
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')

    def test_identical_continuous_fault_polling_is_one_trigger(self):
        self.ready()
        for _ in range(100):self.r.pause('same fault','unchanged episode')
        self.assertEqual(len(self.r.d['recovery_triggers']),1)
        for _ in range(2):self.r.report_repeated_fault('same fault')
        self.assertEqual(self.r.snapshot()['state'],'RECOVERY_LOCKOUT')

    def test_persistence_failure_closes_motion_and_leaves_restart_marker(self):
        self.ready()
        with patch.object(Path,'replace',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(SafetyError):self.r._persist()
        self.assertTrue(self.closed);self.assertFalse(self.r.d['s1_authorized'])
        self.assertEqual(self.r.snapshot()['state'],'RECOVERY_LOCKOUT')
        r=PhaseRV11(self.path,lambda *a,**k:None,'restart',clock=lambda:self.now)
        self.assertEqual(r.snapshot()['state'],'RECOVERY_LOCKOUT')

    def test_background_duration_counts_source_timestamps_including_anchor(self):
        self.ready();start=self.now
        def sample():return self.frame,self.now-.15
        def advance(seconds):self.now+=seconds
        # Emulate slow initial processing. A wall-time3s loop used to reject
        # because the first processed comparison shortened the source span.
        original=self.r.background.anchor
        def slow_anchor(frame):self.now+=.35;return original(frame)
        with patch('phase_r_v11.time.sleep',side_effect=advance),patch.object(self.r.background,'anchor',side_effect=slow_anchor):
            result=self.r.collect_background(sample)
        self.assertGreaterEqual(result['last_timestamp']-result['first_timestamp'],3.)
        self.assertGreaterEqual(result['window_s'],3.)
        self.assertLess(self.now-start,30.)

    def test_verified_multiedge_route_preserves_every_original_segment_gate(self):
        self.ready();self.r.d.update(view_id='HOME',position=list(VIEWS['HOME']))
        steps=self.r.begin_verified_route(self.g,'B-small','SIMULATED-route')
        self.assertEqual(self.r.d['plan']['route'],['HOME','A','B-small'])
        self.assertEqual(len(steps),3)
        for i,step in enumerate(steps):
            self.g.observer_path(step['origin'],step['target'],tuple(step['edge']),5)
            self.r.segment_started('step'+str(i),step['origin'],step['target'])
            self.r.segment_arrived(ControllerEvidence(True,True,'IDLE',tuple(step['target'])),True)
            self.assertEqual(self.r.snapshot()['state'],'SETTLING' if i==2 else 'EXPECTED_MOVE')
        self.assertEqual(self.r.d['view_id'],'B-small')
        self.assertEqual(len(self.r.d['recovery_triggers']),1)

    def test_unknown_route_cannot_create_motion_plan(self):
        self.ready()
        with self.assertRaises(SafetyError):self.r.begin_verified_route(self.g,'UNVERIFIED','bad')
        self.assertIsNone(self.r.d['plan']);self.assertEqual(self.r.snapshot()['state'],'NORMAL')


if __name__=='__main__':unittest.main()
