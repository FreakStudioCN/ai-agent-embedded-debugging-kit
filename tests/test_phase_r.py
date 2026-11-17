import tempfile
from pathlib import Path
import unittest
import threading
import cv2
import numpy as np
from phase_r import PhaseR,BackgroundTracker,ControllerEvidence
from experiment_safety import ExperimentGate,SafetyError,VIEWS


def scene(seed=7):
    rng=np.random.default_rng(seed)
    return cv2.cvtColor(rng.integers(0,256,(360,640),dtype=np.uint8),cv2.COLOR_GRAY2BGR)


def baseline():
    w=dict(window_ms=11000,valid_ratio=1.,confidence_median=.95,rms_px_median=.4,angle_std_deg=.1,angle_drift_deg_per_s=0)
    return dict(valid=True,windows=[w.copy(),w.copy()],std_limit_deg=1.5)


class PhaseRTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.json';self.events=[]
        self.gate=ExperimentGate('test');self.gate.authorize('test','Explicit operator clearance')
        self.r=PhaseR(self.path,lambda event,**kw:self.events.append((event,kw)),'test',self.gate.pause)
        self.gate.recovery_guard=self.r;self.frame=scene()

    def tearDown(self):self.tmp.cleanup()

    def ready(self):
        c=ControllerEvidence(True,True,'IDLE',VIEWS['A'],'simulated operator evidence')
        self.r.confirm_manual_reference('A','SIMULATED manual reference',self.frame,baseline(),c,'SIMULATED clearance')

    def arrival(self):
        self.ready();self.r.begin_verified_move(self.gate,'B-small','m1')
        self.r.segment_started('m1-step',VIEWS['A'],VIEWS['B-small'])
        self.r.segment_arrived(ControllerEvidence(True,True,'WAIT_SETTLE',VIEWS['B-small']),True)

    def test_unknown_position_blocks_every_motion_type_including_homing_request(self):
        self.r.observe(ControllerEvidence(True,False,'UNKNOWN'),dict(valid=True,drift=False))
        with self.assertRaises(SafetyError):self.gate.begin('G28')
        with self.assertRaises(SafetyError):self.gate.observer_path(VIEWS['A'],VIEWS['B-small'],('A','B-small'))
        self.assertFalse(self.gate.authorized)

    def test_background_drift_while_controller_idle_pauses_without_rezero(self):
        self.ready();self.r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A']),dict(valid=True,drift=True))
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')
        self.assertTrue(any(e=='safety_pause' for e,_ in self.events))

    def test_registered_move_can_recalibrate_and_invalidate_old_errors(self):
        self.arrival();old=self.r.snapshot()['calibration_version']
        c=ControllerEvidence(True,True,'IDLE',VIEWS['B-small'])
        self.assertTrue(self.r.attempt_recalibration(c,True,self.frame,baseline))
        self.assertNotEqual(old,self.r.snapshot()['calibration_version'])
        with self.assertRaises(SafetyError):self.r.assert_comparable(dict(calibration_version=old,camera_pose_id='A',measurement_mode='projected'),dict(calibration_version=self.r.snapshot()['calibration_version'],camera_pose_id='B-small',measurement_mode='projected'))
        self.assertTrue(any(e=='comparisons_invalidated' for e,_ in self.events))

    def test_two_measurement_attempts_then_persisted_lockout(self):
        self.arrival();c=ControllerEvidence(True,True,'IDLE',VIEWS['B-small'])
        for _ in range(2):self.assertFalse(self.r.attempt_recalibration(c,True,self.frame,lambda:dict(valid=False)))
        self.assertEqual(self.r.snapshot()['state'],'LOCKOUT')
        again=PhaseR(self.path,lambda *a,**k:None,'new-process')
        self.assertEqual(again.snapshot()['state'],'LOCKOUT')
        with self.assertRaises(SafetyError):again.confirm_manual_reference('A','new clearance',self.frame,baseline(),ControllerEvidence(True,True,'IDLE',VIEWS['A']),'yes')
        with self.assertRaises(SafetyError):again.attempt_recalibration(c,True,self.frame,baseline)

    def test_first_failed_attempt_then_second_success_has_exact_budget(self):
        self.arrival();c=ControllerEvidence(True,True,'IDLE',VIEWS['B-small'])
        self.assertFalse(self.r.attempt_recalibration(c,True,self.frame,lambda:dict(valid=False)))
        self.assertTrue(self.r.attempt_recalibration(c,True,self.frame,baseline))
        self.assertEqual(self.r.snapshot()['attempts'],2)

    def test_camera_fault_never_triggers_baseline_retry(self):
        self.ready();self.r.observe(ControllerEvidence(True,True,'IDLE',VIEWS['A']),dict(valid=True,drift=False),False)
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')
        self.assertEqual(self.r.snapshot()['attempts'],0)

    def test_second_distinct_anomaly_locks_out_but_same_incident_is_not_double_counted(self):
        self.ready();c=ControllerEvidence(True,False,'UNKNOWN')
        self.r.observe(c,dict(valid=True),incident_id='one');self.r.observe(c,dict(valid=True),incident_id='one')
        self.assertEqual(self.r.snapshot()['consecutive_anomalies'],1)
        self.r.observe(c,dict(valid=True),incident_id='two')
        self.assertEqual(self.r.snapshot()['state'],'LOCKOUT')

    def test_nonstationary_or_untrusted_cannot_recalibrate(self):
        self.arrival()
        self.assertFalse(self.r.attempt_recalibration(ControllerEvidence(True,False,'UNKNOWN'),True,self.frame,baseline))
        self.assertEqual(self.r.snapshot()['attempts'],0)

    def test_baseline_claim_cannot_skip_quality_or_duration_checks(self):
        self.assertFalse(PhaseR.valid_baseline(dict(valid=True)))
        b=baseline();b['windows'][0]['window_ms']=9999
        self.assertFalse(PhaseR.valid_baseline(b))

    def test_static_background_versus_affine_displacement(self):
        bg=BackgroundTracker();bg.anchor(self.frame)
        same=bg.compare(self.frame);self.assertTrue(same['valid']);self.assertFalse(same['drift'])
        shifted=cv2.warpAffine(self.frame,np.float32([[1,0,12],[0,1,0]]),(640,360))
        result=bg.compare(shifted);self.assertTrue(result['valid']);self.assertTrue(result['drift'])

    def test_corrupt_state_is_fail_closed(self):
        self.path.write_text('garbage',encoding='utf-8')
        bad=PhaseR(self.path,lambda *a,**k:None,'new')
        self.assertEqual(bad.snapshot()['state'],'LOCKOUT')

    def test_stationarity_callback_does_not_block_background_state_thread(self):
        self.arrival();c=ControllerEvidence(True,True,'IDLE',VIEWS['B-small'])
        def stationary():
            done=threading.Event()
            t=threading.Thread(target=lambda:(self.r.snapshot(),done.set()),daemon=True);t.start()
            self.assertTrue(done.wait(.5));return True
        self.assertTrue(self.r.attempt_recalibration(c,stationary,lambda:self.frame,baseline))

    def test_mixed_calibration_window_is_not_stationary(self):
        from experiment_cv import window_stats
        rows=[dict(monotonic_ms=i*100,camera_id='wrist_8768',camera_pose_id='A',camera_moving=False,arm_id='green_2',
            track_valid=True,joint_angles_deg={'elbow':0},confidence=1.,rms_px=.1,calibration_version='one' if i<7 else 'two') for i in range(15)]
        self.assertFalse(window_stats(rows)['stationary'])

    def test_phase_r_runner_refuses_homing_without_touching_transport(self):
        from phase_r_runner import PhaseRRunner
        runner=PhaseRRunner.__new__(PhaseRRunner)
        with self.assertRaises(SafetyError):runner.observer_command('G28')

    def test_registered_motion_id_is_checked(self):
        self.ready();self.r.begin_verified_move(self.gate,'B-small','m1')
        self.r.segment_started('legitimate',VIEWS['A'],VIEWS['B-small'])
        self.r.observe(ControllerEvidence(True,True,'MOVING',VIEWS['A'],motion_id='unknown'),dict(valid=True,drift=True))
        self.assertEqual(self.r.snapshot()['state'],'PAUSED')


if __name__=='__main__':unittest.main()
