"""Read-only FFmpeg recording and timestamp-aligned experiment exports.

No camera device or serial port is opened by default. Capture subscribes to
the shared MJPEG service and records the native monitor window.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time

from monitor_core import EventTail, event_time

ROOT = Path(__file__).resolve().parent
TITLE = "具身探索监控台 · Embodied AI Monitor"
LABELS = {"observation": "观察 / Observation", "interpretation": "判断 / Interpretation",
          "next_action": "决策 / Next action", "sending": "指令 / Command",
          "acknowledged": "控制器回复 / Controller acknowledgement",
          "motion_verified": "视觉确认停稳 / Visually settled", "result": "结果 / Result"}


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    start = float(stream.get("start_time", data["format"].get("start_time", 0)))
    duration = stream.get("duration")
    if duration is None:
        # Matroska duration with epoch PTS includes the absolute start.
        duration = float(data["format"].get("duration", 0)) - start
    return {"start": start, "duration": float(duration), "width": stream["width"],
            "height": stream["height"], "codec": stream["codec_name"],
            "frame_rate": stream.get("avg_frame_rate"), "probe": data}


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def capture(args):
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    tail = EventTail(args.events)
    # Preserve context separately. Historical summaries stay distinguishable.
    context = tail.read()
    while True:
        more = tail.read()
        if not more:
            break
        context.extend(more)
    (folder / "context.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in context), encoding="utf-8")
    usb_only = getattr(args, "usb_only", False)
    manifest = {"schema": "robot-experiment/v1", "started_utc": utc(),
                "clock": "Host UTC packet receipt timestamps in Matroska PTS",
                "sync_limits": "Software receipt timing. USB exposure and network latency are uncalibrated. External files require a measured offset.",
                "rotation": args.rotation, "sources": {}, "state": "recording",
                "external_pending": not usb_only and not bool(args.external), "pid": __import__("os").getpid()}
    session_start = datetime.fromisoformat(manifest["started_utc"]).timestamp()
    jobs = []
    reconnect = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_at_eof", "1",
                 "-reconnect_on_http_error", "4xx,5xx", "-reconnect_delay_max", "10",
                 "-reconnect_max_retries", "20", "-reconnect_delay_total_max", "60"]
    specs = [("vision", ["-f", "mpjpeg", *reconnect, "-use_wallclock_as_timestamps", "1", "-i", args.camera.rstrip("/") + "/stream.mjpg"], ["-c:v", "copy"])]
    if not usb_only:
        specs.append(("monitor", ["-f", "gdigrab", "-framerate", str(args.fps), "-draw_mouse", "0",
                          "-use_wallclock_as_timestamps", "1", "-i", "title=" + args.window],
              ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2", "-pix_fmt", "yuv420p",
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]))
    if args.external:
        if args.external.startswith("dshow:"):
            source = ["-f", "dshow", "-use_wallclock_as_timestamps", "1", "-i", "video=" + args.external[6:]]
        else:
            source = [*(reconnect if args.external.startswith(('http://','https://')) else []),
                      "-use_wallclock_as_timestamps", "1", "-i", args.external]
        specs.append(("external", source, ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-threads", "2"]))
    save_json(folder / "manifest.json", manifest)
    try:
        for name, inputs, encoder in specs:
            output = folder / (name + ".mkv")
            progress = ["-stats_period", "0.25", "-progress", str(folder / (name + "-progress.txt"))]
            command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", *progress, "-thread_queue_size", "128",
                       *inputs, "-map", "0:v:0", "-an", "-copyts", "-fps_mode", "passthrough",
                       *encoder, "-avoid_negative_ts", "disabled", str(output)]
            log = (folder / (name + "-ffmpeg.log")).open("wb")
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            jobs.append((name, process, log))
            manifest["sources"][name] = {"file": output.name, "launched_utc": utc(), "command": command}
        save_json(folder / "manifest.json", manifest)
        deadline = time.monotonic() + args.seconds if args.seconds else math.inf
        print(str(folder), flush=True)
        with (folder / "events.jsonl").open("a", encoding="utf-8") as journal:
            def preserve(records):
                for record in records:
                    if event_time(record) < session_start:
                        continue
                    journal.write(json.dumps(record, ensure_ascii=False) + "\n")
                    frame = record.get("frame") or record.get("path")
                    if frame and Path(frame).is_file():
                        frames = folder / "frames"
                        frames.mkdir(exist_ok=True)
                        shutil.copy2(frame, frames / Path(frame).name)

            while time.monotonic() < deadline and not (folder / "STOP").exists():
                preserve(tail.read())
                journal.flush()
                failed = [name for name, process, _ in jobs if process.poll() is not None]
                if failed:
                    raise RuntimeError("Capture stopped unexpectedly: " + ", ".join(failed))
                time.sleep(0.1)
            preserve(tail.read())
    except KeyboardInterrupt:
        manifest["stop_reason"] = "keyboard_interrupt"
    except Exception as exc:
        manifest["error"] = str(exc)
        raise
    finally:
        for name, process, log in jobs:
            try:
                if process.poll() is None:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                    process.wait(timeout=12)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait()
            finally:
                log.close()
            source = manifest["sources"][name]
            source["returncode"] = process.returncode
            try:
                source["media"] = probe(folder / source["file"])
            except (subprocess.SubprocessError, KeyError, ValueError) as exc:
                source["error"] = str(exc)
        manifest["ended_utc"] = utc()
        originals = folder / "original-logs"
        originals.mkdir(exist_ok=True)
        for log_path in args.events.glob("*.jsonl"):
            shutil.copy2(log_path, originals / log_path.name)
        manifest["event_reader_errors"] = tail.errors
        manifest["state"] = "failed" if manifest.get("error") or any(s.get("error") or s["returncode"] for s in manifest["sources"].values()) else "complete"
        save_json(folder / "manifest.json", manifest)


def export_usb(args):
    """Export the camera's complete, upright video at the original timing."""
    folder = args.folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["state"] != "complete":
        raise ValueError("USB recording is incomplete; see manifest.json")
    source = folder / manifest["sources"]["vision"]["file"]
    output = folder / "quick-scan.mp4"
    filters = "hflip,vflip," if manifest["rotation"] == 180 else ""
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-map", "0:v:0",
        "-an", "-vf", filters + "setpts=PTS-STARTPTS", "-fps_mode", "vfr",
        "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ], check=True)
    print(str(output), flush=True)


def ass_time(seconds):
    ticks = max(0, round(seconds * 100))
    return f"{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}"


def ass_text(text):
    return str(text).replace("\\", "＼").replace("{", "（").replace("}", "）").replace("\r", " ").replace("\n", "\\N")


def subtitles(folder, start, duration, width, height, path):
    records = []
    for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("event") in LABELS and start <= event_time(record) < start + duration:
            records.append(record)
    records.sort(key=event_time)
    size = 30 if width > height else 28
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{size},&H00F4F4F4,&H000000FF,&H00180E08,&H60180E08,0,0,0,0,100,100,0,0,3,1,0,2,35,35,25,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    summary = ""
    execution = ""
    for index, record in enumerate(records):
        at = max(0, event_time(record) - start)
        end = duration
        if index + 1 < len(records):
            end = min(end, event_time(records[index + 1]) - start)
        event = record["event"]
        if event == "sending":
            execution = LABELS[event] + " · " + ass_text(record.get("command", ""))
        elif event == "acknowledged":
            execution = LABELS[event] + " · " + ass_text(record.get("command", "")) + " · " + ass_text(record.get("response", "")) + "\\N实际停稳待确认 / Physical settling unverified"
        elif event == "motion_verified":
            execution = LABELS[event] + " · " + ass_text(record.get("command", ""))
        else:
            summary = LABELS[event] + " · " + ass_text(record.get("text", "")) + "\\N" + ass_text(record.get("text_en", ""))
        if end > at:
            content = "\\N".join(part for part in (summary, execution) if part)
            lines.append(f"Dialogue: 0,{ass_time(at)},{ass_time(end)},Default,,0,0,0,,{content}\n")
    path.write_text("".join(lines), encoding="utf-8-sig")


def compose(args):
    folder = args.folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["state"] != "complete":
        raise ValueError("Recording must finish successfully before export")
    sources = []
    for name in ("vision", "monitor", "external"):
        if name in manifest["sources"]:
            item = manifest["sources"][name]
            sources.append((name, folder / item["file"], item["media"]["start"], item["media"]["duration"]))
    if args.external:
        external = args.external.resolve()
        media = probe(external)
        # Offset means external first frame occurs this many seconds after session UTC.
        external_start = datetime.fromisoformat(manifest["started_utc"]).timestamp() + args.external_offset
        sources = [s for s in sources if s[0] != "external"]
        sources.append(("external", external, external_start, media["duration"]))
    elif "external" in manifest.get("imports", {}):
        item = manifest["imports"]["external"]
        sources.append(("external", folder / item["file"], item["utc_start"], item["media"]["duration"]))
    start = max(s[2] for s in sources) + args.start
    end = min(s[2] + s[3] for s in sources)
    duration = min(end - start, args.duration or math.inf)
    if duration <= 0:
        raise ValueError("Sources have no overlapping interval at these offsets")
    width, height = (1920, 1080) if args.layout == "landscape" else (1080, 1920)
    output = folder / (args.layout + ("-three" if len(sources) == 3 else "-two") + ".mp4")
    subtitle = folder / (args.layout + ".ass")
    subtitles(folder, start, duration, width, height, subtitle)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-filter_complex_threads", "2"]
    for _, file, source_start, _ in sources:
        command += ["-ss", f"{start - source_start:.6f}", "-threads", "1", "-i", str(file)]
    # Each source keeps its full frame. The monitor is the real native UI capture.
    if args.layout == "landscape":
        boxes = [(0, 80, 1240, 740), (1240, 80, 680, 740)] if len(sources) == 2 else [(0, 80, 1240, 370), (1240, 80, 680, 740), (0, 450, 1240, 370)]
    else:
        boxes = [(0, 90, 1080, 720), (0, 810, 1080, 800)] if len(sources) == 2 else [(0, 90, 1080, 560), (0, 1210, 1080, 450), (0, 650, 1080, 560)]
    filters = [f"color=c=0x080e18:s={width}x{height}:r=30:d={duration}[base]"]
    labels = {"vision": "夹爪视角 / AI VISION", "monitor": "真实监控 / MIND & ACTIONS", "external": "外部机位 / ROBOT BODY"}
    font = "fontfile='C\\:/Windows/Fonts/msyh.ttc'"
    for index, (name, _, _, _) in enumerate(sources):
        x, y, w, h = boxes[index]
        rotate = ",hflip,vflip" if name == "vision" and manifest["rotation"] == 180 else ""
        # Keep the complete native window in monitor.mkv. The export emphasizes
        # its real right-hand decision panel, alongside the separate vision feed.
        crop = ",crop=iw*0.36:ih:iw*0.64:0" if name == "monitor" else ""
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS{rotate}{crop},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x101a29,setsar=1[tile{index}]")
        previous = "base" if index == 0 else f"stage{index - 1}"
        filters.append(f"[{previous}][tile{index}]overlay={x}:{y}:eof_action=pass,drawtext={font}:text='{labels[name]}':x={x + 15}:y={y + 12}:fontsize=25:fontcolor=0x5be0d5:box=1:boxcolor=0x080e18@0.8[stage{index}]")
    caption = "具身探索 / EMBODIED EXPLORATION"
    clock_start = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d %H-%M-%S UTC")
    filters.append(f"[stage{len(sources)-1}]drawtext={font}:text='{caption}':x=28:y=16:fontsize=32:fontcolor=white,drawtext={font}:text='{clock_start}  + %{{pts\\:hms}}':x=28:y=56:fontsize=18:fontcolor=0x5be0d5,subtitles=filename='{subtitle.name}'[out]")
    script = folder / (args.layout + "-filters.txt")
    script.write_text(";\n".join(filters), encoding="utf-8")
    command += ["-filter_complex_script", str(script), "-map", "[out]", "-t", str(duration),
                "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-threads", "4",
                "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", str(output)]
    subprocess.run(command, cwd=folder, check=True)
    report = {"file": str(output), "utc_start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
              "duration": duration, "sources": [s[0] for s in sources],
              "external_pending": len(sources) < 3,
              "external_offset": args.external_offset if args.external else None, "media": probe(output)}
    save_json(folder / (output.stem + ".json"), report)
    print(json.dumps({k: v for k, v in report.items() if k != "media"}, ensure_ascii=False))


def import_external(args):
    folder = args.folder.resolve()
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["state"] != "complete":
        raise ValueError("Finish recording before importing external footage")
    source = args.file.resolve()
    destination = folder / ("external-original" + source.suffix.lower())
    if destination.exists():
        raise FileExistsError(destination)
    media = probe(source)
    shutil.copy2(source, destination)
    manifest.setdefault("imports", {})["external"] = {
        "file": destination.name, "original_path": str(source), "media": media,
        "utc_start": datetime.fromisoformat(manifest["started_utc"]).timestamp() + args.offset,
        "offset_seconds": args.offset, "sync_evidence": args.evidence,
        "sha256": digest(destination), "imported_utc": utc()}
    manifest["external_pending"] = False
    save_json(path, manifest)
    print(str(destination))


def verify(args):
    folder = args.folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    files = [folder / source["file"] for source in manifest["sources"].values()]
    files.extend(folder.glob("*-two.mp4"))
    files.extend(folder.glob("*-three.mp4"))
    files.extend(folder.glob("story-90-*.mp4"))
    files.extend(folder.glob("quick-scan.mp4"))
    files.extend(folder.glob("dynamic-*.mp4"))
    files.extend(folder / item["file"] for item in manifest.get("imports", {}).values())
    results = []
    for path in files:
        media = probe(path)
        decoded = subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-threads", "1", "-i", str(path),
            "-map", "0:v:0", "-an", "-fps_mode", "passthrough", "-progress", "pipe:1",
            "-nostats", "-f", "null", "-"], capture_output=True, text=True)
        counts = [int(line.split("=", 1)[1]) for line in decoded.stdout.splitlines()
                  if line.startswith("frame=")]
        frames = counts[-1] if counts else 0
        results.append({"file": path.name, "frames": frames,
                        "duration": media["duration"], "width": media["width"],
                        "height": media["height"],
                        "observed_fps": frames / media["duration"],
                        "decode_ok": decoded.returncode == 0 and frames > 0,
                        "decode_errors": decoded.stderr.strip()})
        print(f"Verified {path.name}: {frames} frames, decode return code {decoded.returncode}", flush=True)
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    start = datetime.fromisoformat(manifest["started_utc"]).timestamp()
    end = datetime.fromisoformat(manifest["ended_utc"]).timestamp()
    report = {"verified_utc": utc(), "files": results, "events": len(events),
              "events_within_session": all(start <= event_time(event) <= end for event in events),
              "external_pending": manifest.get("external_pending", True),
              "sync_limits": manifest["sync_limits"]}
    save_json(folder / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["events_within_session"] or not all(item["decode_ok"] for item in results):
        raise RuntimeError("Recording verification failed, see verification.json")


def edit_story(args):
    folder = args.folder.resolve()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    master = folder / (args.layout + "-three.mp4")
    report = json.loads(master.with_suffix(".json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    source_start = datetime.fromisoformat(report["utc_start"]).timestamp()
    durations = [float(segment["duration"]) for segment in plan["segments"]]
    starts = [float(segment["source_start"]) for segment in plan["segments"]]
    if not all(math.isfinite(value) and value > 0 for value in durations) or abs(sum(durations) - 90) > .001:
        raise ValueError("Story plan must contain positive durations totaling 90 seconds")
    if not all(math.isfinite(at) and 0 <= at and at + duration <= report["duration"] + 1 / 30
               for at, duration in zip(starts, durations)):
        raise ValueError("Story segment exceeds recorded master interval")
    width, height = (1920, 1080) if args.layout == "landscape" else (1080, 1920)
    work = folder / ("story-90-" + args.layout + "-parts")
    work.mkdir(exist_ok=True)
    elapsed = 0.0
    decisions = []
    for index, segment in enumerate(plan["segments"]):
        at, duration = float(segment["source_start"]), float(segment["duration"])
        media = master
        seek = at
        filters = []
        if segment.get("view") == "body":
            external = manifest["imports"]["external"]
            media = folder / external["file"]
            seek = source_start + at - external["utc_start"]
            if args.layout == "portrait":
                # This first shot follows the visible end effector in the left
                # part of the operator's original frame. Raw footage is kept.
                filters.append("crop=ih*9/16:ih:iw*0.08:0")
            filters += [f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x080e18", "setsar=1"]
            stamp = datetime.fromtimestamp(source_start + at, timezone.utc).strftime("%Y-%m-%d %H-%M-%S UTC")
            filters.append(f"drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='{stamp} + %{{pts\\:hms}}':x=24:y=20:fontsize=20:fontcolor=0x5be0d5:box=1:boxcolor=0x080e18@0.85")
        subtitle = work / f"part-{index:02}.ass"
        size = 36 if width > height else 31
        margin = 175 if width > height else 235
        subtitle.write_text(
            f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Story,Microsoft YaHei,{size},&H00FFFFFF,&H000000FF,&H00180E08,&H80180E08,0,0,0,0,100,100,0,0,3,1,0,2,45,45,{margin},1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,{ass_time(duration)},Story,,0,0,0,,{ass_text(segment['title_en'])}\\N{ass_text(segment['title_zh'])}\n",
            encoding="utf-8-sig")
        filters.append(f"subtitles=filename='{subtitle.name}'")
        output = work / f"part-{index:02}.mp4"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-ss", str(seek),
                   "-threads", "1", "-i", str(media), "-t", str(duration), "-an", "-vf", ",".join(filters),
                   "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-threads", "4",
                   "-pix_fmt", "yuv420p", "-r", "30", str(output)]
        subprocess.run(command, cwd=work, check=True)
        decisions.append({**segment, "output_start": elapsed, "output_end": elapsed + duration,
                          "source_utc": datetime.fromtimestamp(source_start + at, timezone.utc).isoformat(),
                          "source_file": str(media), "input_seek": seek, "command": command})
        elapsed += duration
        print(f"{args.layout} story {index + 1}/{len(plan['segments'])}", flush=True)
    playlist = work / "concat.txt"
    playlist.write_text("".join(f"file 'part-{index:02}.mp4'\n" for index in range(len(decisions))), encoding="utf-8")
    output = folder / ("story-90-" + args.layout + ".mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat",
                    "-safe", "0", "-i", str(playlist), "-c", "copy", "-movflags", "+faststart", str(output)], check=True)
    save_json(output.with_suffix(".json"), {"file": str(output), "segments": decisions,
              "duration": elapsed, "media": probe(output), "created_utc": utc(),
              "method": "Chronological real-time excerpts with cuts. Captions supplied by the user and translated. Original UTC remains on the source views."})
    print(str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    record = commands.add_parser("record")
    record.add_argument("--output", type=Path, default=ROOT / ".runtime" / "recordings" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    record.add_argument("--events", type=Path, default=ROOT / ".runtime")
    record.add_argument("--camera", default="http://127.0.0.1:8766")
    record.add_argument("--window", default=TITLE)
    record.add_argument("--fps", type=int, default=10)
    record.add_argument("--rotation", type=int, choices=[0, 180], default=180)
    record.add_argument("--external", help="Live URL or dshow:DEVICE; omit for later external file import")
    record.add_argument("--usb-only", action="store_true", help="Record the USB camera stream without window capture")
    record.add_argument("--seconds", type=float, default=0, help="0 records until STOP file or Ctrl+C")
    record.set_defaults(run=capture)
    export = commands.add_parser("export")
    export.add_argument("folder", type=Path)
    export.add_argument("--layout", choices=["landscape", "portrait", "both"], required=True)
    export.add_argument("--external", type=Path)
    export.add_argument("--external-offset", type=float)
    export.add_argument("--start", type=float, default=0)
    export.add_argument("--duration", type=float)
    export.set_defaults(run=compose)
    usb = commands.add_parser("export-usb", help="Export the upright USB camera video at its original timing")
    usb.add_argument("folder", type=Path)
    usb.set_defaults(run=export_usb)
    ingest = commands.add_parser("import-external", help="Preserve an external original with a measured synchronization offset")
    ingest.add_argument("folder", type=Path)
    ingest.add_argument("file", type=Path)
    ingest.add_argument("--offset", type=float, required=True, help="External first frame UTC minus recording started_utc, in seconds")
    ingest.add_argument("--evidence", required=True, help="How this offset was measured, including uncertainty")
    ingest.set_defaults(run=import_external)
    validate = commands.add_parser("verify", help="Count and fully decode recordings and exports")
    validate.add_argument("folder", type=Path)
    validate.set_defaults(run=verify)
    story = commands.add_parser("edit", help="Render a 90-second story from a recorded three-view master")
    story.add_argument("folder", type=Path)
    story.add_argument("--plan", type=Path, required=True)
    story.add_argument("--layout", choices=["landscape", "portrait", "both"], default="both")
    story.set_defaults(run=edit_story)
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        parser.error("FFmpeg and FFprobe must be on PATH")
    for key in ("seconds", "fps", "start", "duration", "external_offset", "offset"):
        value = getattr(args, key, None)
        if value is not None and (not math.isfinite(value) or (key not in ("external_offset", "offset") and value < 0)):
            parser.error(key + " must be finite and non-negative")
    if getattr(args, "fps", 1) == 0:
        parser.error("fps must be positive")
    if getattr(args, "duration", None) == 0:
        parser.error("duration must be positive")
    if args.action == "export" and args.external and args.external_offset is None:
        parser.error("--external requires a measured --external-offset")
    if args.action == "record" and args.usb_only and args.external:
        parser.error("--usb-only cannot record an external camera")
    if args.action in ("export", "edit") and args.layout == "both":
        for layout in ("landscape", "portrait"):
            args.layout = layout
            args.run(args)
    else:
        args.run(args)


if __name__ == "__main__":
    main()
