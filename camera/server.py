"""Local USB camera MJPEG server using Python stdlib and FFmpeg.

Run: python camera_server.py
Browser: http://127.0.0.1:8766/   Snapshot: /snapshot.jpg
The camera is opened once; all browser/agent clients share the latest frame.
"""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import argparse
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit


PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>机械臂摄像头</title>
<style>
:root{color-scheme:dark;font:16px system-ui,"Microsoft YaHei",sans-serif}
*{box-sizing:border-box}body{margin:0;background:#10141c;color:#e8edf6}
main{max-width:1440px;margin:auto;padding:28px}header,.bar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
h1{margin:0 0 6px;font-size:25px}p{margin:0;color:#9baabd;line-height:1.6}
.status{font-size:14px;color:#77dfb0}.viewport{margin-top:24px;background:#05070a;border:1px solid #283344;border-radius:14px;overflow:hidden;min-height:240px;display:grid;place-items:center}
img{display:block;width:100%;max-height:76vh;object-fit:contain}.bar{margin-top:18px}
button,a{font:inherit;cursor:pointer;border:1px solid #35455d;border-radius:8px;background:#1e2b3e;color:#eef4ff;padding:10px 16px;text-decoration:none}
button:hover,a:hover{background:#2c405b}.links{display:flex;gap:10px;flex-wrap:wrap}small{color:#9baabd}
</style><main><header><div><h1>机械臂摄像头</h1><p>实时查看工作区域</p></div><span id="status" class="status">正在连接…</span></header>
<div class="viewport"><img id="feed" src="/stream.mjpg" alt="摄像头实时画面"></div>
<div class="bar"><div class="links"><button id="toggle">暂停画面</button><a href="/snapshot.jpg" target="_blank" rel="noopener">查看当前照片</a><button id="retry">重新连接</button></div><small id="detail"></small></div>
<p style="margin-top:20px;font-size:13px">暂停只停止当前页面显示，摄像头仍保持采集。</p></main>
<script>
const feed=document.querySelector('#feed'),toggle=document.querySelector('#toggle');let paused=false;
function reconnect(){paused=false;feed.src='/stream.mjpg?t='+Date.now();toggle.textContent='暂停画面'}
toggle.onclick=()=>{if(paused){reconnect()}else{feed.removeAttribute('src');paused=true;toggle.textContent='继续播放'}};
document.querySelector('#retry').onclick=reconnect;
feed.onerror=()=>{document.querySelector('#status').textContent='画面连接中断，请重新连接'};
async function update(){try{const r=await fetch('/api/status',{cache:'no-store'}),s=await r.json();document.querySelector('#status').textContent=s.healthy?(paused?'已暂停显示 · 摄像头在线':'● 摄像头在线'):'摄像头离线';document.querySelector('#detail').textContent=s.device+' · '+s.fps+' FPS · 已采集 '+s.frame_count+' 帧'}catch(e){document.querySelector('#status').textContent='服务连接中断'}}
update();setInterval(update,2000);
</script></html>""".encode("utf-8")


class Camera:
    def __init__(self, ffmpeg, device, fps, width):
        self.device, self.fps = device, fps
        self.condition = threading.Condition()
        self.frame = None
        self.frame_count = 0
        self.last_frame_at = 0
        self.last_frame_utc = None
        self.stopped = False
        self.error = None
        self.logs = deque(maxlen=12)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
               "-f", "dshow", "-i", "video=" + device, "-an",
               "-vf", "fps=%d,scale=%d:-2" % (fps, width),
               "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.reader = threading.Thread(target=self._capture, daemon=True)
        self.logger = threading.Thread(target=self._logs, daemon=True)
        self.logger.start()
        self.reader.start()

    def _logs(self):
        for line in self.process.stderr:
            self.logs.append(line.decode("utf-8", errors="replace").strip())

    def _capture(self):
        buffer = bytearray()
        try:
            while not self.stopped:
                chunk = self.process.stdout.read(65536)
                if not chunk:
                    break
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
                    frame = bytes(buffer[:end + 2])
                    del buffer[:end + 2]
                    with self.condition:
                        self.frame = frame
                        self.frame_count += 1
                        self.last_frame_at = time.monotonic()
                        self.last_frame_utc = datetime.now(timezone.utc).isoformat()
                        self.condition.notify_all()
                if len(buffer) > 8 * 1024 * 1024:
                    raise RuntimeError("JPEG capture buffer overflow")
        except Exception as exc:
            self.error = str(exc)
        finally:
            with self.condition:
                if not self.stopped and not self.error:
                    self.error = "Camera capture ended"
                self.stopped = True
                self.condition.notify_all()

    def get_frame(self, after=0, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.stopped:
                if self.frame_count > after and time.monotonic() - self.last_frame_at < 5:
                    return self.frame, self.frame_count
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
        return None, after

    def status(self):
        with self.condition:
            age = time.monotonic() - self.last_frame_at if self.frame else None
            return {"device": self.device, "fps": self.fps, "frame_count": self.frame_count,
                    "healthy": not self.stopped and age is not None and age < 5,
                    "frame_age_seconds": round(age, 3) if age is not None else None,
                    "frame_utc": self.last_frame_utc, "error": self.error,
                    "capture_returncode": self.process.poll(), "capture_logs": list(self.logs)}

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.logger.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


class CameraHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Streaming reconnects and health checks do not need access logging.
        if args and str(args[1] if len(args) > 1 else "") not in ("200",):
            super().log_message(format, *args)

    def _send(self, code, content_type, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.connection.settimeout(10)
        try:
            path = urlsplit(self.path).path
            if path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif path == "/api/status":
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(self.server.camera.status(), ensure_ascii=False).encode("utf-8"))
            elif path == "/snapshot.jpg":
                frame, seq = self.server.camera.get_frame()
                if frame is None:
                    self._send(503, "text/plain", b"No fresh camera frame available")
                else:
                    self._send(200, "image/jpeg", frame, {"X-Frame-Id": seq})
            elif path == "/stream.mjpg":
                frame, seq = self.server.camera.get_frame()
                if frame is None:
                    self._send(503, "text/plain", b"No fresh camera frame available")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                while frame is not None:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                    self.wfile.flush()
                    frame, seq = self.server.camera.get_frame(after=seq)
            else:
                self._send(404, "text/plain", b"Not found")
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            self.close_connection = True


def reconnect_camera(server, args, stopped):
    """Recover an ended capture while keeping one owner per physical camera."""
    while not stopped.wait(1):
        previous = server.camera
        if not previous.stopped:
            continue
        previous.close()
        replacement = None
        try:
            replacement = Camera(args.ffmpeg,args.device,args.fps,args.width)
            frame,_ = replacement.get_frame(timeout=3)
            if frame is None:
                raise RuntimeError('Camera reconnect produced no fresh frame')
            server.camera = replacement
            print('Camera capture reconnected',flush=True)
        except (OSError,RuntimeError) as error:
            if replacement:
                replacement.close()
            print('Camera reconnect failed: '+str(error),flush=True)
            stopped.wait(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--device", default="2M")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument('--reconnect',action='store_true',help='Retry ended capture without opening a second camera owner')
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("FFmpeg not found; add to PATH or pass --ffmpeg")
    if not 1 <= args.fps <= 60 or not 160 <= args.width <= 3840 or args.width % 2:
        parser.error("fps must be 1..60; width must be even, in 160..3840")
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    # Bind before starting capture, so an occupied port does not grab the camera.
    server = CameraHTTPServer((args.host, args.port), Handler)
    camera = None
    stopped = threading.Event()
    watcher = None
    try:
        camera = Camera(args.ffmpeg, args.device, args.fps, args.width)
        server.camera = camera
        frame, _ = camera.get_frame(timeout=12)
        if frame is None:
            raise RuntimeError("No camera frame: " + "; ".join(camera.logs))
        print("Camera ready: %s (%d FPS)" % (args.device, args.fps), flush=True)
        print("Browser: http://%s:%d/" % (args.host, args.port), flush=True)
        print("Snapshot: /snapshot.jpg | Status: /api/status", flush=True)
        if args.reconnect:
            watcher = threading.Thread(target=reconnect_camera,args=(server,args,stopped),daemon=True)
            watcher.start()
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        if watcher:
            watcher.join(timeout=15)
        server.server_close()
        if camera is not None:
            server.camera.close()


if __name__ == "__main__":
    main()
