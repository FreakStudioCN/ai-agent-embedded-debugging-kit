"""Independent, read-only Tk monitoring window for embodied exploration.

Subscribes to the existing MJPEG stream and tails real JSONL events.
This program never imports the arm driver or opens the serial port.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from monitor_core import EventTail, MonitorState, VideoReader, event_time

BG = "#080e18"
PANEL = "#101a29"
TEXT = "#e5effb"
MUTED = "#8c9fb9"
CYAN = "#5be0d5"
AMBER = "#ffc879"
LOCAL_TZ = timezone(timedelta(hours=8))
TITLES = {"observation": "观察 / Observation", "interpretation": "判断 / Interpretation",
          "next_action": "决策与下一步 / Decision & Next Action", "execution": "执行 / Execution",
          "result": "结果 / Result"}
MOTION_EN = {"等待运动事件": "Waiting for motion events", "已发送 · 实际运动待确认": "Sent · Physical completion unverified",
             "已回复 · 实际运动待确认": "Acknowledged · Physical completion unverified",
             "Agent 已视觉确认停稳": "Agent visually verified settling",
             "异常 · 实际运动状态未知": "Error · Physical state unknown"}
EVENT_LABELS = {"sending": "发送 / Sent", "acknowledged": "回复 / Acknowledged", "waited": "等待 / Waited",
                "snapshot": "取图 / Snapshot", "ready": "串口连接 / Serial connected", "closed": "串口关闭 / Serial closed",
                "status": "状态 / Status", "ack_wait": "等待回复 / Await acknowledgement",
                "motion_verified": "视觉停稳 / Visually settled", "timeout": "超时 / Timeout", "error": "异常 / Error",
                "interrupted": "中断 / Interrupted", "note": "记录 / Note", **TITLES}


class Monitor:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.state = MonitorState()
        self.tail = EventTail(args.events)
        self.video = VideoReader(args.camera.rstrip("/") + "/stream.mjpg", args.rotation)
        self.pose = None
        self.events = []
        self.replay = None
        self.replay_index = 0
        self.replay_running = False
        self.replay_frame = None
        self.last_sequence = -1
        self.last_size = None
        self.last_annotations = None
        self.photo = None
        self.widgets = {}
        self.displayed = {}
        root.title("具身探索监控台 · Embodied AI Monitor")
        width = min(1540, root.winfo_screenwidth() - 40)
        height = min(920, root.winfo_screenheight() - 90)
        root.geometry(f"{width}x{height}+0+0")
        root.minsize(1100, 720)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", background="#1b2b41", foreground=TEXT, borderwidth=0, padding=(12, 8), font=("Microsoft YaHei UI", 9))
        style.map("TButton", background=[("active", "#29455f")])
        self.build()
        self.video.thread.start()
        if not args.no_skeleton:
            self.start_pose_worker()
        self.tick()
        root.after(150, self.poll_events)

    def label(self, parent, text, color=TEXT, size=10, bold=False):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color, anchor="w", justify="left",
                        font=("Microsoft YaHei UI", size, "bold" if bold else "normal"))

    def build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 14))
        self.label(header, "具身探索  /  EMBODIED EXPLORATION", size=18, bold=True).pack(side="left")
        self.mode = self.label(header, "实时 / LIVE", CYAN, 11, True)
        self.mode.pack(side="right")
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        body.grid_columnconfigure(0, weight=65, uniform="columns")
        body.grid_columnconfigure(1, weight=35, uniform="columns")
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=PANEL, padx=16, pady=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = tk.Frame(body, bg=PANEL, padx=16, pady=16)
        right.grid(row=0, column=1, sticky="nsew")
        self.label(left, "AI VISION  /  实时视觉", CYAN, 13, True).pack(fill="x")
        self.camera_status = self.label(left, "视频流连接中 / Connecting to video stream", MUTED, 9)
        self.camera_status.pack(fill="x", pady=(6, 12))
        pose_bar = tk.Frame(left, bg=PANEL)
        pose_bar.pack(fill='x', pady=(0, 6))
        self.skeleton_enabled = tk.BooleanVar(value=not self.args.no_skeleton)
        tk.Checkbutton(pose_bar, text='绿色机械臂骨架 / Skeleton', variable=self.skeleton_enabled,
                       command=self.toggle_skeleton, bg=PANEL, fg=CYAN, selectcolor=BG,
                       activebackground=PANEL, activeforeground=CYAN,
                       font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.pose_status = self.label(left, '骨架连接中 / Starting skeleton worker', MUTED, 9)
        self.pose_status.pack(fill='x', pady=(0, 6))
        self.label(left, 'B/S/E 关节估计 / FK estimates · 轴心精度未标定 / Axis accuracy uncalibrated' if self.args.pose_mode=='fused'
                   else 'J? 关节候选 / Joint candidates · 二维轮廓骨架 / 2D silhouette skeleton', MUTED, 9).pack(fill='x')
        self.canvas = tk.Canvas(left, bg="#040912", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.goal = self.label(left, "观察目标 / Observation target", size=11, bold=True)
        self.goal.pack(fill="x", pady=(14, 6))
        self.motion = self.label(left, "等待运动事件 / Waiting for motion events", AMBER, 10)
        self.motion.pack(fill="x", pady=(0, 6))
        self.position = self.label(left, "指令目标 / Command target    X —    Y —    Z — mm", size=11)
        self.position.pack(fill="x")
        self.label(left, "目标坐标为指令记录 / Target coordinates are command records", MUTED, 9).pack(fill="x", pady=(4, 0))
        self.label(right, "AI MIND & ACTIONS  /  观察与行动", CYAN, 13, True).pack(fill="x", pady=(0, 10))
        for key, title in TITLES.items():
            self.label(right, title, CYAN if key == "next_action" else MUTED, 9, True).pack(fill="x", pady=(5, 2))
            widget = tk.Text(right, width=1, height=4, wrap="word", bg=PANEL, fg=TEXT, relief="flat", borderwidth=0,
                             highlightthickness=0, font=("Microsoft YaHei UI", 9), padx=0, pady=0)
            widget.insert("1.0", "等待 Agent 事件\nWaiting for Agent events")
            widget.configure(state="disabled")
            widget.pack(fill="x")
            self.widgets[key] = widget
        self.label(right, "探索时间线 / Exploration timeline", MUTED, 9, True).pack(fill="x", pady=(10, 5))
        timeline_area = tk.Frame(right, bg=PANEL)
        timeline_area.pack(fill="both", expand=True)
        self.timeline = tk.Text(timeline_area, width=1, bg="#0a1320", fg=TEXT, relief="flat", borderwidth=0,
                                wrap="word", font=("Microsoft YaHei UI", 9), padx=10, pady=8, state="disabled")
        scroll = ttk.Scrollbar(timeline_area, command=self.timeline.yview)
        self.timeline.configure(yscrollcommand=scroll.set)
        self.timeline.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=24, pady=(0, 14))
        ttk.Button(footer, text="实时 / Live", command=self.live).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="打开回放 / Open replay", command=self.open_replay).pack(side="left", padx=(0, 8))
        self.play_button = ttk.Button(footer, text="播放/暂停 / Play/Pause", command=self.toggle_replay)
        self.play_button.pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="保存事件回放 / Save replay", command=self.save_replay).pack(side="left")
        self.footer = self.label(footer, "等待日志 / Waiting for logs", MUTED, 9)
        self.footer.pack(side="right")
        # Reserve header/footer space before the expandable panels on small screens.
        body.pack_forget()
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))

    def render_state(self):
        for key, widget in self.widgets.items():
            value = self.state.summary[key] + "\n" + self.state.summary_en[key]
            if self.displayed.get(key) == value:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            widget.configure(state="disabled")
            self.displayed[key] = value
        width = max(300, self.canvas.winfo_width())
        self.goal.configure(text=self.state.goal + "\n" + self.state.goal_en, wraplength=width)
        self.motion.configure(text=self.state.motion + "\n" + MOTION_EN[self.state.motion],
                              fg=CYAN if self.state.motion == "Agent 已视觉确认停稳" else AMBER, wraplength=width)
        values = "    ".join(axis + " " + ("—" if value is None else f"{value:g}") for axis, value in self.state.target.items())
        self.position.configure(text="指令目标 / Command target    " + values + " mm")

    def append_timeline(self, record):
        stamp = event_time(record)
        when = datetime.fromtimestamp(stamp, LOCAL_TZ).strftime("%H:%M:%S") if stamp else "—"
        kind = record.get("event", "")
        text = record.get("text", record.get("command", record.get("error", "")))
        english = record.get("text_en", "")
        if kind == "waited":
            text = str(record.get("seconds", "")) + " s"
        if kind == "snapshot":
            text = Path(record.get("path", "")).name
        self.timeline.configure(state="normal")
        self.timeline.insert("end", when + "  " + EVENT_LABELS.get(kind, kind) + "\n" + str(text) + ("\n" + english if english else "") + "\n\n")
        # Rendering stays bounded; full records remain in the original JSONL files.
        if int(self.timeline.index("end-1c").split(".")[0]) > 3000:
            self.timeline.delete("1.0", "500.0")
        self.timeline.see("end")
        self.timeline.configure(state="disabled")

    def poll_events(self):
        batch = self.tail.read()
        self.events.extend(batch)
        if self.replay is None:
            for record in batch:
                self.state.apply(record)
                self.append_timeline(record)
            if batch:
                self.render_state()
        self.footer.configure(text=f"{len(self.events)} 事件 / events · UTC+8")
        if self.tail.errors:
            self.footer.configure(text="日志读取异常 / Log read issue · " + self.tail.errors[-1][:90])
        self.root.after(150, self.poll_events)

    def draw_frame(self, frame):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 2 or height < 2:
            return
        ratio = min(width / frame.width, height / frame.height)
        size = max(1, round(frame.width * ratio)), max(1, round(frame.height * ratio))
        resized = frame.resize(size, Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        ox, oy = (width - size[0]) / 2, (height - size[1]) / 2
        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")
        for annotation in self.state.annotations:
            try:
                box = annotation["box"]
                if len(box) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box):
                    continue
                x0, y0, x1, y1 = box
                if x0 >= x1 or y0 >= y1:
                    continue
                coords = (ox + x0*size[0], oy + y0*size[1], ox + x1*size[0], oy + y1*size[1])
                self.canvas.create_rectangle(*coords, outline=CYAN, width=2)
                label = str(annotation.get("label", "")) + " / " + str(annotation.get("label_en", ""))
                self.canvas.create_text(coords[0]+4, max(oy+12, coords[1]-12), text=label, fill=CYAN, anchor="w", font=("Microsoft YaHei UI", 10, "bold"))
            except (KeyError, TypeError, ValueError):
                continue

    def tick(self):
        frame, sequence, received, fps, error = self.video.latest()
        age = time.monotonic() - received if received else float("inf")
        if self.replay is None:
            pose_frame, pose_sequence, pose_received, pose_stats = (
                self.pose.latest() if self.pose else (None, None, 0, {'error': None})
            )
            pose_age = time.monotonic() - pose_received if pose_received else float('inf')
            if not self.skeleton_enabled.get():
                self.pose_status.configure(text='骨架已关闭 / Skeleton off', fg=MUTED)
            elif pose_stats['error']:
                self.pose_status.configure(text='骨架异常 / Skeleton error · ' + pose_stats['error'][:85], fg=AMBER)
            elif pose_frame is not None and pose_age < .75 and age < 1 and not error:
                # Display the exact image used for inference, keeping image and skeleton aligned.
                frame, sequence = pose_frame, pose_sequence
                quality = [item.get('quality_score',0) for item in pose_stats.get('poses',[])]
                quality_text = f" · Q {sum(quality)/len(quality):.2f}" if quality else ''
                detail = f"视觉 / visual {pose_stats['visual_tracks']} · 预测 / predicted {pose_stats['predicted_tracks']} · 丢失 / lost {pose_stats['lost_tracks']}{quality_text}" if self.args.pose_mode=='fused' else f"{pose_stats['arms']} 台 / arms"
                self.pose_status.configure(text=f"自动骨架 / Auto pose · {detail} · {pose_stats['processing_ms']:.0f} ms", fg=CYAN)
            else:
                self.pose_status.configure(text='等待新鲜骨架 / Waiting for fresh pose', fg=AMBER)
            size = self.canvas.winfo_width(), self.canvas.winfo_height()
            annotations = repr(self.state.annotations)
            if frame is not None and (sequence != self.last_sequence or size != self.last_size or annotations != self.last_annotations):
                self.draw_frame(frame)
                self.last_sequence, self.last_size, self.last_annotations = sequence, size, annotations
            if age < 3 and not error:
                self.camera_status.configure(text=f"在线 / Live · {frame.width}×{frame.height} · {fps:.1f} FPS · {age:.2f}s · 旋转 / rotation {self.args.rotation}°", fg=CYAN)
            else:
                self.camera_status.configure(text="视频离线或过期 / Video offline or stale" + (" · " + error[:80] if error else ""), fg=AMBER)
        elif self.replay_running:
            self.pose_status.configure(text='回放留存画面 / Saved-frame replay', fg=MUTED)
            elapsed = self.replay_start_time + time.monotonic() - self.replay_started
            count = 0
            while self.replay_index < len(self.replay) and event_time(self.replay[self.replay_index]) <= elapsed and count < 100:
                record = self.replay[self.replay_index]
                self.state.apply(record)
                self.append_timeline(record)
                path = record.get("path") if record.get("event") == "snapshot" else record.get("frame")
                if path:
                    try:
                        with Image.open(path) as saved:
                            self.replay_frame = saved.convert("RGB").rotate(self.args.rotation, expand=True)
                    except (OSError, ValueError):
                        self.camera_status.configure(text="留存画面缺失 / Saved frame missing", fg=AMBER)
                self.replay_index += 1
                count += 1
            self.render_state()
            if self.replay_frame is not None:
                self.draw_frame(self.replay_frame)
            if self.replay_index == len(self.replay):
                self.replay_running = False
                self.mode.configure(text="回放完成 / REPLAY COMPLETE", fg=AMBER)
                self.camera_status.configure(text="回放完成 · 留存画面 / Replay complete · Saved frame", fg=MUTED)
        self.root.after(30, self.tick)

    def clear_timeline(self):
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.configure(state="disabled")

    def live(self):
        self.replay = None
        self.replay_running = False
        self.state = MonitorState()
        self.clear_timeline()
        for record in sorted(self.events, key=event_time):
            self.state.apply(record)
        for record in sorted(self.events, key=event_time)[-150:]:
            self.append_timeline(record)
        self.mode.configure(text="实时 / LIVE", fg=CYAN)
        self.last_sequence = -1
        self.render_state()

    def open_replay(self):
        path = filedialog.askopenfilename(title="打开事件回放 / Open event replay", initialdir=self.args.events, filetypes=[("JSONL event log", "*.jsonl")])
        if not path:
            return
        try:
            records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if not records or not all(isinstance(r, dict) and isinstance(r.get("event"), str) for r in records):
                raise ValueError("Empty or invalid event log")
            self.replay = sorted(records, key=event_time)
        except (OSError, ValueError) as exc:
            self.footer.configure(text="回放错误 / Replay error · " + str(exc)[:80])
            return
        self.replay_index = 0
        self.replay_frame = None
        self.replay_running = True
        self.replay_start_time = event_time(self.replay[0])
        self.replay_started = time.monotonic()
        self.state = MonitorState()
        self.clear_timeline()
        self.canvas.delete("all")
        self.mode.configure(text="事件回放 / EVENT REPLAY", fg=AMBER)
        self.camera_status.configure(text="回放留存画面 / Replaying saved frames", fg=MUTED)
        self.render_state()

    def toggle_replay(self):
        if self.replay is None:
            return
        if self.replay_running:
            self.replay_start_time += time.monotonic() - self.replay_started
        else:
            if self.replay_index == len(self.replay):
                self.replay_index = 0
                self.replay_start_time = event_time(self.replay[0])
                self.state = MonitorState()
                self.clear_timeline()
            self.replay_started = time.monotonic()
        self.replay_running = not self.replay_running
        self.mode.configure(text="事件回放 / EVENT REPLAY" if self.replay_running else "回放暂停 / REPLAY PAUSED", fg=AMBER)

    def save_replay(self):
        destination = filedialog.asksaveasfilename(title="保存事件回放 / Save event replay", initialdir=self.args.events / "replays", defaultextension=".jsonl", filetypes=[("JSONL event log", "*.jsonl")])
        if not destination:
            return
        try:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in sorted(self.events, key=event_time)), encoding="utf-8")
            self.footer.configure(text="已保存 / Saved · " + path.name)
        except OSError as exc:
            self.footer.configure(text="保存失败 / Save failed · " + str(exc)[:80])

    def start_pose_worker(self):
        if self.pose is not None:
            return
        from cv_pipeline.monitor_pose import PoseWorker

        pose_log = self.args.events / 'vision' / datetime.now(timezone.utc).strftime('poses-%Y%m%dT%H%M%S%fZ.jsonl')
        self.pose = PoseWorker(
            self.video, self.args.pose_library, pose_log, enabled=True,
            fused=self.args.pose_mode == 'fused', state_directory=self.args.events,
        )
        self.pose.thread.start()

    def close(self):
        if self.pose is not None:
            self.pose.stop.set()
        self.video.stop.set()
        self.root.destroy()

    def toggle_skeleton(self):
        if self.skeleton_enabled.get():
            self.start_pose_worker()
            self.pose.enabled.set()
        elif self.pose is not None:
            self.pose.enabled.clear()
        self.last_sequence = -1


def main(argv=None, *, default_skeleton=True):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="http://127.0.0.1:8766")
    parser.add_argument("--events", type=Path, default=Path(__file__).resolve().parents[1] / ".runtime")
    parser.add_argument("--rotation", type=int, choices=[0, 90, 180, 270], default=180, help="Counterclockwise display rotation, confirmed by user")
    parser.add_argument('--pose-library', type=Path, default=Path(__file__).resolve().parents[2] / 'Mr-Robot-Arm',
                        help='Repository containing mr_robot_desktop/skeleton.py')
    overlay = parser.add_mutually_exclusive_group()
    overlay.add_argument('--no-skeleton', action='store_true', default=not default_skeleton, help='Display camera images with the pose overlay disabled')
    overlay.add_argument('--skeleton', dest='no_skeleton', action='store_false', help='Enable the optional CV pose overlay')
    parser.add_argument('--pose-mode', choices=('fused','silhouette'), default='fused')
    args = parser.parse_args(argv)
    args.events.mkdir(parents=True, exist_ok=True)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    Monitor(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
