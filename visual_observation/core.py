"""Read-only event, video-stream and presentation state for the monitor."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from datetime import datetime
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.request import urlopen

from PIL import Image

MOTION = re.compile(r"^(?:G0*0|G0*1|G28|M3|M5)(?=[A-Z\s]|$)")
AXIS = re.compile(r"([XYZ])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


def event_time(record):
    value = record.get("time",record.get("timestamp_utc"))
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0.0


class EventTail:
    """Incremental byte offsets preserve incomplete UTF-8/JSON lines."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.offsets = {}
        self.errors = []
        self.seen = set()

    def read(self):
        records = []
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                previous_identity, offset = self.offsets.get(path, (identity, 0))
                if previous_identity != identity or stat.st_size < offset:
                    offset = 0
                with path.open("rb") as stream:
                    stream.seek(offset)
                    for _ in range(500):
                        line_start = stream.tell()
                        line = stream.readline(1024 * 1024 + 1)
                        if not line or not line.endswith(b"\n"):
                            break
                        offset = stream.tell()
                        try:
                            record = json.loads(line)
                            if isinstance(record, dict) and isinstance(record.get("event"), str):
                                origin = record.get("_origin")
                                if not isinstance(origin, str):
                                    origin = f"{path.resolve()}:{line_start}:{hashlib.sha256(line).hexdigest()}"
                                    record["_origin"] = origin
                                if origin in self.seen:
                                    continue
                                self.seen.add(origin)
                                record["_log"] = str(path)
                                records.append(record)
                        except (ValueError, UnicodeError) as exc:
                            self.errors.append(f"{path.name} at {offset}: {exc}")
                self.offsets[path] = identity, offset
            except OSError as exc:
                self.errors.append(str(exc))
        return sorted(records, key=event_time)


class MonitorState:
    def __init__(self):
        self.target = {axis: None for axis in "XYZ"}
        self.motion = "等待运动事件"
        self.command = "—"
        self.motion_command = None
        self.summary = {key: "等待 Agent 事件" for key in ("observation", "interpretation", "next_action", "execution", "result")}
        self.summary_en = {key: "Waiting for Agent events" for key in self.summary}
        self.goal = "等待观察目标"
        self.goal_en = "Waiting for an observation target"
        self.annotations = []
        self.last_time = 0

    def apply(self, record):
        timestamp = event_time(record)
        if timestamp < self.last_time:
            return
        self.last_time = timestamp
        kind = record.get("event")
        text = record.get("text", "")
        if kind == "experiment_started":
            self.summary = {key: "等待本次实验事件" for key in self.summary}
            self.summary_en = {key: "Waiting for this experiment's events" for key in self.summary}
            self.annotations = []
            self.goal = "本次实机演示"
            self.goal_en = "Current physical demonstration"
        if kind in self.summary and isinstance(text, str):
            self.summary[kind] = text
            self.summary_en[kind] = str(record.get("text_en", "English summary not provided"))
        if record.get("target"):
            self.goal = str(record["target"])
            self.goal_en = str(record.get("target_en", "English target not provided"))
        if "annotations" in record and isinstance(record["annotations"], list):
            self.annotations = record["annotations"]
        if kind == "sending":
            command = str(record.get("command", "")).strip().upper()
            self.command = command
            self.summary["execution"] = command + " · 指令已发送"
            self.summary_en["execution"] = command + " · Command sent"
            if MOTION.match(command):
                self.motion_command = command
                self.motion = "已发送 · 实际运动待确认"
                self.annotations = []
                if command.startswith("G28"):
                    self.target = {axis: None for axis in "XYZ"}
                else:
                    self.target.update({axis: float(value) for axis, value in AXIS.findall(command)})
        elif kind == "acknowledged":
            command = str(record.get("command", "")).strip().upper()
            self.summary["execution"] = command + " · 控制器已回复 ok"
            self.summary_en["execution"] = command + " · Controller acknowledged"
            if command == self.motion_command:
                self.motion = "已回复 · 实际运动待确认"
        elif kind == "motion_verified":
            command = str(record.get("command", "")).strip().upper()
            if command == self.motion_command and record.get("frame"):
                self.motion = "Agent 已视觉确认停稳"
                self.summary["result"] = text
                self.summary_en["result"] = str(record.get("text_en", "English summary not provided"))
        elif kind in ("timeout", "error", "interrupted"):
            self.motion = "异常 · 实际运动状态未知"
            self.summary["execution"] = str(record.get("error", kind))
            self.summary_en["execution"] = str(record.get("error", kind))
        elif kind == "closed":
            self.summary["execution"] += "\n串口会话已关闭"
            self.summary_en["execution"] += "\nSerial session closed"


def jpeg_frames(response):
    """Consume MJPEG continuously without accumulating a queue of old frames."""
    buffer = bytearray()
    read = getattr(response, "read1", response.read)
    while True:
        chunk = read(65536)
        if not chunk:
            return
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                buffer[:] = buffer[-1:]
                break
            if start:
                del buffer[:start]
            end = buffer.find(b"\xff\xd9", 2)
            if end < 0:
                break
            yield bytes(buffer[:end + 2])
            del buffer[:end + 2]
        if len(buffer) > 20 * 1024 * 1024:
            raise ValueError("MJPEG frame buffer exceeds 20 MiB")


class VideoReader:
    def __init__(self, url, rotation=180):
        self.url = url
        self.rotation = rotation
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0
        self.received_at = 0
        self.fps = 0
        self.error = "正在连接视频流"
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                with urlopen(self.url, timeout=3) as response:
                    start, count = time.monotonic(), 0
                    for data in jpeg_frames(response):
                        if self.stop.is_set():
                            return
                        with Image.open(BytesIO(data)) as decoded:
                            frame = decoded.convert("RGB")
                        if self.rotation:
                            frame = frame.rotate(self.rotation, expand=True)
                        now = time.monotonic()
                        count += 1
                        with self.lock:
                            self.frame = frame
                            self.sequence += 1
                            self.received_at = now
                            self.error = ""
                            if now - start >= 1:
                                self.fps = count / (now - start)
                        if now - start >= 3:
                            start, count = now, 0
            except (OSError, ValueError) as exc:
                with self.lock:
                    self.error = str(exc)
                self.stop.wait(1)

    def latest(self):
        with self.lock:
            return self.frame, self.sequence, self.received_at, self.fps, self.error
