import unittest
from experiment_cv import baseline_threshold,coarse_regions
from experiment_phases import compare_groups
import numpy as np
import cv2


class RevisedProtocolTests(unittest.TestCase):
    def test_only_angular_noise_cap_changes(self):
        self.assertEqual(baseline_threshold(.1),1.5)
        self.assertEqual(baseline_threshold(.7),2.1-4.440892098500626e-16)
        self.assertEqual(baseline_threshold(2.4),3.5)
        with self.assertRaises(ValueError):baseline_threshold(float('nan'))

    def test_no_invisible_angles_are_invented_for_global_regions(self):
        frame=np.zeros((720,1280,3),np.uint8)
        cv2.rectangle(frame,(300,300),(370,650),(30,200,80),-1)
        cv2.rectangle(frame,(700,300),(770,650),(30,200,80),-1)
        regions=coarse_regions(frame)
        self.assertEqual(set(regions),{1,2})
        self.assertLess(regions[1]['centroid'][0],regions[2]['centroid'][0])
        self.assertNotIn('joint_angles_deg',regions[1])

    def test_backlash_requires_noise_and_repeatability_significance(self):
        high=compare_groups([5,5.1,5.2,4.9,5.05],[1,1.1,.9,1.05,1.0],.1)
        self.assertTrue(high['significant'])
        low=compare_groups([1,1.1,.9,1.05,1.0],[1,1.1,.9,1.05,1.0],.2)
        self.assertFalse(low['significant'])
        with self.assertRaises(ValueError):compare_groups([1],[2],.1)


if __name__=='__main__':unittest.main()
