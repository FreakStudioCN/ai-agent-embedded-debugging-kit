"""Replay two synchronized cycles using previously verified observer segments."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from exploration_events import emit
from quick_scan import Biped, Camera, DOWN, FEET_REGION, FRONT, LEFT, RIGHT, UP, WALK_VIEW, ScanError, record_usb


ROOT = Path(__file__).resolve().parents[1]
WINDOW = "具身探索监控台 · Embodied AI Monitor"
NEAR = (0, 174, 120)
MID = (0, 169, 120)

# Concurrent actions are limited to the two pairs verified in the previous
# synchronized recording, with the same endpoints, speed, and biped options.
OVERLAPS = {
    (LEFT, RIGHT): {"action": "turn_left", "speed": .65, "amplitude": .9, "repeat": 1},
    (RIGHT, FRONT): {"action": "turn_right", "speed": .65, "amplitude": .9, "repeat": 1},
}
CYCLES = (
    ("第一轮 · 同步起拍与低位步态", (
        (RIGHT, 7, "横扫与左转"), (FRONT, 7, "回扫与右转"),
        (UP, 7, "抬升观察"), (DOWN, 7, "下降观察"), (WALK_VIEW, 5, "低位全身"),
        ("swing_arms", "交替摆臂"), ("backward", "低位后退"),
    )),
    ("第二轮 · 抬臂与前后取景", (
        ("arms_up", "双臂抬起"), ("arms_down", "双臂放下"),
        (DOWN, 5, "低位回升"), (FRONT, 7, "正面"), (NEAR, 5, "镜头前移"),
        ("swing_arms", "近景摆臂"), (MID, 5, "镜头后移"), (FRONT, 5, "回到正面"),
    )),
)
ARM_MOTIONS = {
    "swing_arms": {"action": "swing_arms", "speed": .8, "repeat": 1},
    "backward": {"action": "backward", "speed": .7, "amplitude": 1.5, "repeat": 1},
    "arms_up": {"action": "arms_up", "speed": .8},
    "arms_down": {"action": "arms_down", "speed": .8},
}


def set_phase(folder, label, command="", moving=False):
    pending = folder / "phase.tmp"
    pending.write_text(json.dumps({"label": label, "command": command, "moving": moving},
                                  ensure_ascii=False), encoding="utf-8")
    pending.replace(folder / "phase.json")


def reference_matches(camera, reference, current):
    """Use fixed desk and shelf texture so screen content and biped movement do not define camera position."""
    if reference is None or reference.shape != current.shape:
        return False
    height, width = current.shape
    for x0, y0, x1, y1 in ((0, .45, .29, .98), (.78, .02, .99, .44)):
        region = (slice(round(y0 * height), round(y1 * height)),
                  slice(round(x0 * width), round(x1 * width)))
        if camera.displacement(reference[region], current[region]) > 12:
            return False
    return True


@contextmanager
def overlay_window(url, folder):
    proc = subprocess.Popen([sys.executable, "-B", "-m", "visual_observation.mtto_demo_window",
                             "--camera", url, "--run", str(folder)], cwd=ROOT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    journal = folder / "overlay.jsonl"

    def check():
        if proc.poll() is not None or not journal.exists() or time.time() - journal.stat().st_mtime > 2:
            raise ScanError("Live overlay is no longer receiving camera frames")

    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ScanError("Live overlay window could not start")
            if journal.exists() and '"mode": "DETECT"' in journal.read_text(encoding="utf-8"):
                break
            time.sleep(.15)
        else:
            raise ScanError("The overlay did not detect the biped at the reference view")
        yield check
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def export_synced(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["state"] != "complete":
        raise ScanError("Synchronized recordings did not complete")
    sources = manifest["sources"]
    start = max(sources[name]["media"]["start"] for name in ("vision", "monitor"))
    end = min(sources[name]["media"]["start"] + sources[name]["media"]["duration"]
              for name in ("vision", "monitor"))
    if end <= start:
        raise ScanError("The camera and desktop tracks have no common interval")
    for name, output, filt in (("vision", "dynamic-usb.mp4", "hflip,vflip,"),
                               ("monitor", "dynamic-desktop.mp4", "")):
        source = sources[name]
        skip = max(0, start - source["media"]["start"])
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{skip:.3f}", "-i", str(folder / source["file"]), "-t", f"{end-start:.3f}",
                        "-an", "-vf", filt + "setpts=PTS-STARTPTS", "-fps_mode", "vfr",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(folder / output)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"common_start_utc": start, "seconds": round(end-start, 3)}


def run(arm, url, output_dir, reference_path, biped_url, biped_config):
    import cv2
    import numpy as np

    if not biped_url or not biped_config:
        raise ScanError("Provide --scan-biped and --scan-biped-config for the two-device demo")
    cv2.setNumThreads(1)
    output_dir = output_dir.resolve()
    serial_reference = reference_path or output_dir / "quick-scan-desk-reference.jpg"
    reference = cv2.imdecode(np.frombuffer(serial_reference.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = output_dir / "dynamic-demos" / stamp
    folder.mkdir(parents=True)
    report = {"state": "stopped", "phases": [], "keyframes": []}
    camera = Camera(url, cv2, np)
    robot = Biped(biped_url, biped_config)
    capture = folder / "recordings"
    report_path = folder / "report.json"

    def log(event, zh, en, **fields):
        return emit(event, zh, path=output_dir / "agent-events.jsonl", text_en=en,
                    target="双设备动态演示", target_en="Two-device motion demo", **fields)

    def evidence(frame, label, command):
        number = len(report["keyframes"]) + 1
        raw = folder / f"{number:02d}-raw.jpg"
        upright = folder / f"{number:02d}-key.jpg"
        raw.write_bytes(frame.jpeg)
        camera.save_upright(upright, frame)
        report["keyframes"].append({"view": label, "path": str(upright), "command": command})
        return str(raw)

    def standalone(action):
        motion = ARM_MOTIONS[action]
        baseline = robot.start(motion)
        if action in ("arms_up", "arms_down"):
            angle = 72.0 if action == "arms_up" else 108.0
            baseline = {**baseline, "left_arm": angle, "right_arm": angle}
        robot.wait(action, baseline)

    try:
        if arm.pending is not None:
            raise ScanError("Previous serial command is unresolved")
        frame = camera.settle(camera.capture())
        if not reference_matches(camera, reference, frame.gray):
            raise ScanError("Start at the calibrated front view or provide a matching reference image")
        arm.command("G4 S0")
        neutral = robot.check_ready()
        if neutral["left_arm"] != 108 or neutral["right_arm"] != 108:
            raise ScanError("MttoRobot must start with both arms in its standing pose")
        setup = "G1 X%g Y%g Z%g F7" % LEFT
        log("next_action", "录制准备，机械臂移动到左侧起拍位。",
            "Recording setup: move the observer to the left starting view.", command=setup)
        sent = time.monotonic()
        arm.command(setup)
        time.sleep(max(0, math.dist(FRONT, LEFT) / 7 - (time.monotonic() - sent)))
        frame = camera.settle(camera.capture(after=frame.sequence), origin=frame.gray)
        proof = evidence(frame, "左侧起拍位", setup)
        log("motion_verified", "左侧起拍位已停稳。", "The left starting view has settled.",
            command=setup, frame=proof)
        set_phase(folder, "实时观察 · 左侧起拍位")
        with overlay_window(url, folder) as check_overlay, record_usb(url, output_dir, capture, window=WINDOW) as check_record:
            log("observation", "USB 原画与具身探索监控台录屏均已收到新帧。",
                "Both the USB camera and Embodied AI Monitor recorders are receiving frames.")
            origin = LEFT
            for cycle, stages in CYCLES:
                for stage in stages:
                    check_overlay()
                    check_record()
                    started = time.time()
                    if isinstance(stage[0], str):
                        action, label = stage
                        set_phase(folder, cycle + " · " + label, "Wi-Fi  " + action)
                        log("next_action", label, "Biped action: " + action, command=action)
                        standalone(action)
                        before = camera.capture(after=frame.sequence)
                        frame = camera.settle(before, region=FEET_REGION if action == "backward" else None)
                        proof = evidence(frame, label, action)
                        log("motion_verified", "动作结束，画面停稳。", "Biped action ended and the image settled.",
                            command=action, frame=proof)
                        report["phases"].append({"label": label, "biped": action, "started": started, "ended": time.time()})
                        continue
                    target, speed, label = stage
                    before = camera.capture(after=frame.sequence)
                    if camera.displacement(frame.gray, before.gray) >= .8:
                        raise ScanError("View changed before the next observer transition")
                    command = "G1 X%g Y%g Z%g F%g" % (*target, speed)
                    overlap = OVERLAPS.get((origin, target))
                    robot.check_ready()
                    display = command + ("  +  " + overlap["action"] if overlap else "")
                    set_phase(folder, cycle + " · " + label, display, moving=True)
                    log("next_action", "机械臂转场到" + label, "Observer transition to " + label, command=display)
                    sent = time.monotonic()
                    arm.command(command)
                    if overlap:
                        baseline = robot.start(overlap)
                    time.sleep(max(0, math.dist(origin, target) / speed - (time.monotonic() - sent)))
                    if overlap:
                        robot.wait(overlap["action"], baseline)
                    frame = camera.settle(camera.capture(after=before.sequence), origin=before.gray)
                    proof = evidence(frame, label, command)
                    set_phase(folder, cycle + " · " + label, display)
                    log("motion_verified", "镜头停稳，恢复定位。", "Observer settled; reacquiring the biped.",
                        command=command, frame=proof)
                    report["phases"].append({"label": label, "arm": command, "target": target,
                                             "biped": overlap["action"] if overlap else None,
                                             "started": started, "ended": time.time()})
                    origin = target
                    time.sleep(.18)
            if robot.check_ready() != neutral:
                raise ScanError("MttoRobot did not finish in its initial standing pose")
            set_phase(folder, "演示完成 · 正面观察位")
            log("result", "本轮动作完成，机械臂回到正面观察位，双足机器人恢复站立。",
                "The actions are complete. The observer is back at the front view, and the biped is standing.")
            time.sleep(1.3)
            check_overlay()
            check_record()
        report["sync"] = export_synced(capture)
        report["state"] = "complete"
    except BaseException as error:
        report["error"] = str(error)
        log("result", "动态演示已停止。", "The dynamic demo stopped.", error=str(error))
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("result", "动态演示完成，原画与桌面录屏已同步导出。",
        "Dynamic demo completed. Camera and desktop recordings share a common interval.", report=str(report_path))
    return report_path
