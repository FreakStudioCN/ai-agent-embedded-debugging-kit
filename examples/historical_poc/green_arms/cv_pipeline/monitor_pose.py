"""Latest-frame-only skeleton processing for the read-only Tk monitor."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
from datetime import datetime, timezone
import ast
import importlib
import json
from pathlib import Path
import sys
import threading
import time

from PIL import Image
from monitor_core import EventTail, MOTION, event_time


class CameraMotionGuard:
    def __init__(self, directory):
        self.tail = EventTail(directory)
        self.command = None
        self.moved_at = 0
        self.generation = 0
        self.blocked = False

    def update(self):
        for record in self.tail.read():
            command = str(record.get('command','')).strip().upper()
            if (record.get('event')=='sending' and command.startswith(('G0','G1','G28'))
                    and MOTION.match(command) and event_time(record)>=self.moved_at):
                self.command = command
                self.moved_at = event_time(record)
                self.generation += 1
                self.blocked = True
            elif (record.get('event')=='motion_verified' and command==self.command
                  and record.get('frame') and event_time(record)>=self.moved_at):
                self.blocked = False
        return self.blocked,self.generation


class CommandModel:
    """Read actual UART logs and reproduce the board's smoothstep command model."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = None
        self.offset = 0
        self.counts = {}
        self.plan = None

    def sample(self, wall_time):
        paths = list(self.directory.glob('device-COM8-*.jsonl'))
        if paths:
            path = max(paths, key=lambda item: item.stat().st_mtime)
            if path != self.path:
                self.path, self.offset = path, 0
                self.counts, self.plan = {}, None
            with path.open('r', encoding='utf-8') as stream:
                stream.seek(self.offset)
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith('\n'):
                        break
                    self.offset = stream.tell()
                    record = json.loads(line)
                    if record.get('event') == 'device_received':
                        for text in record.get('text','').splitlines():
                            if 'command_counts' not in text or '{' not in text:
                                continue
                            try:
                                state = ast.literal_eval(text[text.index('{'):])
                            except (ValueError,SyntaxError):
                                continue
                            values = state.get('command_counts',{})
                            if state.get('enabled') and all(values.get(index) and all(type(v) is int for v in values[index]) for index in (1,2)):
                                self.counts = {index:list(values[index]) for index in (1,2)}
                                self.plan = None
                    if record.get('event') == 'device_sent' and self.counts:
                        try:
                            tree = ast.parse(record.get('payload','').strip())
                            for call in ast.walk(tree):
                                if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr!='run_segment':
                                    continue
                                targets = {1:list(ast.literal_eval(call.args[0])),2:list(ast.literal_eval(call.args[1]))}
                                speed = next((ast.literal_eval(k.value) for k in call.keywords if k.arg=='speed'),6)
                                scales = {1:(.43135,.43939,.47088),2:(.56,.44,.52)}
                                distance = max(abs(targets[a][j]-self.counts[a][j])*scales[a][j] for a in (1,2) for j in range(3))
                                duration = max(.001,__import__('math').ceil(1500*distance/speed)/1000)
                                started = datetime.fromisoformat(record['time']).timestamp()
                                self.plan = started,duration,{a:list(v) for a,v in self.counts.items()},targets
                        except (ValueError,SyntaxError,TypeError,IndexError,ZeroDivisionError):
                            self.plan = None
        if self.plan:
            started,duration,origins,targets = self.plan
            u = max(0,min(1,(wall_time-started)/duration))
            progress = u*u*(3-2*u)
            return {a:[origins[a][j]+(targets[a][j]-origins[a][j])*progress for j in range(3)] for a in (1,2)}
        return self.counts


class PoseWorker:
    def __init__(self, video, library, log_path=None, enabled=True, fused=False, state_directory=None):
        self.video = video
        self.library = Path(library)
        self.log_path = Path(log_path) if log_path else None
        self.fused = fused
        self.command_model = CommandModel(state_directory) if state_directory else None
        self.camera_guard = CameraMotionGuard(state_directory) if fused and state_directory else None
        self.stop = threading.Event()
        self.enabled = threading.Event()
        if enabled:
            self.enabled.set()
        self.lock = threading.Lock()
        self.result = (None, -1, 0, {'error': '', 'arms': 0, 'processing_ms': 0})
        self.thread = threading.Thread(target=self.run, daemon=True, name='green-arm-skeleton')

    def latest(self):
        with self.lock:
            return self.result

    def run(self):
        journal = None
        try:
            import cv2
            import numpy as np
            if self.library.is_dir():
                sys.path.insert(0, str(self.library.resolve()))
            engine = importlib.import_module('mr_robot_desktop.skeleton')
            fusion = importlib.import_module('mr_robot_desktop.fused_pose') if self.fused else None
            tracker = fusion.FusedTracker() if fusion else None
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                journal = self.log_path.open('a', encoding='utf-8', buffering=1)
            last_sequence = -1
            camera_generation = -1
            while not self.stop.is_set():
                frame, sequence, received, _, error = self.video.latest()
                if (not self.enabled.is_set() or frame is None or error or
                        sequence == last_sequence or time.monotonic()-received > 1):
                    self.stop.wait(.01)
                    continue
                started = time.perf_counter()
                if self.camera_guard:
                    blocked,generation = self.camera_guard.update()
                    if generation != camera_generation:
                        tracker.reset()
                        camera_generation = generation
                    if blocked:
                        with self.lock:
                            self.result = None,-1,0,{'error':'相机机械臂运动后等待视觉停稳 / Awaiting camera settling verification','arms':0,'processing_ms':0}
                        self.stop.wait(.03)
                        continue
                source = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)
                if tracker:
                    wall_time = time.time()-(time.monotonic()-received)
                    counts = self.command_model.sample(wall_time) if self.command_model else {}
                    arms = tracker.update(source,received,counts)
                    annotated = fusion.draw_fused(source,arms)
                else:
                    arms = engine.detect_skeletons(source)
                    annotated = engine.draw_skeletons(source, arms)
                image = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
                elapsed = (time.perf_counter()-started)*1000
                stats = {'error': '', 'arms': len(arms), 'processing_ms': elapsed,
                         'poses': arms,
                         'joint_candidates': sum(len(arm.get('joint_candidates',[])) for arm in arms),
                         'pose_mode': 'fused' if tracker else 'silhouette',
                         'visual_tracks': sum(arm.get('status')=='visual_constrained' for arm in arms),
                         'predicted_tracks': sum(arm.get('status')=='model_predicted' for arm in arms),
                         'lost_tracks': sum(arm.get('status')=='lost' for arm in arms)}
                if journal:
                    journal.write(json.dumps({
                        'processed_utc': datetime.now(timezone.utc).isoformat(),
                        'source_sequence': sequence, 'source_received_monotonic': received,
                        'processing_ms': elapsed,
                        'arms': [{key: value for key, value in arm.items() if key != 'contour'} for arm in arms]
                        ,'coordinate_frame': 'camera-view-%s'%camera_generation if tracker else 'image',
                        'cross_view_transform_verified':False
                    }) + '\n')
                with self.lock:
                    self.result = image, sequence, received, stats
                last_sequence = sequence
        except Exception as error:
            with self.lock:
                self.result = None, -1, 0, {'error': str(error), 'arms': 0, 'processing_ms': 0}
        finally:
            if journal:
                journal.close()
