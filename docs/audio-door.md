# audio-door

<!-- MOVED-AUDIO: moved verbatim from the root AGENTS.md (Audio door (TTS + STT), 1768 bytes) -->

Audio (TTS + STT) is the **agent-workflows audio door** (`~/SourceRoot/agent-workflows`,
`packages/audio`), an OpenAI-compatible loopback service on the mini at `http://127.0.0.1:7792/v1`
(LaunchAgent `com.jkrumm.agent-workflows-audio`; moved off the retired VPS audio gateway 2026-10-29, same
request/response contract). Hermes only points its native `openai` TTS/STT providers at it in
`config.yaml` — this repo installs and patches no audio service. **Auth:** `api_key: ${AUDIO_DOOR_TOKEN}`;
`secrets.command` appends that variable from the `hermes=` line of `~/.agent-workflows/data/door-tokens`
(a local 0600 file created by agent-workflows' deploy — not a 1Password ref, never in git). Every
request is a run in agent-workflows (`agw-run-id` response header, caller `hermes`); the cron briefing
prompts use the same door.
TTS = Gemini 3.8 via the door's native lane, voice Charon. **`model` is an agw route id, never a literal model id** — the route table owns the concrete id: `audio.tts.gemini-flash-lite` for chat replies (`tts.openai`), `audio.tts.gemini-flash` for
briefings (`skills/briefing-tts`, prep on). Streaming clients (CLI voice `OpenAIStreamer`, desktop
`speak-stream` relay, spoken summary) already send `response_format: pcm` and get the progressive
stream; Non-streaming replies stay whole-file mp3 + `X-Audio-Title`. ElevenLabs ids stay selectable as a
fallback. STT = `audio.stt.voxtral-mini` (Voxtral Mini Transcribe, EU; the door falls back to `gpt-transcribe`). Door rows for caller `hermes` carry lane `hermes` (since 2026-11-04); the prep/summary text calls are gateway rows under the door caller — join on `run_id`. Request shapes and traps: `modelpick/docs/gemini-tts.md`;
rationale: `modelpick/docs/decisions/audio-stack.md`.
