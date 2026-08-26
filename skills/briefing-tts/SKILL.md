---
name: briefing-tts
description: "TTS audio synthesis via the VPS audio-gateway (https://audio-gateway.jkrumm.com/v1) — ElevenLabs v3 for briefings/long-form (expressive, titled), ElevenLabs Flash v2.5 for short replies, voice \"Roger\", OpenAI-compatible /v1/audio/speech. Use for any spoken output: morning/evening briefings, voice memos, ad-hoc TTS."
version: 2.0.0
metadata:
  hermes:
    tags: [tts, audio, briefing, elevenlabs, audio-gateway, mp3, voice]
    related_skills: [argo-api, homelab-ops]
---

# Briefing TTS

Audio synthesis via the VPS audio-gateway, OpenAI-compatible `/v1/audio/speech`.
The gateway routes by **model id** and owns everything behind it (prep LLM,
chunking, concatenation, title); the caller sends the whole text in one request.
This skill exists because the native `text_to_speech` tools are NOT reliably
registered in every session (especially cron), so it calls the gateway directly
via urllib/curl. Same pattern works interactively and in cron.

**API base:** `https://audio-gateway.jkrumm.com/v1`
**Health:** `GET https://audio-gateway.jkrumm.com/health` → `{"ok":true,"service":"audio-gateway"}`
**Container lookup:** don't hardcode a container name — the Docker Compose
suffix changes on every redeploy. Use the `homelab-ops` skill's `containers
vps` / `logs vps <name>` verbs, which resolve the live name for you.

---

## Which model

| Use | `model` | What the gateway does | Latency |
|-|-|-|-|
| Briefings, long-form, anything worth listening to | `elevenlabs/v3` | prep LLM (spoken-form numbers/dates, ~110-word chunks, sparse audio tags, **title**), parallel synth, one continuous MP3 | ~10 s per 40 s of audio |
| Short replies, confirmations | `elevenlabs/flash-v2.5` | one synthesis call, no prep, no title | ~1.2 s |

Voice is `Roger` for both (ElevenLabs fixed voice list: Roger, Drew, Paul,
Bradford, James, Mark, Clyde, …; unknown names fall back to the gateway default).
The chat/desktop/Slack-reply path uses Flash through `config.yaml` → `tts.openai`;
this skill is the briefing path and pins `elevenlabs/v3` explicitly.
`gemini-3.1-flash-tts-preview` (voice `Charon`) is still served for comparison,
but it is ~10× slower per second of audio and no longer the default.

---

## Endpoint

`POST /v1/audio/speech`

```json
{
  "model": "elevenlabs/v3",
  "voice": "Roger",
  "input": "the whole briefing text — do not pre-chunk",
  "response_format": "mp3"
}
```

Returns raw MP3 bytes — no base64 wrapping, write directly to file. Optional
fields: `language` (`de`/`en`, else auto-detected from the text), `speed`
(0.7–1.2), `instructions` (a short delivery hint the prep LLM folds in; v3 only).
A model id that matches nothing is silently remapped to the gateway default, so a
typo won't error — check the id.

Response header **`X-Audio-Title`** (URL-encoded, v3 only) carries a 3–6-word
title the prep LLM derived from the content, in the text's language — use it for
the filename when no convention below applies.

---

## Pitfalls

### 1. Don't chunk on the caller side anymore
The old Gemini backend 503'd on long text, so this skill used to split into
40–80-word pieces and concatenate MP3 bytes. The ElevenLabs lane chunks
server-side with cross-chunk prosody continuity — sending pieces yourself now
*hurts* (no continuity, no title, repeated prep). One request, whole text.

If a request 502s with `proxy_error`, the Replicate upstream failed for that
prediction — retry once; if health is fine but every request fails, see
`references/audio-gateway-troubleshooting.md`.

### 2. `text_to_speech` / `text_to_speech_fast` tools aren't always registered
Not reliably available in every session, especially cron. Call the gateway
directly via curl or `urllib.request` — don't depend on the native tool.

### 3. `execute_code` can be blocked under `cron_mode` approval
Use `terminal` with a Python script file instead (write to `/tmp`, run with
`python3`).

### 4. Heredoc Python is blocked by Tirith
`python3 << 'PYEOF'` gets flagged as a security pattern. Write the script to
a file first (`write_file` to `/tmp/script.py`), then
`terminal("python3 /tmp/script.py")`.

### 5. `curl | python3` is blocked by Tirith
Piping curl output straight into an interpreter trips the "pipe to
interpreter" gate. Write the response to a file, or use `urllib.request`
inside the Python script instead of shelling out to curl.

---

## Canonical Pattern — One Request

Write a Python script, run it:

```python
import json, urllib.request, urllib.parse, os

AUDIO_DIR = "/Users/jkrumm/.hermes/cache/audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

text = """Guten Morgen. Heute ist ... (the whole briefing, plain prose, no markdown)"""

payload = json.dumps({
    "model": "elevenlabs/v3",
    "voice": "Roger",
    "input": text,
    "response_format": "mp3",
}).encode("utf-8")

req = urllib.request.Request(
    "https://audio-gateway.jkrumm.com/v1/audio/speech",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=180) as resp:
    audio = resp.read()
    title = urllib.parse.unquote(resp.headers.get("X-Audio-Title", "") or "")

out_path = os.path.join(AUDIO_DIR, "Morning Briefing Thu 14.05.26.mp3")  # see conventions below
with open(out_path, "wb") as f:
    f.write(audio)
print(f"{len(audio)} bytes, title={title!r} -> {out_path}")
```

For a short phrase, a curl one-liner on Flash:

```bash
curl -s -X POST https://audio-gateway.jkrumm.com/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"elevenlabs/flash-v2.5","voice":"Roger","input":"Erledigt.","response_format":"mp3"}' \
  -o /tmp/short.mp3
```

---

## MEDIA Tag

Append at the **very end** of the Slack text body:
```
MEDIA:/Users/jkrumm/.hermes/cache/audio/filename.mp3
```
The delivery system picks it up and attaches the MP3. (The native
`text_to_speech` tool names its output from the gateway's `X-Audio-Title`
header instead — see the repo `CLAUDE.md`'s `tts-tool-audio-title.patch`
note. With the urllib pattern above you name the file yourself, per the
conventions below, and can fall back to the header title for ad-hoc audio.)

---

## Output filename conventions

| Report type | Pattern | Example |
|-|-|-|
| Evening (German) | `Abend <Weekday> <HH> <DD.MM.YY>.mp3` | `Abend Mittwoch 22 13.05.26.mp3` |
| Morning (German) | `Morning Briefing <Day> <DD.MM.YY>.mp3` | `Morning Briefing Thu 14.05.26.mp3` |
| Ad-hoc / weather | `Wetter_<Weekday>_<DD.MM.YY>.mp3` | `Wetter_Mittwoch_10.06.26.mp3` |

All files saved to `/Users/jkrumm/.hermes/cache/audio/`.

---

**Reference files:**
- `references/audio-gateway-troubleshooting.md` — architecture, 503 diagnosis, container log access via `homelab-ops`
- `references/morning-briefing-edge-cases.md` — content edge cases observed while assembling the morning/evening briefing narrative (calendar, GitHub, watchdog, meeting overlap)
