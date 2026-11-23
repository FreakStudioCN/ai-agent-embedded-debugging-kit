"""Append the Agent's actual public decision summaries to the monitor log."""

import sys as _sys
from pathlib import Path as _Path
_WORKSPACE_ROOT = next(p for p in _Path(__file__).resolve().parents if (p / "package.json").is_file())
if str(_WORKSPACE_ROOT) not in _sys.path: _sys.path.insert(0, str(_WORKSPACE_ROOT))
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

DEFAULT_LOG = _WORKSPACE_ROOT / ".runtime" / "agent-events.jsonl"


def emit(event, text, path=DEFAULT_LOG, **fields):
    record = {"time": datetime.now(timezone.utc).isoformat(), "event": event,
              "event_id": uuid.uuid4().hex, "source": "codex", "text": text, **fields}
    encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("Incomplete event write")
    finally:
        os.close(descriptor)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, choices=["observation", "interpretation", "next_action", "result", "motion_verified", "note"])
    parser.add_argument("--text", required=True)
    parser.add_argument("--text-en", required=True, help="English version of the actual public summary")
    parser.add_argument("--target")
    parser.add_argument("--command", help="Command whose physical settling was visually checked")
    parser.add_argument("--frame", help="Evidence frame path")
    parser.add_argument("--data", type=Path, help="Additional structured fields in a JSON file")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    fields = json.loads(args.data.read_text(encoding="utf-8-sig")) if args.data else {}
    if not isinstance(fields, dict) or set(fields) & {"time", "event", "text", "source", "event_id"}:
        parser.error("data must be an object of additional event fields")
    for key in ("target", "command", "frame"):
        value = getattr(args, key)
        if value:
            fields[key] = value
    fields["text_en"] = args.text_en
    if args.event == "motion_verified" and not (fields.get("command") and fields.get("frame")):
        parser.error("motion_verified requires command and evidence frame")
    print(json.dumps(emit(args.event, args.text, args.log, **fields), ensure_ascii=False))


if __name__ == "__main__":
    main()
