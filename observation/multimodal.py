"""Fetch actual JPEG bytes plus acquisition metadata; no LLM provider required."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from .contracts import FramePacket
def snapshot(camera, output):
    with urlopen(camera.rstrip("/") + "/snapshot.jpg", timeout=10) as response:
        image = response.read()
    if not image.startswith(b"\xff\xd8"): raise ValueError("Camera did not return JPEG data")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    stamp = datetime.now(timezone.utc).isoformat()
    packet = FramePacket(stamp, camera, stamp, str(output.resolve()))
    output.with_suffix(".json").write_text(json.dumps({**packet.to_dict(), "timestamp_basis": "host_received_at; not sensor exposure time"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return packet
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="http://127.0.0.1:8766")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.camera, args.output).to_dict(), ensure_ascii=False))
if __name__ == "__main__": main()
