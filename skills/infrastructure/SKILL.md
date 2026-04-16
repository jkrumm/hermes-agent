---
name: infrastructure
description: Check service uptime, Docker container health, resource usage, and logs across homelab and VPS — use curl with Bearer $HOMELAB_API_KEY
version: 1.0.0
metadata:
  hermes:
    tags: [uptime, docker, containers, homelab, vps, infrastructure, monitoring, health]
    related_skills: [homelab-api, localai-debug]
---

# Infrastructure Status

Monitor service uptime (UptimeKuma) and Docker container health across homelab and VPS.

**Base URL:** `https://api.jkrumm.com`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Best first call — single snapshot of everything
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/summary"

# Any services down?
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/uptime-kuma/status"

# All monitor details (only if asked for specifics)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/uptime-kuma/monitors"

# Docker overview — homelab or vps
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/homelab/summary"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/vps/summary"

# Container resource usage
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/homelab/stats"

# Container logs (use tail=50 for quick checks)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/homelab/logs/container-name?tail=50"
```

---

## Decision Tree

**"Is everything running?" / "Any issues?"**
→ Call `/summary` — one request covers UptimeKuma + Docker homelab + Docker VPS + overdue tasks

**"Any alerts?" / "What happened?" / "Recent warnings?"**
→ Call `/summary` for current status AND check the #alerts Slack channel (`C0AS1LAUQ3C`) for recent automated alerts
→ Use `skill_view('slack')` to search: `curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/channels/C0AS1LAUQ3C/messages?limit=20"`

**"Is X down?" / "What's the uptime?"**
→ Call `/uptime-kuma/status` first (3 numbers: up/down/total)
→ Only call `/uptime-kuma/monitors` if something is down or details requested

**"How are the containers?" / "Docker status?"**
→ Call `/docker/homelab/summary` and/or `/docker/vps/summary`
→ Look at alerts array first — unhealthy containers and high restart counts

**"Why is X broken?" / debugging**
→ Call `/docker/{homelab|vps}/logs/container-name?tail=50`
→ Look for error patterns in recent log lines

**"Resource usage?" / "What's eating memory?"**
→ Call `/docker/{homelab|vps}/stats` for CPU%, memory, network I/O per container

---

## Field Semantics

### UptimeKuma
| Field | Values | Meaning |
|-|-|-|
| `status` | `1` | UP — healthy |
| `status` | `0` | DOWN — alert |
| `status` | `2` | PENDING — checking |
| `status` | `3` | MAINTENANCE — expected downtime |
| `uptime1d` | 0.0–1.0 | 24h uptime ratio (0.99 = 99%) |
| `uptime30d` | 0.0–1.0 | 30-day uptime ratio |

### Docker Containers
| Field | Values | Meaning |
|-|-|-|
| `state` | `running` | Normal operation |
| `state` | `exited` | Stopped (may be intentional) |
| `state` | `restarting` | Crash loop — investigate |
| `health` | `healthy` | Health check passing |
| `health` | `unhealthy` | Health check failing — alert |
| `health` | `none` | No health check configured |
| `restartCount` | > 3 | Suspicious — check logs |

---

## Response Formatting

- **All clear:** One line — "All X monitors up, Y containers healthy across homelab and VPS."
- **Issues found:** Lead with what's down/unhealthy, then context (restart count, uptime ratio, recent log errors)
- **Overview requested:** Group by system (homelab vs VPS), highlight alerts, skip healthy details unless asked
- **Never list all 25+ containers** unless explicitly asked — summarize counts and flag anomalies
