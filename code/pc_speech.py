"""Speak through Windows desktop audio using installed SAPI TTS voices."""
import argparse
import json
import subprocess
import sys

from exploration_events import emit


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$speaker = New-Object -ComObject SAPI.SpVoice
try {
    $voices = @($speaker.GetVoices())
    if ($request.voice) {
        $chosen = @($voices | Where-Object { $_.GetDescription().IndexOf($request.voice, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if ($chosen.Count -ne 1) { throw 'Voice name must match exactly one installed voice' }
        $speaker.Voice = $chosen[0]
    } else {
        $chinese = @($voices | Where-Object { $_.GetAttribute('Language') -match '(^|;)804(;|$)' })
        if ($chinese.Count -gt 0) { $speaker.Voice = $chinese[0] }
    }
    if ($request.output) {
        $outputs = @($speaker.GetAudioOutputs() | Where-Object { $_.GetDescription().IndexOf($request.output, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if ($outputs.Count -ne 1) { throw 'Output name must match exactly one audio device' }
        $speaker.AudioOutput = $outputs[0]
    }
    $speaker.Rate = [int]$request.rate
    $speaker.Volume = [int]$request.volume
    $device = if ($null -ne $speaker.AudioOutput) { $speaker.AudioOutput.GetDescription() } else { 'Windows default audio output' }
    # Synchronous playback returns after synthesis/playback completes.
    [void]$speaker.Speak([string]$request.text, 16)
    @{voice=$speaker.Voice.GetDescription(); output=$device; text=$request.text; status='playback_returned'} | ConvertTo-Json -Compress
} finally {
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($speaker)
}
'''


def speak(text, voice=None, output=None, rate=0, volume=80):
    if sys.platform != "win32":
        raise RuntimeError("This speech backend requires Windows SAPI")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("text must contain 1..4000 characters")
    if not -10 <= rate <= 10 or not 0 <= volume <= 100:
        raise ValueError("rate must be -10..10 and volume must be 0..100")
    payload = {"text": text, "voice": voice, "output": output, "rate": rate, "volume": volume}
    emit("speech_start", "电脑语音播报开始", text_en="Desktop speech playback started", utterance=text, engine="Windows SAPI")
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT],
                                   input=json.dumps(payload), encoding="utf-8", capture_output=True,
                                   timeout=max(30, len(text) * 2), creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Windows speech failed")
        result = json.loads(completed.stdout.lstrip("\ufeff"))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        emit("speech_error", "语音播放异常", text_en="Speech playback error", error=str(exc))
        raise
    emit("speech_complete", "语音引擎已完成本次播放", text_en="The speech engine completed playback", playback=result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--voice", help="Installed voice name substring")
    parser.add_argument("--output", help="Desktop audio output name substring; default is the Windows default")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--volume", type=int, default=80, help="TTS volume, independent of OS master volume")
    args = parser.parse_args()
    print(json.dumps(speak(args.text, args.voice, args.output, args.rate, args.volume), ensure_ascii=False))


if __name__ == "__main__":
    main()
