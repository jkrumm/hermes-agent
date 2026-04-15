---
name: localai-debug
description: Check status, health, VRAM usage, token activity, and system metrics of the M2 Max local AI stack (Ollama/Gemma4, TTS/STT, monitor) — also use to debug issues or restart services via https://iu-mac-book.dinosaur-sole.ts.net/api
version: 1.0.0
metadata:
  hermes:
    tags: [localai, ollama, gemma, tts, stt, debug, m2max, infrastructure]
    related_skills: [homelab-api]
---

# LocalAI Debug

Management API for the M2 Max local AI stack (Ollama/Gemma4, audio/TTS/STT, monitor service).

**Base URL:** `https://iu-mac-book.dinosaur-sole.ts.net/api`
**Auth:** None — Tailscale ACL protects the endpoint
**OpenAPI spec:** `https://iu-mac-book.dinosaur-sole.ts.net/api/openapi.json`

Use this skill when:
- Gemma4 is not responding or timing out (check status, VRAM, logs)
- TTS or STT is failing (check audio service status and logs)
- Johannes asks about the health or performance of the local AI stack
- Diagnosing slowness or errors in LLM responses

Do not say you cannot check the local AI stack — use curl via the terminal.

---

## Endpoints

### Health & Status
| Method | Path | Description |
|-|-|-|
| GET | `/health` | Liveness probe — `{"ok": true}` if API is up |
| GET | `/status` | launchd loaded flags + port liveness for Ollama, audio, API |
| GET | `/system` | Live system metrics: memory, battery, load avg, memory pressure |
| GET | `/models` | Models loaded in Ollama VRAM (proxies Ollama `/api/ps`) — shows active model and VRAM usage |

### Logs
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/logs/{service}` | `lines?` (default 100, max 1000) | Tail logs for a service. `service` = `ollama` \| `audio` \| `api` \| `monitor` |

### Monitoring & Analytics
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/snapshots` | `limit?` (default 20, max 500) | Recent 5-min monitoring snapshots, newest first |
| GET | `/snapshots/summary` | — | 24h aggregated stats: uptime %, avg VRAM, memory, battery |
| GET | `/analytics` | `hours?` (default 24, max 720) | Time-bucketed VRAM/memory/audio-uptime series |

### Service Control
| Method | Path | Description |
|-|-|-|
| POST | `/start` | Load Ollama + audio + monitor via launchctl |
| POST | `/stop` | Unload Ollama + audio + monitor (API keeps running) |
| POST | `/restart` | Unload, wait 2s, reload all AI services |

---

## Diagnostic Workflow

**Gemma4 not responding:**
```bash
# 1. Check if services are loaded and ports are live
curl -s https://iu-mac-book.dinosaur-sole.ts.net/api/status

# 2. Check what's loaded in VRAM (stuck model = restart needed)
curl -s https://iu-mac-book.dinosaur-sole.ts.net/api/models

# 3. Check system pressure (OOM = model got evicted)
curl -s https://iu-mac-book.dinosaur-sole.ts.net/api/system

# 4. Tail Ollama logs for errors
curl -s "https://iu-mac-book.dinosaur-sole.ts.net/api/logs/ollama?lines=50"

# 5. Restart if needed
curl -s -X POST https://iu-mac-book.dinosaur-sole.ts.net/api/restart
```

**Audio (TTS/STT) not working:**
```bash
curl -s https://iu-mac-book.dinosaur-sole.ts.net/api/status
curl -s "https://iu-mac-book.dinosaur-sole.ts.net/api/logs/audio?lines=50"
curl -s -X POST https://iu-mac-book.dinosaur-sole.ts.net/api/restart
```

**General health check:**
```bash
# Single-call overview
curl -s https://iu-mac-book.dinosaur-sole.ts.net/api/snapshots/summary
```

---

## Notes

- `/restart` only restarts AI services (Ollama + audio + monitor) — the API itself stays up
- `/models` shows VRAM state: if `total_vram_gb` is high but Ollama is unresponsive, a stuck inference is likely → restart
- `/system` `memory_pressure` field: `normal` = fine, `warn` / `critical` = model may get evicted
- 5-min monitoring snapshots are stored in SQLite on the M2 Max — use `/analytics?hours=1` for recent trend
- This skill is kept in sync with the live OpenAPI spec at `/api/openapi.json` — run `/docs` in the localai project after API changes
