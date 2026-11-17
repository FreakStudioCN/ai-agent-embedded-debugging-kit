import unittest
from unittest.mock import Mock
import tempfile
from experiment_cv import CVStream
from experiment_cv import projected,window_stats


class WindowTests(unittest.TestCase):
    def rows(self):
        return [dict(monotonic_ms=100*i,camera_id='wrist_8768',camera_pose_id='A',arm_id='green_2',camera_moving=False,
                     track_valid=True,joint_angles_deg={'elbow':20.0},confidence=.9,rms_px=1.0) for i in range(15)]

    def test_projected_angle_is_image_geometry_not_pwm(self):
        links,joints=projected(dict(S=[10,10],E=[10,30],TCP=[30,30]))
        self.assertEqual(links,dict(upper=90,forearm=0))
        self.assertEqual(joints['elbow'],-90)

    def test_stationary_requires_duration_quality_and_fixed_camera(self):
        rows=self.rows()
        self.assertTrue(window_stats(rows)['stationary'])
        self.assertFalse(window_stats(rows[:5])['stationary'])
        for field,value in [('confidence',.79),('rms_px',5.1),('camera_moving',True),('track_valid',False)]:
            changed=[dict(row,**{field:value}) for row in rows]
            self.assertFalse(window_stats(changed)['stationary'])
        rows[-1]['camera_pose_id']='B'
        self.assertFalse(window_stats(rows)['stationary'])

    def test_drift_and_invalid_frames_cannot_be_hidden(self):
        rows=self.rows()
        for i,r in enumerate(rows):r['joint_angles_deg']={'elbow':i*.2}
        self.assertFalse(window_stats(rows)['stationary'])
        rows=self.rows()
        for r in rows[:3]:r['track_valid']=False
        self.assertFalse(window_stats(rows)['stationary'])

    def test_wraparound_does_not_create_false_motion(self):
        rows=self.rows()
        for i,r in enumerate(rows):r['joint_angles_deg']={'elbow':179.9 if i%2 else -179.9}
        self.assertTrue(window_stats(rows)['stationary'])

    def test_stream_fault_latches_admission_without_waiting_for_next_command(self):
        with tempfile.TemporaryDirectory() as folder:
            events=Mock();callback=Mock();stream=CVStream(folder,events);stream.on_failure=callback
            stream.fail('wrist timeout');stream.fail('later fault')
            callback.assert_called_once_with('wrist timeout')
            self.assertEqual(stream.failure,'wrist timeout')


if __name__=='__main__':unittest.main()
