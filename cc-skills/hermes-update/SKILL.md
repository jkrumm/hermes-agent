---
name: hermes-update
description: Update Hermes Agent to latest version, resolve conflicts in locally-modified source files, and restart the gateway
---

# hermes-update

Updates `~/.hermes/hermes-agent/` from upstream, re-applies local customizations if upstream changed the same files, then restarts the gateway.

## Run the update

```bash
hermes update
```

Then check what happened:

```bash
cd ~/.hermes/hermes-agent && git status --short
```

If clean: jump straight to **Restart**. If conflicts or upstream rewrote a customized file: see below.

---

## Known local modifications

Three upstream files are customized. Re-apply if upstream overwrote them.

### `tools/tts_tool.py` — thin client over localai-helper

The upstream file is a 1600-line multi-provider TTS implementation (Edge / ElevenLabs / OpenAI / MiniMax / Mistral / Gemini / xAI / NeuTTS / KittenTTS). We replace it entirely with a ~160-line thin client that POSTs to `localai-helper:8001/v1/tts/synthesize`. The helper handles language detection, speakable rewrite, chunking, Fish S2 Pro synthesis (smile EQ for German), and ffmpeg encode.

The thin client also exposes `paragraph_pause_secs` as a tool argument, so agents (e.g. the morning briefing) can declare deliberate section beats by inserting blank lines and asking the helper for a longer inter-paragraph pause.

**Re-apply:**
```bash
cp ~/SourceRoot/dotfiles/hermes/patches/tts_tool.py \
   ~/.hermes/hermes-agent/tools/tts_tool.py
rm -f ~/.hermes/hermes-agent/tools/__pycache__/tts_tool*.pyc
```

The thin client only depends on `requests` and `tools.registry` — both stable upstream APIs.

### `gateway/platforms/slack.py` — Markdown pre-normalization

`format_message()` is patched to (a) replace `*` list markers with `-` (asterisk lists break the mrkdwn converter), and (b) strip backticks around emoji shortcodes (`:warning:` etc., otherwise they don't render).

**Re-apply:** read upstream `format_message()`, add the two pre-steps. The logic is small (~10 lines).

### `gateway/config.py` — Slack threading bridge

Bridges `reply_in_thread`, `reply_broadcast`, `reply_to_mode` from the `slack:` YAML section into the platform `extra` dict. Upstream as of 0.11.0 only bridges `require_mention`, `allow_bots`, `free_response_channels`.

**Re-apply:** find where the existing fields are bridged and add the three threading fields alongside.

---

## Restart

```bash
launchctl unload ~/Library/LaunchAgents/ai.hermes.gateway.plist
sleep 2
launchctl load ~/Library/LaunchAgents/ai.hermes.gateway.plist
```

Verify it came up:

```bash
tail -20 ~/.hermes/logs/gateway.log
```

## Verify

Send a message in `#hermes` on Slack and confirm a response. If TTS was touched, send a message that triggers voice output and check `~/.hermes/cache/audio/` for an MP3 with a sensible title.
