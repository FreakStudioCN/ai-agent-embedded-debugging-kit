import unittest

import cv2
import numpy as np

from cv_pipeline.mtto_overlay import MttoOverlay


class MttoOverlayTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((360, 640, 3), 100, np.uint8)
        cv2.rectangle(self.image, (233, 130), (404, 243), (236, 236, 236), -1)
        cv2.rectangle(self.image, (260, 153), (376, 224), (18, 18, 18), -1)
        cv2.rectangle(self.image, (272, 161), (364, 216), (0, 110, 255), 2)
        for point in ((248, 173), (248, 205), (387, 172), (387, 205)):
            cv2.circle(self.image, point, 3, (97, 97, 97), -1)
        self.overlay = MttoOverlay()

    def test_face_changes_do_not_mark_an_arm(self):
        _, first = self.overlay.process(self.image)
        self.assertEqual(first["mode"], "DETECT")
        changed = self.image.copy()
        cv2.circle(changed, (305, 180), 9, (240, 250, 255), -1)
        _, second = self.overlay.process(changed)
        self.assertEqual(second["mode"], "LK TRACK")
        self.assertEqual(second["arms"], [])

    def test_first_settled_frame_reacquires_after_transit(self):
        self.overlay.process(self.image)
        _, moving = self.overlay.process(self.image, moving=True)
        self.assertEqual(moving["mode"], "CAMERA TRANSIT")
        self.assertEqual(moving["arms"], [])
        _, after = self.overlay.process(self.image)
        self.assertEqual(after["mode"], "DETECT")
