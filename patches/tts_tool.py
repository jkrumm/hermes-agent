"""TTS tool — thin client over localai-helper (:8001).

Calls POST /v1/tts/synthesize which orchestrates:
  language detection, speakable rewrite (Haiku), title (Haiku),
  paragraph-aware chunking, Voxtral 4B synthesis, MP3 encode.

Returns a MEDIA:<path> tag Hermes delivers as a Slack audio attachment.

Local modification to ~/.hermes/hermes-agent/tools/tts_tool.py.
Source of truth: ~/SourceRoot/claude-local/hermes/patches/tts_tool.py
Re-apply after `hermes update`:
  cp ~/SourceRoot/claude-local/hermes/patches/tts_tool.py \
     ~/.hermes/hermes-agent/tools/tts_tool.py
"""

import base64
import datetime
import json
import logging
import os
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_HELPER_URL = os.getenv("LOCALAI_HELPER_URL", "http://127.0.0.1:8001")
_OUTPUT_DIR = Path(os.getenv("TTS_OUTPUT_DIR", "~/.hermes/cache/audio")).expanduser()


def text_to_speech_tool(
    text: str,
    output_path: str | None = None,
) -> str:
    """Convert text to speech. Returns JSON with MEDIA tag for Slack delivery."""
    if not text or not text.strip():
        return json.dumps({"success": False, "error": "Text is required"})

    try:
        r = requests.post(
            f"{_HELPER_URL}/v1/tts/synthesize",
            json={"text": text.strip()},
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as e:
        return json.dumps({"success": False, "error": f"Helper error: {e.response.status_code}"})
    except Exception as e:
        return json.dumps({"success": False, "error": f"TTS failed: {e}"})

    if output_path:
        file_path = Path(output_path).expanduser()
    else:
        ts = datetime.datetime.now().strftime("%H:%M %d.%m.%y")
        title = data.get("title", "Voice memo")
        clean_title = re.sub(r'[<>:"/\\|?*]', "", title).strip()
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_path = _OUTPUT_DIR / f"{clean_title} {ts}.mp3"

    try:
        file_path.write_bytes(base64.b64decode(data["audio_b64"]))
    except Exception as e:
        return json.dumps({"success": False, "error": f"Failed to save audio: {e}"})

    logger.info(
        "TTS audio: %s (%.1fs, %d chunk(s), lang=%s)",
        file_path.name,
        data.get("duration_secs", 0),
        data.get("chunks", 1),
        data.get("lang", "?"),
    )

    return json.dumps({
        "success": True,
        "file_path": str(file_path),
        "media_tag": f"MEDIA:{file_path}",
        "title": data.get("title", ""),
        "duration_secs": data.get("duration_secs", 0),
        "lang": data.get("lang", ""),
    })


def check_tts_requirements() -> bool:
    try:
        r = requests.get(f"{_HELPER_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


TTS_SCHEMA = {
    "name": "text_to_speech",
    "description": (
        "Convert text to speech audio and deliver as a Slack voice memo. "
        "Use for briefings, weather updates, status summaries, or any response "
        "that benefits from audio. The helper rewrites markdown-heavy text into "
        "natural spoken prose, detects language automatically, and handles any "
        "length — including multi-minute memos. Returns a MEDIA: path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The text to speak. Write it as you would for Slack — the helper "
                    "rewrites it for speech automatically. Any length is supported."
                ),
            },
        },
        "required": ["text"],
    },
}

from tools.registry import registry  # noqa: E402

registry.register(
    name="text_to_speech",
    toolset="tts",
    schema=TTS_SCHEMA,
    handler=lambda args, **kw: text_to_speech_tool(
        text=args.get("text", ""),
        output_path=args.get("output_path"),
    ),
    check_fn=check_tts_requirements,
    emoji="🔊",
)
