"""Read-only live preview for the synchronized MttoRobot demo recording."""

import argparse
import json
from pathlib import Path
import time
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageTk

from cv_pipeline.mtto_overlay import MttoOverlay
from monitor_core import VideoReader


TITLE = "MttoRobot Live CV"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    tracker = MttoOverlay()
    video = VideoReader(args.camera.rstrip("/") + "/stream.mjpg", rotation=180)
    video.thread.start()
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.title(TITLE)
    root.configure(bg="#0b131d")
    root.geometry("1000x680+12+12")
    root.attributes("-topmost", True)

    def label(size, shade="#ecf4fb"):
        widget = tk.Label(root, bg="#0b131d", fg=shade, anchor="w", padx=16,
                          font=("Microsoft YaHei UI", size))
        widget.pack(fill="x")
        return widget

    phase = label(17)
    command = label(11, "#a7bdcf")
    picture = tk.Label(root, bg="#0b131d")
    picture.pack(fill="both", expand=True)
    detail = label(12, "#72e9db")
    heartbeat = args.run / "overlay.jsonl"
    state_path = args.run / "phase.json"
    shown = None
    state = {}
    state_seen = 0
    started = time.monotonic()
    with heartbeat.open("x", encoding="utf-8", buffering=1) as log:
        def tick():
            nonlocal shown, state, state_seen
            try:
                current = state_path.stat().st_mtime_ns
                if current != state_seen:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state_seen = current
                    phase.configure(text=state["label"])
                    command.configure(text=state.get("command") or "等待演示动作")
            except (OSError, ValueError):
                pass
            frame, sequence, received, fps, error = video.latest()
            if frame is not None and sequence != shown and time.monotonic() - received < 1:
                img, result = tracker.process(np.asarray(frame), moving=state.get("moving", False))
                scale = min(965 / img.shape[1], 540 / img.shape[0])
                image = Image.fromarray(img)
                if scale > 0:
                    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.BILINEAR)
                photo = ImageTk.PhotoImage(image)
                picture.configure(image=photo)
                picture.image = photo
                arms = ", ".join(result["arms"]) or "--"
                detail.configure(text=f"USB LIVE  {fps:.1f} fps  /  {result['mode']}  /  {result['view']}  /  ACTIVE ARM {arms}")
                log.write(json.dumps({"utc": time.time(), "elapsed_s": round(time.monotonic()-started, 3),
                                      "sequence": sequence, "phase": state.get("label"), **result}, ensure_ascii=False) + "\n")
                shown = sequence
            elif frame is None or time.monotonic() - received >= 1:
                detail.configure(text="USB 等待新鲜帧 / Waiting for fresh frames")
            root.after(25, tick)

        root.after(0, tick)
        root.mainloop()
    video.stop.set()


if __name__ == "__main__":
    main()
