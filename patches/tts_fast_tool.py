"""Fast TTS tool — thin client over localai-helper (:8001).

Calls POST /v1/tts/synthesize/fast which orchestrates:
  English-only polish (Haiku — strips markdown, translates non-English to
  English, NO Fish-style prosody tags), title generation, Supertonic-3
  ONNX/CPU synthesis with the Sam (M4) voice preset, MP3 encode + loudnorm.

Returns a MEDIA:<path> tag Hermes delivers as a Slack audio attachment.

Why this exists separately from text_to_speech:
  Fish-S2-Pro (the primary engine) is highest-quality but slow and MLX-heavy.
  Supertonic-3 is fast (CPU, ~900 MB), ignores Fish prosody tags, and its
  preset voices are English-tuned. So the optimal pipeline is different:
  English-only, light polish without tags, short prose. Splitting into a
  separate tool lets the LLM pick speed-vs-quality per turn instead of the
  current "always primary, fall back on failure" pattern.

Local addition to ~/.hermes/hermes-agent/tools/tts_fast_tool.py.
Source of truth: ~/SourceRoot/hermes-agent/patches/tts_fast_tool.py
Re-apply after `hermes update`:
  cp ~/SourceRoot/hermes-agent/patches/tts_fast_tool.py \
     ~/.hermes/hermes-agent/tools/tts_fast_tool.py
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


def text_to_speech_fast_tool(
    text: str,
    output_path: str | None = None,
) -> str:
    """Convert text to a fast English voice memo. Returns JSON with MEDIA tag."""
    if not text or not text.strip():
        return json.dumps({"success": False, "error": "Text is required"})

    payload = {
        "text": text.strip(),
        "english_only": True,
        "polish": True,
    }
    try:
        r = requests.post(
            f"{_HELPER_URL}/v1/tts/synthesize/fast",
            json=payload,
            # Supertonic on CPU does ~1.5x realtime on the M2 Pro. A 4-sentence
            # memo renders in 5–15 s; the Haiku polish adds 1–3 s. 120 s gives
            # comfortable headroom for the longest reasonable voice memo
            # without sitting on a wedged request.
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as e:
        return json.dumps({"success": False, "error": f"Helper error: {e.response.status_code}"})
    except Exception as e:
        return json.dumps({"success": False, "error": f"Fast TTS failed: {e}"})

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
        "Fast TTS audio: %s (%.1fs, lang=%s)",
        file_path.name,
        data.get("duration_secs", 0),
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


def check_tts_fast_requirements() -> bool:
    try:
        r = requests.get(f"{_HELPER_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


TTS_FAST_SCHEMA = {
    "name": "text_to_speech_fast",
    "description": (
        "FAST English voice memo via Supertonic-3 (Sam / M4 voice). "
        "ALWAYS use this tool when the user explicitly asks for 'fast TTS', "
        "'fast voice', 'quick voice memo', 'fast audio', or any similar "
        "speed-first phrasing — regardless of content length or language. "
        "Also the default choice for: status snaps, quick confirmations, "
        "weather snippets, ad-hoc voice replies, anything where speed beats "
        "production polish.\n"
        "\n"
        "Pipeline (server-side, you don't manage any of it):\n"
        "  • Haiku polish rewrites the text for natural spoken English, "
        "strips markdown, and TRANSLATES non-English input (German, etc.) "
        "to English. Information is preserved — short stays short, long "
        "stays long. The voice is English-tuned, so this tool always "
        "delivers English audio regardless of input language.\n"
        "  • Custom paragraph + sentence chunker hands each chunk to "
        "Supertonic-3 (ONNX/CPU) with edge-fade smoothing and two-tier "
        "inter-chunk pauses (sentence beat vs paragraph breath). The polish "
        "may insert <breath> tags at natural inhale points for longer memos.\n"
        "  • Loudness-normalized MP3 returned as a MEDIA: path for Slack.\n"
        "\n"
        "DO NOT add prosody tags like [emphasis] or [pause] — Supertonic "
        "ignores them or reads them as literal text. Just write the natural "
        "message you want spoken. Numbers, dates, currency, units, "
        "abbreviations are auto-normalized; write them naturally.\n"
        "\n"
        "Use text_to_speech (the primary tool) ONLY when: the user explicitly "
        "asks for the high-quality / Fish / German voice path, OR the content "
        "is a scheduled briefing that needs the German voice or Fish-grade "
        "prosody. When in doubt — especially for interactive replies — pick "
        "text_to_speech_fast."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The message to speak. Plain prose — the helper polishes "
                    "it for spoken delivery, preserving every piece of "
                    "information. Any length works: short snaps stay snappy, "
                    "multi-paragraph content renders with paragraph-aware "
                    "cadence. Use blank lines to mark deliberate section "
                    "breaks. Non-English input is fine — it gets translated "
                    "to English automatically."
                ),
            },
        },
        "required": ["text"],
    },
}

from tools.registry import registry  # noqa: E402

registry.register(
    name="text_to_speech_fast",
    toolset="tts",
    schema=TTS_FAST_SCHEMA,
    handler=lambda args, **kw: text_to_speech_fast_tool(
        text=args.get("text", ""),
        output_path=args.get("output_path"),
    ),
    check_fn=check_tts_fast_requirements,
    emoji="⚡",
)
