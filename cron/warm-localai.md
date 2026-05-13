# Warm LocalAI — Hermes Cron Job

Keeps the local STT (Parakeet via mlx-audio) and fast TTS (Supertonic-3) models warm so MacWhisper and fast-TTS callers don't hit cold-start latency on first request.

## Job Spec

| Field | Value |
|-|-|
| Schedule | `*/5 * * * *` (every 5 min, all days) |
| Mode | `no_agent` — script stdout delivered verbatim, no LLM round-trip |
| Script | `warm-localai-models.py` |
| Deliver | `slack:C0ASRULFTSS` (#watchdog) — failures only |
| Name | `Warm LocalAI` |

## What it does

| Service | Endpoint | Warm-up payload | Cost |
|-|-|-|-|
| STT (Parakeet) | `POST localai-helper:8001/v1/audio/transcriptions` | multipart with `/tmp/_mlx-audio-warmup.wav` (0.5s silence, regenerated if missing) | ~0.3s mlx-audio inference |
| Fast TTS (Supertonic-3) | `POST localai-helper:8001/v1/tts/synthesize/fast` | `{"text": "ok", "polish": false}` — `polish: false` skips the LLM rewrite so this is pure local ONNX | ~0.5s ONNX + ffmpeg loudnorm |

End-to-end ~1s per tick. Discards the returned MP3 and the transcription JSON.

## Why both

- **STT**: high-value. mlx-audio's `ModelProvider.models[]` cache can evict Parakeet under memory pressure. Periodic warm-up keeps it resident — `start-mlx-audio.sh` only warms once at process boot.
- **Fast TTS**: marginal. Supertonic loads at helper module import (`tts_fast.py:148`) and stays in memory while the process is up. Warm-up exercises ONNX inference + ffmpeg loudnorm paths — small first-call latency improvement on subsequent requests but no model-loading benefit.

If memory or CPU pressure becomes a concern, drop the TTS warm-up first by editing `warm-localai-models.py` and removing the `Fast TTS` entry from the `main()` loop.

## Failure handling

Empty stdout = silent (no Slack delivery). Failures emit one line per service to stdout and exit non-zero:

```
:thermometer: LocalAI warm-up failures (19:30):
- STT: Connection refused
```

That lands in `#watchdog` directly. The watchdog cron's `hermes_cron` poller also picks up the failed `last_status` and surfaces it independently — that's fine, double-eventing on infra failures is acceptable.

## Manual debugging

```bash
# Run once, see exit code
python3 ~/.hermes/scripts/warm-localai-models.py; echo "exit=$?"

# Time the warm-up
time python3 ~/.hermes/scripts/warm-localai-models.py

# Check helper health (used as upstream by both warm-ups)
curl -fsS http://127.0.0.1:8001/health

# Check mlx-audio (STT) directly
curl -fsS http://127.0.0.1:8000/v1/models
```

## Re-register

```bash
hermes cron create "*/5 * * * *" "" \
  --script warm-localai-models.py \
  --no-agent \
  --name "Warm LocalAI" \
  --deliver slack:C0ASRULFTSS
```
