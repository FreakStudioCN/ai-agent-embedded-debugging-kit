"""Track the MttoRobot screen bezel and observe aligned arm motion."""

import cv2
import numpy as np


SCREEN = np.float32([[140, 92], [300, 92], [300, 184], [140, 184]])
ARM_REGIONS = {"R": (12, 24, 128, 160), "L": (312, 24, 428, 160)}


def order_corners(points):
    points = points.reshape(4, 2)
    by_y = points[np.argsort(points[:, 1])]
    top, bottom = by_y[:2], by_y[2:]
    return np.float32([*top[np.argsort(top[:, 0])], *bottom[np.argsort(-bottom[:, 0])]])


def find_screen(image, gray):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (85, 105, 110), (132, 255, 255))
    white = cv2.inRange(hsv, (0, 0, 137), (179, 69, 255))
    black = cv2.inRange(gray, 0, 70)
    black = cv2.morphologyEx(black, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    edges = cv2.Canny(gray, 55, 140)
    winner, score = None, 0.0
    for mask in (black, edges):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if not .004 * gray.size < area < .26 * gray.size:
                continue
            quad = cv2.approxPolyDP(contour, .027 * cv2.arcLength(contour, True), True)
            if len(quad) != 4 or not cv2.isContourConvex(quad):
                continue
            x, y, w, h = cv2.boundingRect(quad)
            if not 1.22 < w / h < 2.75 or area / (w * h) < .65:
                continue
            pad = max(3, int(h * .17))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(gray.shape[1], x+w+pad), min(gray.shape[0], y+h+pad)
            inside = np.zeros((y1-y0, x1-x0), np.uint8)
            cv2.fillConvexPoly(inside, quad.reshape(4, 2) - (x0, y0), 255)
            hit = inside > 0
            blue_ratio = np.count_nonzero(blue[y0:y1, x0:x1][hit]) / np.count_nonzero(hit)
            dark_ratio = np.count_nonzero(gray[y0:y1, x0:x1][hit] < 70) / np.count_nonzero(hit)
            shell_ratio = np.mean(white[y0:y1, x0:x1][~hit]) / 255 if np.any(~hit) else 0
            if blue_ratio < .025 or dark_ratio < .30 or shell_ratio < .35:
                continue
            quality = dark_ratio + shell_ratio + .55 * min(blue_ratio / .15, 1)
            # Prefer the outer bezel to a smaller contour inside the display.
            quality *= area ** .5
            if quality > score:
                winner, score = order_corners(quad), quality
    return winner


def view_label(quad):
    tl, tr, br, bl = quad
    top = np.linalg.norm(tr-tl)
    bottom = np.linalg.norm(br-bl)
    left = np.linalg.norm(bl-tl)
    right = np.linalg.norm(br-tr)
    if abs(top-bottom) / max(top, bottom) > .058:
        return "HIGH / OBLIQUE"
    if abs(left-right) / max(left, right) > .031 and abs((tr-tl)[1]) / top > .024:
        return "LEFT OBLIQUE" if left > right else "RIGHT OBLIQUE"
    return "FRONT" if abs((tr-tl)[1]) / top < .13 else "UNKNOWN"


class MttoOverlay:
    def __init__(self):
        self.reset()

    def reset(self):
        self.quad = self.points = self.gray = self.aligned = None
        self.age = 0

    def track(self, gray):
        if self.points is None or len(self.points) < 5:
            return None
        moved, valid, _ = cv2.calcOpticalFlowPyrLK(self.gray, gray, self.points, None)
        if moved is None:
            return None
        backward, reverse, _ = cv2.calcOpticalFlowPyrLK(gray, self.gray, moved, None)
        if backward is None:
            return None
        keep = ((valid.ravel() == 1) & (reverse.ravel() == 1)
                & (np.linalg.norm(backward[:, 0] - self.points[:, 0], axis=1) < 1))
        if np.count_nonzero(keep) < 5:
            return None
        fit, inliers = cv2.estimateAffinePartial2D(self.points[keep], moved[keep], ransacReprojThreshold=2)
        if fit is None or np.count_nonzero(inliers) < 5:
            return None
        return cv2.transform(self.quad[None], fit)[0]

    def process(self, rgb, moving=False):
        image = cv2.resize(rgb, (640, round(rgb.shape[0] * 640 / rgb.shape[1])))
        # The preview is RGB. OpenCV's detector takes BGR.
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        result = {"mode": "SEARCH", "view": "UNKNOWN", "arms": [], "scores": {}}
        if moving:
            self.reset()
            result["mode"] = "CAMERA TRANSIT"
            return image, result
        quad = self.track(gray) if self.quad is not None else None
        reacquire = quad is None
        if reacquire or self.age >= 10:
            detected = find_screen(bgr, gray)
            if detected is not None:
                quad = detected
                self.age = 0
                if reacquire:
                    self.aligned = None
        if quad is None:
            self.reset()
            return image, result

        center = quad.mean(axis=0)
        mask = np.zeros_like(gray)
        cv2.fillConvexPoly(mask, np.int32(center + (quad-center) * 1.27), 255)
        cv2.fillConvexPoly(mask, np.int32(center + (quad-center) * .84), 0)
        self.points = cv2.goodFeaturesToTrack(gray, 45, .012, 4, mask=mask)
        self.quad, self.gray = quad, gray
        self.age += 1
        transform = cv2.getPerspectiveTransform(quad, SCREEN)
        aligned = cv2.warpPerspective(gray, transform, (440, 260))
        result.update(mode="DETECT" if reacquire else "LK TRACK", view=view_label(quad))
        cv2.polylines(image, [np.int32(center + (quad-center) * 1.36)], True, (81, 230, 219), 2, cv2.LINE_AA)
        cv2.polylines(image, [np.int32(quad)], True, (81, 230, 219), 1, cv2.LINE_AA)
        if self.aligned is not None:
            inverse = np.linalg.inv(transform)
            diff = cv2.absdiff(cv2.GaussianBlur(aligned, (3, 3), 0),
                               cv2.GaussianBlur(self.aligned, (3, 3), 0))
            for side, (x0, y0, x1, y1) in ARM_REGIONS.items():
                region = np.s_[y0:y1, x0:x1]
                shell = np.maximum(aligned[region], self.aligned[region]) >= 155
                score = float(np.mean((diff[region] >= 23) & shell))
                result["scores"][side] = round(score, 4)
                if score < .030:
                    continue
                result["arms"].append(side)
                corners = np.float32([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]])
                polygon = np.int32(cv2.perspectiveTransform(corners, inverse))
                cv2.polylines(image, polygon, True, (255, 175, 70), 2, cv2.LINE_AA)
        self.aligned = aligned
        return image, result
