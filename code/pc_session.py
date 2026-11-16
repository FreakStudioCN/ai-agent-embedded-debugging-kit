"""Persistent PC UART session for camera-guided Codex operation.

Input is a G/M command, a JSON request, or a local :action. Connecting only
opens the port. Physical completion remains a separate visual observation.
Run in an interactive terminal with stdin kept open.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from urllib.request import urlopen

from pc_control import PCUART
from robot_arm import ArmError, ArmTimeout, RobotArm


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("settle/wait must be a number")
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= 60:
        raise ValueError("settle/wait must be finite and in 0..60 seconds")
    return seconds


def request(line):
    """Validate the whole request before any UART write."""
    if line.startswith("{"):
        data = json.loads(line)
        if not isinstance(data, dict) or set(data) - {"command", "settle"}:
            raise ValueError("JSON accepts command and optional settle only")
        command = data.get("command")
        if not isinstance(command, str):
            raise ValueError("command must be a string")
        return command, duration(data.get("settle", 0))
    return line, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM23")
    parser.add_argument("--timeout", type=int, default=120000, help="UART acknowledgement timeout in ms")
    parser.add_argument("--camera", default="http://127.0.0.1:8766")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / ".runtime")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = args.output_dir / ("session-" + session_id + ".jsonl")
    uart = None
    with log_path.open("x", encoding="utf-8") as log:
        def emit(event, **fields):
            record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
            encoded = json.dumps(record, ensure_ascii=False)
            log.write(encoded + "\n")
            log.flush()
            print(encoded, flush=True)

        try:
            uart = PCUART(args.port)
            original_write = uart.write
            sent = bytearray()

            def logged_write(data):
                count = original_write(data)
                if isinstance(count, int) and 0 < count <= len(data):
                    sent.extend(data[:count])
                    if sent.endswith(b"\n"):
                        emit("sending", command=sent.decode("ascii").strip())
                        sent.clear()
                return count

            uart.write = logged_write
            arm = RobotArm(uart, timeout_ms=args.timeout)
            emit("ready", port=args.port, log=str(log_path), position="unknown")
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    if line == ":quit":
                        break
                    if line == ":status":
                        emit("status", pending=arm.pending, position="unknown", physical_completion="unverified")
                    elif line == ":await":
                        response = arm.wait_done()
                        emit("ack_wait", response=response, pending=arm.pending, physical_completion="unverified")
                    elif line.startswith(":wait "):
                        seconds = duration(line.split(maxsplit=1)[1])
                        time.sleep(seconds)
                        emit("waited", seconds=seconds, physical_completion="unverified")
                    elif line == ":snapshot":
                        with urlopen(args.camera.rstrip("/") + "/snapshot.jpg", timeout=8) as response:
                            frame_id = response.headers.get("X-Frame-Id")
                            data = response.read(20 * 1024 * 1024 + 1)
                        if len(data) > 20 * 1024 * 1024 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                            raise ValueError("camera returned an invalid or oversized JPEG")
                        path = args.output_dir / ("frame-" + str(time.time_ns()) + ".jpg")
                        path.write_bytes(data)
                        emit("snapshot", path=str(path.resolve()), frame_id=frame_id)
                    elif line.startswith(":"):
                        raise ValueError("Actions: :status, :snapshot, :wait SECONDS, :await, :quit")
                    else:
                        command, settle = request(line)
                        response = arm.command(command)
                        emit("acknowledged", command=command, response=response, physical_completion="unverified")
                        if settle:
                            time.sleep(settle)
                            emit("waited", seconds=settle, physical_completion="unverified")
                except ArmTimeout as exc:
                    emit("timeout", error=str(exc), pending=arm.pending, next_action=":await")
                except (ArmError, OSError, ValueError) as exc:
                    emit("error", error=str(exc), pending=arm.pending)
        except KeyboardInterrupt:
            emit("interrupted", physical_completion="unverified")
        finally:
            if uart is not None:
                uart.deinit()
            emit("closed", physical_completion="unverified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
