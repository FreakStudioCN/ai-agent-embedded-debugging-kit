import ast
import inspect
import unittest
from dataclasses import replace
import cv2
import numpy as np
import contour_axis_2d as module
from contour_axis_2d import AxisConfig,ContourAxisDetector,axial_difference,axis_window_stats,assert_axis_comparable


def scene(distal_rotation=0.,shoulder_rotation=0.,hide_left=False,occlude=False,pcb=False):
    image=np.full((420,720,3),210,np.uint8);green=(80,190,150)
    for arm,cx in enumerate((180,540),1):
        if hide_left and arm==1:continue
        layer=np.zeros_like(image);distal=np.zeros_like(image)
        cv2.rectangle(layer,(cx-29,210),(cx+29,355),green,-1)
        cv2.rectangle(distal,(cx-40,85),(cx+40,230),green,-1)
        cv2.rectangle(distal,(cx-62,65),(cx+62,95),green,-1)
        cv2.rectangle(distal,(cx-62,25),(cx-42,70),green,-1)
        cv2.rectangle(distal,(cx+42,25),(cx+62,70),green,-1)
        if arm==2 and distal_rotation:
            transform=cv2.getRotationMatrix2D((cx,220),distal_rotation,1.)
            distal=cv2.warpAffine(distal,transform,(720,420))
        layer[np.any(distal>0,axis=2)]=distal[np.any(distal>0,axis=2)]
        cv2.rectangle(layer,(cx-28,218),(cx+28,223),(35,65,40),-1)
        if arm==2 and shoulder_rotation:
            transform=cv2.getRotationMatrix2D((cx,350),shoulder_rotation,1.)
            layer=cv2.warpAffine(layer,transform,(720,420))
        image[np.any(layer>0,axis=2)]=layer[np.any(layer>0,axis=2)]
        cv2.ellipse(image,(cx,363),(72,33),0,0,360,green,-1)
    if pcb:cv2.rectangle(image,(330,220),(415,410),green,-1);cv2.line(image,(250,240),(370,260),green,3)
    if occlude:cv2.rectangle(image,(465,80),(615,200),(95,95,95),-1)
    return image


class ContourAxisTests(unittest.TestCase):
    def test_pure_opencv_geometry_has_no_pose_or_motion_imports(self):
        tree=ast.parse(inspect.getsource(module));forbidden={'calcOpticalFlowPyrLK','solvePnP','solvePnPGeneric','findTransformECC','serial','PCUART'}
        names={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}|{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        self.assertFalse(names&forbidden)

    def test_distinct_arm_ids_and_known_static_axis(self):
        result=ContourAxisDetector().detect(scene())
        self.assertEqual([x['arm_id'] for x in result],['green_1','green_2'])
        for row in result:
            self.assertTrue(row['measurement_valid'],row['invalid_reason']);self.assertLess(abs(axial_difference(row['axis_angle_deg'],-90)),.3)
            self.assertEqual(row['measurement_mode'],'contour_axis_2d');self.assertIsNone(row['pnp_rms_px'])

    def test_foreground_entity_rejects_short_wide_ledge_despite_vertical_centerline(self):
        yy,xx=np.mgrid[0:31,0:179]
        evidence=module.entity_axis_evidence(np.column_stack((xx.ravel(),yy.ravel())),-81.)
        self.assertFalse(evidence['valid'])
        self.assertEqual(evidence['invalid_reason'],'roi_not_an_elongated_entity_in_claimed_axis')
        yy,xx=np.mgrid[0:180,0:45]
        evidence=module.entity_axis_evidence(np.column_stack((xx.ravel(),yy.ravel())),-90.)
        self.assertTrue(evidence['valid'])

    def test_missing_left_does_not_rename_right(self):
        left,right=ContourAxisDetector().detect(scene(hide_left=True))
        self.assertFalse(left['measurement_valid']);self.assertEqual(right['arm_id'],'green_2');self.assertTrue(right['measurement_valid'])

    def test_target_distal_response_and_static_other_arm(self):
        d=ContourAxisDetector();before=d.detect(scene());after=d.detect(scene(distal_rotation=4))
        self.assertTrue(after[1]['measurement_valid'],after[1]['invalid_reason'])
        self.assertLess(abs(axial_difference(after[1]['axis_angle_deg'],before[1]['axis_angle_deg'])+4),1.)
        self.assertLess(abs(axial_difference(after[0]['axis_angle_deg'],before[0]['axis_angle_deg'])),.3)

    def test_truncated_rotated_entity_abstains_when_foreground_axis_is_ambiguous(self):
        row=ContourAxisDetector().detect(scene(distal_rotation=5))[1]
        self.assertFalse(row['measurement_valid'])
        self.assertIsNone(row['axis_angle_deg'])
        self.assertIn('entity',row['invalid_reason'])

    def test_synthetic_joint_causality_distinguishes_two_rigid_links(self):
        distal=ContourAxisDetector();proximal=ContourAxisDetector(replace(AxisConfig(),target_link='proximal_candidate'))
        baseline=proximal.detect(scene())[1]
        elbow_like=proximal.detect(scene(distal_rotation=5))[1]
        shoulder_like=proximal.detect(scene(shoulder_rotation=3))[1]
        self.assertTrue(elbow_like['measurement_valid']);self.assertTrue(shoulder_like['measurement_valid'])
        self.assertLess(abs(axial_difference(elbow_like['axis_angle_deg'],baseline['axis_angle_deg'])),.4)
        self.assertLess(abs(axial_difference(shoulder_like['axis_angle_deg'],baseline['axis_angle_deg'])+3),.5)
        self.assertLess(abs(axial_difference(distal.detect(scene(shoulder_rotation=3))[1]['axis_angle_deg'],-93)),.5)

    def test_green_board_inside_same_mount_zone_does_not_steal_identity(self):
        frame=scene();cv2.rectangle(frame,(25,125),(90,400),(80,190,150),-1)
        result=ContourAxisDetector().detect(frame)
        self.assertTrue(all(r['measurement_valid'] for r in result),[r['invalid_reason'] for r in result])
        self.assertLess(abs(result[0]['base_anchor_px'][0]-180),10)

    def test_overlay_never_prints_a_previous_valid_angle_on_occlusion(self):
        d=ContourAxisDetector();d.detect(scene());rows=d.detect(scene(occlude=True));image=module.draw_axis_overlay(scene(occlude=True),rows,1.2)
        self.assertEqual(image.shape,(420,720,3));self.assertIsNone(rows[1]['axis_angle_deg'])

    def test_stateless_order_does_not_hold_last_angle(self):
        d=ContourAxisDetector();first=d.detect(scene());d.detect(scene(distal_rotation=5));again=d.detect(scene())
        for a,b in zip(first,again):self.assertEqual(a['measurement_valid'],b['measurement_valid']);self.assertEqual(a['axis_angle_deg'],b['axis_angle_deg'])
        missing=d.detect(np.full((420,720,3),120,np.uint8))
        for r in missing:self.assertFalse(r['measurement_valid']);self.assertIsNone(r['axis_angle_deg']);self.assertIsNone(r['delta_angle_deg'])

    def test_occlusion_cannot_relabel_a_visible_proximal_fragment_as_distal(self):
        row=ContourAxisDetector().detect(scene(occlude=True))[1]
        self.assertFalse(row['measurement_valid']);self.assertIsNone(row['axis_angle_deg'])

    def test_pcb_and_thin_green_wire_are_not_accepted_as_an_arm(self):
        rows=ContourAxisDetector().detect(scene(pcb=True))
        self.assertTrue(all(r['measurement_valid'] for r in rows),[r['invalid_reason'] for r in rows])
        self.assertLess(abs(axial_difference(rows[0]['axis_angle_deg'],-90)),.4)

    def test_cross_version_or_mode_errors_are_rejected(self):
        a=dict(measurement_mode='contour_axis_2d',parameter_version='new',calibration_version='new',camera_pose_id='B')
        assert_axis_comparable(a,a)
        for key in a:
            with self.assertRaises(ValueError):assert_axis_comparable(a,dict(a,**{key:'old'}))

    def test_stability_window_requires_current_validity_and_single_version(self):
        row=dict(measurement_mode='contour_axis_2d',parameter_version='v1',calibration_version='v1',camera_pose_id='B',measurement_valid=True,axis_angle_deg=-90.,detection_quality=.95,geometry_quality=.95)
        rows=[dict(row,monotonic_ms=100*i) for i in range(15)]
        self.assertTrue(axis_window_stats(rows)['stationary'])
        for r in rows[:4]:r['measurement_valid']=False
        self.assertFalse(axis_window_stats(rows)['stationary'])
        rows=[dict(row,monotonic_ms=100*i) for i in range(15)];rows[-1]['calibration_version']='other'
        self.assertFalse(axis_window_stats(rows)['measurement_valid'])


if __name__=='__main__':unittest.main()
