# Infrastructure Status

Monitor service uptime (UptimeKuma) and Docker container health across homelab and VPS.

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Best first call — single snapshot of everything
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/summary"

# Any services down?
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/uptime-kuma/status"

# All monitor details (only if asked for specifics)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/uptime-kuma/monitors"

# Docker overview — homelab or vps (interchangeable shape)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/homelab/summary"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/vps/summary"

# Container resource usage (homelab + vps both)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/homelab/stats"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/vps/stats"

# Full container list (state, health, restart count) — rarely needed if /summary suffices
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/homelab/containers"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/vps/containers"

# Container logs (use tail=50 for quick checks) — works for both hosts
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/homelab/logs/container-name?tail=50"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/vps/logs/container-name?tail=50"
```

---

## Decision Tree

**"Is everything running?" / "Any issues?"**
→ Call `/summary` — one request covers UptimeKuma + Docker homelab + Docker VPS + overdue tasks

**"Any alerts?" / "What happened?" / "Recent warnings?"**
→ Call `/summary` for current status AND check the #alerts Slack channel (`C0AS1LAUQ3C`) for recent automated alerts
→ Use the slack reference: `curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/slack/channels/C0AS1LAUQ3C/messages?limit=20"`

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

Both `/uptime-kuma/status` and `/uptime-kuma/monitors` responses are enveloped:

```json
{ "status": "ready", "lastUpdatedAt": "...", "staleSince": null, "lastError": null, "up": 61, "down": 0, "total": 61, "monitors": [...] }
```

| Envelope field | Meaning |
|-|-|
| `status` | `"ready"` / `"loading"` / `"error"` — overall service state |
| `lastUpdatedAt` | When the bridge last refreshed from UptimeKuma |
| `staleSince` | Non-null = bridge hasn't updated since this timestamp — trust signal is shaky |
| `lastError` | Non-null = bridge errored last poll — surface it if asked "is monitoring working?" |

Per-monitor fields (inside `monitors[]`):

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