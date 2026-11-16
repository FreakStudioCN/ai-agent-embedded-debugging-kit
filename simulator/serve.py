"""Serve the downloaded robot simulator locally, including ES modules."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
from urllib.parse import urlsplit
from urllib.request import urlopen


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".mjs": "text/javascript", ".js": "text/javascript",
                      ".stl": "application/octet-stream", ".step": "application/step"}

    def do_GET(self):
        try:
            if urlsplit(self.path).path == "/api/camera-status":
                try:
                    with urlopen("http://127.0.0.1:8766/api/status", timeout=2) as response:
                        status = json.loads(response.read(65536))
                except (OSError, ValueError):
                    status = {"healthy": False, "error": "Camera service unavailable"}
                data = json.dumps(status).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]) not in ("200", "304"):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    server = LocalServer(("127.0.0.1", args.port), partial(Handler, directory=str(root)))
    print("RobotArm simulator http://127.0.0.1:%d/" % args.port, flush=True)
    print("Press Ctrl+C to stop", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
