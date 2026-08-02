# Audio-Gateway Troubleshooting

## Architecture

```
Hermes (Mac Mini) → https://audio-gateway.jkrumm.com/v1 (VPS Docker, Tailscale-only)
                   → LiteLLM proxy (internal)
                   → IU unified endpoint
                   → Gemini 3.1 Flash TTS (Charon voice)
```

The gateway does text prep (chunking + expression tags) but the upstream
Gemini model's own length limit still applies — see SKILL.md Pitfall #1.

## Quick health check

```bash
curl -s https://audio-gateway.jkrumm.com/health
# → {"ok":true,"service":"audio-gateway"}
```

If this doesn't respond, the container is down — go to container state below.

## Container state and logs — via `homelab-ops`, not raw curl

Don't hand-roll `docker/vps/containers` or `docker/vps/logs/<name>` calls,
and don't hardcode a container name — the Docker Compose suffix increments
on every redeploy. Use the `homelab-ops` skill's bounded verbs, which
resolve the live name and format the output:

```
~/.hermes/scripts/hermes-ops.sh containers vps          # find the live audio-gateway container name + state
~/.hermes/scripts/hermes-ops.sh logs vps <name> 200      # tail its logs
```

## Error patterns

### 503 with a LiteLLM error body, even on short phrases
The IU Gemini upstream is down. The gateway itself is healthy but can't
reach the model:
```
[LiteLLM 2026 Gateway GDPR StatusCode: InternalServerError] {"error":{"message":"Internal server error","type":"internal_server_error"}}
```
**No local fix.** Wait for IU upstream recovery. The container may
auto-restart via Docker Compose but that won't resolve an upstream outage.

### 503 only on long texts (>2-3 sentences)
Normal Gemini length limit — chunk into ~40-80 word pieces and concatenate
MP3s. See SKILL.md Pitfall #1.

### Connection refused / no response
Gateway container is down — confirm with `homelab-ops`' `containers vps`.
If it's wedged but not crash-looping, `restart vps audio-gateway` (Tier B,
`--why` + `--confirm`) is in scope. Note `redeploy vps <stack>` does **not**
cover it — `audio-gateway` deploys standalone via RollHook (push to
`jkrumm/audio-gateway:master`), it isn't part of the `networking` / `infra` /
`monitoring` compose stacks `homelab-ops` redeploys. A redeploy need
(image behind source, container missing) is a RollHook push, i.e. a code
change — escalate, don't improvise a docker command.

### Container recently restarted (Up < 10 min)
Likely auto-recovery from a prior crash. `logs vps <name>` for the crash
cause. A repeating fault on every restart is a crash loop — the IU upstream
being unhealthy can cause gateway panics; see the "no local fix" case above
before assuming a code fault.

## Testing TTS end-to-end

```bash
curl -s -o /tmp/test.mp3 -w "HTTP %{http_code} size=%{size_download}\n" \
  -X POST "https://audio-gateway.jkrumm.com/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.1-flash-tts-preview","voice":"Charon","input":"Hallo Test.","response_format":"mp3"}'

file /tmp/test.mp3
# Should say: /tmp/test.mp3: MPEG ADTS, layer III ...
# If it says "ASCII text" instead, the body is an error, not audio.
```

No local TTS path exists to fall back to — the gateway is the only backend
(see repo `CLAUDE.md`'s audio section).
