# Audio door troubleshooting

## Architecture

```
Hermes (Mac Mini) → http://127.0.0.1:7792/v1   (agent-workflows audio process, LaunchAgent
                                                com.jkrumm.agent-workflows-audio, loopback only)
                  → IU unified endpoint (Gemini TTS, ElevenLabs via Replicate, Voxtral/OpenAI STT)
```

The door does text prep (chunking, spoken-form numbers, pause tags, title) but the upstream
Gemini model's own length limit still applies. Every request is a run of its own
(`door.speech` / `door.transcriptions`) in agent-workflows, caller `hermes`.

**Auth:** `Authorization: Bearer $AUDIO_DOOR_TOKEN`. The gateway process puts that variable into
its environment at start — `config.yaml` `secrets.command` reads the `hermes=` line of the
door-token file (agent-workflows' `door-tokens`, local, mode 0600) — and `tts.openai.api_key` /
`stt.openai.api_key` reference it. The token is not a 1Password item and never enters git.
A 401 `unauthorized` means the variable is empty (file missing or no `hermes=` line, then a
gateway restart) or the token was rotated without a restart.

## Quick health check

```bash
curl -s http://127.0.0.1:7792/health
# → {"status":"ok","version":"<release sha>"}
```

No answer → the LaunchAgent is down: `launchctl print gui/$(id -u)/com.jkrumm.agent-workflows-audio`.
Restarting or redeploying it belongs to agent-workflows (`make deploy` there), not to Hermes.

## Run record

Every response carries `agw-run-id`. `agw run status <id>` (on the mini, where `agw` runs) shows
the caller, the route actually served, cost and call count — the first place to look when audio
sounds wrong or a request failed.

## Error patterns

### 401 `unauthorized`
See *Auth* above.

### 502 `proxy_error` / `upstream_error`
The IU upstream failed for that call. Retry once. If every request fails while `/health` is ok,
read the run (`agw run status <agw-run-id>`) for the upstream error text.

### 503 `proxy_error`
The audio process is up but its runtime is not open yet (just restarted) — retry in a few seconds.

### 400 `invalid_request_error`
Bad `response_format`, `style`/`delivery` value, or an upload over the limit — the message names it.

## Testing TTS end-to-end

```bash
curl -s -o /tmp/test.mp3 -D /tmp/test.hdr -w "HTTP %{http_code} size=%{size_download}\n" \
  -X POST http://127.0.0.1:7792/v1/audio/speech \
  -H "Authorization: Bearer $AUDIO_DOOR_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash-lite-tts","voice":"Charon","input":"Hallo Test.","response_format":"mp3"}'

file /tmp/test.mp3
# Should say: /tmp/test.mp3: MPEG ADTS, layer III ...
# If it says "ASCII text" instead, the body is an error, not audio.
grep -i agw-run-id /tmp/test.hdr
```

No local TTS path exists to fall back to — the door is the only backend
(see repo `AGENTS.md`'s audio section).
