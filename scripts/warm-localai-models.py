"""Keep local STT (Parakeet via mlx-audio) and fast TTS (Supertonic-3) warm.

Runs as a Hermes `no_agent` cron. Empty stdout on success → silent delivery.
On failure, prints a one-line-per-failure report and exits non-zero so the
scheduler logs the failure and the watchdog cron picks it up via the
`hermes_cron` source.

Two warm-ups:

  1. STT — POST `/tmp/_mlx-audio-warmup.wav` (0.5s silence, regenerated here
     if missing) to localai-helper's `/v1/audio/transcriptions` proxy. Forces
     Parakeet to stay resident in mlx-audio's ModelProvider cache.

  2. Fast TTS — POST `{"text": "ok", "polish": false}` to Supertonic-3.
     `polish: false` bypasses the polish LLM call, so this is pure local
     ONNX inference — no API cost.

Operator dry-run: just run this script directly (`python3 ...`). No flag
toggle — production and manual invocations behave identically.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HELPER_BASE = "http://127.0.0.1:8001"
STT_WARMUP_WAV = Path("/tmp/_mlx-audio-warmup.wav")
STT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
TIMEOUT_SECS = 30


def _ensure_warmup_wav() -> str | None:
    """Generate the silent warm-up WAV if /tmp got cleaned. Returns error string on failure."""
    if STT_WARMUP_WAV.exists():
        return None
    try:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=16000:cl=mono", "-t", "0.5",
             "-y", str(STT_WARMUP_WAV)],
            check=True, capture_output=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"could not generate warm-up WAV: {e}"
    return None


def _warm_stt() -> str | None:
    err = _ensure_warmup_wav()
    if err:
        return err
    boundary = "----localai-warm-up"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model"\r\n\r\n'
        f"{STT_MODEL}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="warmup.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + STT_WARMUP_WAV.read_bytes() + tail
    req = urllib.request.Request(
        f"{HELPER_BASE}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as r:
            r.read()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return str(e.reason if hasattr(e, "reason") else e)
    return None


def _warm_fast_tts() -> str | None:
    body = json.dumps({"text": "ok", "polish": False, "english_only": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{HELPER_BASE}/v1/tts/synthesize/fast",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as r:
            r.read()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return str(e.reason if hasattr(e, "reason") else e)
    return None


def main() -> int:
    failures: list[tuple[str, str]] = []
    for label, fn in [("STT", _warm_stt), ("Fast TTS", _warm_fast_tts)]:
        err = fn()
        if err:
            failures.append((label, err))

    if not failures:
        return 0

    now = dt.datetime.now().strftime("%H:%M")
    print(f":thermometer: LocalAI warm-up failures ({now}):")
    for label, err in failures:
        print(f"- {label}: {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
