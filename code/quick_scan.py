"""Replay documented observer routes using the current serial session and USB feed."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from exploration_events import emit


DIRECTIONS = {"left": "左侧", "right": "右侧", "up": "上方", "down": "下方", "front": "正前方",
              "forward": "前移", "backward": "后移"}
SWEEP_ORDER = ("left", "right", "up", "down", "front")
DEMO_ORDER = ("up", "down", "forward", "backward", "left", "right", "front")
SETTLE_SAMPLE_S = .6
SETTLE_LIMIT_PX = .8
RECORDER = Path(__file__).resolve().parents[1] / "experiment_recorder.py"
WALK = {"action": "forward", "speed": .7, "amplitude": 1.5, "repeat": 1, "swing_arms": True}
TURNS_DURING_SWEEP = {"right": "turn_left", "front": "turn_right"}
# Raw (upside-down) frame fractions covering the feet and lower chassis.
FEET_REGION = (.28, .035, .67, .46)


@dataclass(frozen=True)
class Route:
    front: tuple
    steps: tuple
    reference_limit_px: float = 1.5
    directions: tuple = SWEEP_ORDER
    hold_s: float = 0

    def missing(self):
        covered = {direction for _, _, direction in self.steps}
        return [direction for direction in self.directions if direction not in covered]


FRONT = (0, 164, 120)
LEFT = (-10, 164, 120)
RIGHT = (17, 164, 120)
UP = (0, 164, 130)
DOWN = (0, 164, 85)
WALK_VIEW = (0, 164, 70)
ROUTES = {
    # Reuse the F7 vertical and lateral lines from the desk scan. The depth
    # line is the recorded home-to-front path through Y169, in both directions.
    # The checked Z85–Z70 line extends the low view at F5 for the biped's feet.
    "demo": Route(FRONT, (
        (UP, 7, "up"), (DOWN, 7, None), (WALK_VIEW, 5, "down"),
        (DOWN, 5, None), (FRONT, 7, None),
        ((0, 174, 120), 5, "forward"), ((0, 169, 120), 5, "backward"),
        (FRONT, 5, None), (LEFT, 7, "left"), (RIGHT, 7, "right"), (FRONT, 7, "front"),
    ), reference_limit_px=12, directions=DEMO_ORDER, hold_s=.85),
    # Current desktop setup. The nominal front view differs by about 9 pixels
    # when reached from home versus after the vertical return.
    "desk": Route(FRONT, (
        (LEFT, 7, "left"), (RIGHT, 7, "right"), (FRONT, 7, None),
        (UP, 7, "up"), (DOWN, 7, "down"), (FRONT, 7, "front"),
    ), reference_limit_px=12),
    # Exact F7 replay from the November 17 observer cruise.
    "cruise": Route(FRONT, (
        (LEFT, 7, "left"), ((0, 164, 125), 7, "up"), (FRONT, 7, "front"),
    )),
}


class ScanError(RuntimeError):
    pass


class Biped:
    def __init__(self, url, config_path):
        self.url = url.rstrip("/")
        token = json.loads(config_path.read_text(encoding="utf-8"))["token"]
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    def request(self, path, action=None):
        data = None if action is None else json.dumps(action).encode("utf-8")
        with urlopen(Request(self.url + path, data=data, headers=self.headers), timeout=3) as response:
            if action is not None and response.status != 202:
                raise ScanError("Biped did not accept the demo action")
            return json.load(response)

    def check_ready(self):
        state = self.request("/status")
        if state["state"] != "idle" or not state["initialized"]:
            raise ScanError("Biped is not initialized and idle")
        return state["commanded_angles"]

    def start(self, motion):
        baseline = self.check_ready()
        self.request("/action", motion)
        return baseline

    def wait(self, action, baseline):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            state = self.request("/status")
            if state["state"] == "error" or not state["initialized"]:
                raise ScanError("Biped encountered a motion error")
            if state["action"] != action:
                raise ScanError("Biped reported a different action")
            if state["state"] == "idle":
                if state["commanded_angles"] != baseline:
                    raise ScanError("Biped did not return to its standing commands")
                return
            time.sleep(.2)
        raise ScanError("Biped action timed out: " + action)


@contextmanager
def record_usb(url, output_dir, folder, window=None):
    """Keep the existing recorder live across the whole motion sequence."""
    args = [sys.executable, "-B", str(RECORDER)]
    process = subprocess.Popen(
        [*args, "record", *(["--window", window] if window else ["--usb-only"]),
         "--camera", url, "--events", str(output_dir),
         "--output", str(folder), "--seconds", "150" if window else "90"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tracks = ("vision", "monitor") if window else ("vision",)

    def receiving(name):
        progress = folder / (name + "-progress.txt")
        try:
            updated = time.time() - progress.stat().st_mtime
            lines = progress.read_text(encoding="ascii").splitlines()
        except FileNotFoundError:
            return False
        frames = (line.removeprefix("frame=").strip() for line in lines if line.startswith("frame="))
        return updated < 3 and any(count.isdecimal() and int(count) >= 4 for count in frames)

    def recording():
        if process.poll() is not None:
            raise ScanError("Recorder exited; see " + str(folder))
        return all(receiving(name) for name in tracks)

    def check():
        if not recording():
            raise ScanError("A recording track is not receiving frames")

    try:
        deadline = time.monotonic() + 10
        while not recording():
            if time.monotonic() >= deadline:
                raise ScanError("USB recording did not start; see " + str(folder))
            time.sleep(.1)
        yield check
    finally:
        if process.poll() is None and folder.is_dir():
            (folder / "STOP").touch()
        try:
            process.wait(timeout=18)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    if process.returncode != 0:
        raise ScanError("USB recorder failed; see " + str(folder))


@dataclass(frozen=True)
class Frame:
    sequence: int
    jpeg: bytes
    gray: object


class Camera:
    def __init__(self, url, vision, arrays):
        self.url = url.rstrip("/")
        self.cv = vision
        self.np = arrays

    def capture(self, after=0):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with urlopen(self.url + "/api/status", timeout=2) as response:
                state = json.load(response)
            if not state["healthy"] or state["frame_age_seconds"] is None or state["frame_age_seconds"] > 1:
                raise ScanError("USB camera is stale")
            if state["frame_count"] < after:
                raise ScanError("USB camera restarted during the scan")
            if state["frame_count"] > after:
                with urlopen(self.url + "/snapshot.jpg", timeout=2) as response:
                    sequence = int(response.headers["X-Frame-Id"])
                    data = response.read(20 * 1024 * 1024 + 1)
                if len(data) > 20 * 1024 * 1024 or not data.endswith(b"\xff\xd9"):
                    raise ScanError("Incomplete or oversized camera JPEG")
                if sequence > after:
                    gray = self.cv.imdecode(self.np.frombuffer(data, dtype=self.np.uint8), self.cv.IMREAD_GRAYSCALE)
                    if gray is None:
                        raise ScanError("USB camera JPEG could not be decoded")
                    return Frame(sequence, data, gray)
            time.sleep(.05)
        raise ScanError("No new USB camera frame")

    def displacement(self, before, after):
        """Compare distributed, forward/backward-consistent image features."""
        if before.shape != after.shape:
            raise ScanError("USB camera resolution changed")
        points = self.cv.goodFeaturesToTrack(before, 180, .015, 18)
        if points is None:
            return math.inf
        moved, valid, _ = self.cv.calcOpticalFlowPyrLK(before, after, points, None)
        if moved is None:
            return math.inf
        back, reverse, _ = self.cv.calcOpticalFlowPyrLK(after, before, moved, None)
        if back is None:
            return math.inf
        keep = valid.ravel().astype(bool) & reverse.ravel().astype(bool)
        keep &= self.np.linalg.norm((back - points).reshape(-1, 2), axis=1) < 1.0
        origin = points.reshape(-1, 2)[keep]
        height, width = before.shape
        quadrants = (origin[:, 0] >= width / 2).astype(int) + 2 * (origin[:, 1] >= height / 2)
        if len(origin) < max(12, .35 * len(points)) or len(set(quadrants)) < 3:
            return math.inf
        distances = self.np.linalg.norm(moved.reshape(-1, 2)[keep] - origin, axis=1)
        return float(self.np.percentile(distances, 90))

    def settle(self, first, origin=None, region=None):
        if region:
            height, width = first.gray.shape
            x0, y0, x1, y1 = region
            patch = (slice(round(y0 * height), round(y1 * height)),
                     slice(round(x0 * width), round(x1 * width)))
        for _ in range(10):
            time.sleep(SETTLE_SAMPLE_S)
            current = self.capture(after=first.sequence)
            if self.displacement(first.gray, current.gray) < SETTLE_LIMIT_PX:
                if region and self.displacement(first.gray[patch], current.gray[patch]) >= SETTLE_LIMIT_PX:
                    first = current
                    continue
                if origin is None or self.displacement(origin, current.gray) > 1.5:
                    return current
            first = current
        raise ScanError("Fresh frames did not establish that the camera moved and settled"
                        if origin is not None else "Fresh frames did not establish that the camera settled")

    def sharpness(self, frame):
        return float(self.cv.Laplacian(frame.gray, self.cv.CV_32F).var())

    def save_upright(self, path, frame):
        color = self.cv.imdecode(self.np.frombuffer(frame.jpeg, dtype=self.np.uint8), self.cv.IMREAD_COLOR)
        upright = self.cv.rotate(color, self.cv.ROTATE_180)
        ok, encoded = self.cv.imencode(".jpg", upright, [self.cv.IMWRITE_JPEG_QUALITY, 94])
        if not ok:
            raise ScanError("Keyframe JPEG could not be encoded")
        path.write_bytes(encoded.tobytes())


def execute(route, arm, camera, reference, folder, notify, recording=None, biped=None):
    """Execute the selected route, recording a partial report on first fault."""
    started = time.monotonic()
    folder.mkdir(parents=True, exist_ok=False)
    report = {"state": "stopped", "start_target_mm": route.front,
              "missing": route.missing(), "views": [], "transitions": []}
    if biped:
        report["biped_actions"] = []
    try:
        if arm.pending is not None:
            raise ScanError("Previous controller command is unresolved")
        frame = camera.settle(camera.capture())
        start_delta = camera.displacement(reference, frame.gray)
        if start_delta > route.reference_limit_px:
            raise ScanError("Live image does not match the calibrated front view")
        report["start_view_delta_px"] = round(start_delta, 2)
        arm.command("G4 S0")
        focus_floor = max(12, .20 * camera.sharpness(frame))
        origin = route.front
        report["last_verified_target_mm"] = origin
        notify("observation", "串口正常，实时画面与标定观察位一致。", "Serial is responsive and the live frame matches the calibrated front view.")
        for index, (target, speed, direction) in enumerate(route.steps, 1):
            before = camera.capture(after=frame.sequence)
            if camera.displacement(frame.gray, before.gray) >= SETTLE_LIMIT_PX:
                raise ScanError("View changed before the next transition")
            if recording:
                recording()
            command = "G1 X%g Y%g Z%g F%g" % (*target, speed)
            turn = TURNS_DURING_SWEEP.get(direction) if biped else None
            if turn:
                biped.check_ready()
            notify("next_action", "沿已记录的转场移动至 " + command,
                   "Following the recorded transition: " + command, command=command)
            report["last_sent_target_mm"] = target
            sent_at = time.monotonic()
            arm.command(command)
            if turn:
                turn_motion = {"action": turn, "speed": .65, "amplitude": .9, "repeat": 1}
                notify("next_action", "镜头转场时，双足机器人同步" + ("左转。" if turn == "turn_left" else "右转。"),
                       "The biped turns during the camera transition.", command=turn)
                baseline = biped.start(turn_motion)
            travel_s = math.dist(origin, target) / speed
            time.sleep(max(0, travel_s - (time.monotonic() - sent_at)))
            if turn:
                biped.wait(turn, baseline)
                report["biped_actions"].append({**turn_motion, "camera_transition": command})
            frame = camera.settle(camera.capture(after=before.sequence), origin=before.gray)
            evidence = folder / ("%02d-raw.jpg" % index)
            evidence.write_bytes(frame.jpeg)
            report["last_verified_target_mm"] = target
            report["transitions"].append({"command": command, "frame": str(evidence), "speed_mm_s": speed})
            notify("motion_verified", "新鲜画面显示转场已停稳。", "Fresh frames show that the view has settled.",
                   command=command, frame=str(evidence))
            origin = target
            if direction is None:
                continue

            score = camera.sharpness(frame)
            attempts = 1
            if score < focus_floor:
                retry = camera.capture(after=frame.sequence)
                if camera.displacement(frame.gray, retry.gray) >= SETTLE_LIMIT_PX:
                    raise ScanError("View moved while taking the replacement frame")
                frame = retry
                score = camera.sharpness(frame)
                attempts = 2
            quality = "clear" if score >= focus_floor else "blurred"
            keyframe = folder / (direction + ".jpg")
            camera.save_upright(keyframe, frame)
            observation = DIRECTIONS[direction] + "画面清晰。"
            english = direction.capitalize() + " frame passed the clarity check."
            if quality == "blurred":
                observation = DIRECTIONS[direction] + "补拍后仍不清楚。"
                english = direction.capitalize() + " frame remained unclear after one retry."
            report["views"].append({"direction": direction, "frame": str(keyframe), "quality": quality,
                                    "sharpness": round(score, 1), "capture_attempts": attempts, "observation": observation})
            notify("result", observation, english, frame=str(evidence))
            if route.hold_s:
                time.sleep(route.hold_s)
                held = camera.capture(after=frame.sequence)
                if camera.displacement(frame.gray, held.gray) >= SETTLE_LIMIT_PX:
                    raise ScanError("View moved during the keyframe hold")
                frame = held
            if direction == "down" and biped:
                if recording:
                    recording()
                notify("next_action", "相机保持低位，双足机器人前进两步并交替摆臂。",
                       "Hold the low camera angle for a full left/right step cycle with alternating arm swings.",
                       command="forward speed=0.7 amplitude=1.5 repeat=1 swing_arms=true")
                baseline = biped.start(WALK)
                biped.wait(WALK["action"], baseline)
                frame = camera.settle(camera.capture(after=frame.sequence), region=FEET_REGION)
                feet_evidence = folder / "walk-end-raw.jpg"
                feet_evidence.write_bytes(frame.jpeg)
                camera.save_upright(folder / "walk-end.jpg", frame)
                report["biped_actions"].append({**WALK, "camera_target_mm": target, "frame": str(feet_evidence)})
                notify("result", "前进周期结束，双脚画面已停稳，继续扫视。",
                       "The walking cycle ended and the feet are stable in the image. Resume the camera sweep.",
                       frame=str(feet_evidence))
        if recording:
            recording()
        report["state"] = "complete"
    except BaseException as error:
        report["error"] = str(error) or type(error).__name__
        raise
    finally:
        report["elapsed_s"] = round(time.monotonic() - started, 2)
        report_path = folder / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, report_path


def run(arm, url, output_dir, profile, reference_path=None, biped_url=None, biped_config=None):
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ScanError("Install the scan dependencies with requirements-vision.txt") from error

    output_dir = output_dir.resolve()
    reference_profile = "desk" if profile == "demo" else profile
    reference_path = reference_path or output_dir / ("quick-scan-%s-reference.jpg" % reference_profile)
    if not reference_path.is_file():
        raise ScanError("Calibrated front keyframe is missing: " + str(reference_path))
    reference = cv2.imdecode(np.frombuffer(reference_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if reference is None:
        raise ScanError("Calibrated front keyframe is invalid")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = output_dir / "quick-scans" / (profile + "-" + stamp)
    notify = lambda event, text, english, **fields: emit(
        event, text, path=output_dir / "agent-events.jsonl", text_en=english, target="quick_scan", **fields)
    camera = Camera(url, cv2, np)
    try:
        if profile == "demo":
            # A sibling directory lets the recorder and scan each create their
            # own output atomically. They share the same timestamp and events.
            recording_folder = folder.with_name(folder.name + "-usb")
            biped = Biped(biped_url, biped_config) if biped_url else None
            if biped:
                biped.check_ready()
            with record_usb(url, output_dir, recording_folder) as check:
                notify("observation", "USB 摄像头已开始录像。", "USB camera recording is live.")
                report, path = execute(ROUTES[profile], arm, camera, reference, folder, notify, recording=check, biped=biped)
            try:
                subprocess.run([sys.executable, "-B", str(RECORDER), "export-usb", str(recording_folder)],
                               check=True, stdout=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.CalledProcessError as error:
                raise ScanError("USB export failed; the source recording is in " + str(recording_folder)) from error
            report["video"] = str(recording_folder / "quick-scan.mp4")
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            report, path = execute(ROUTES[profile], arm, camera, reference, folder, notify)
    except (Exception, KeyboardInterrupt) as error:
        notify("result", "快速扫视已停止。", "Quick scan stopped.", error=str(error), report=str(folder / "report.json"))
        raise
    notify("result", "快速扫视完成，用时 %.2f 秒。" % report["elapsed_s"],
           "Quick scan completed in %.2f seconds." % report["elapsed_s"], report=str(path))
    return report, path
