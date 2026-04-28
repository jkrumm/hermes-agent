---
name: homelab-api
description: Call the homelab REST API (https://api.jkrumm.com) for TickTick tasks, Gmail, Google Calendar, Docker containers (homelab + VPS), UptimeKuma monitors, and Slack — use curl with Bearer $HOMELAB_API_KEY
version: 1.0.0
metadata:
  hermes:
    tags: [ticktick, tasks, gmail, calendar, docker, uptime, slack, homelab, api]
    related_skills: []
---

# Homelab API

Personal integration layer for TickTick, Gmail, Calendar, Docker, UptimeKuma, and Slack over a single authenticated REST API. Use `curl` with `$HOMELAB_API_KEY` from the environment.

**Base URL:** `https://api.jkrumm.com`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY` (available in env)
**OpenAPI spec:** `https://api.jkrumm.com/docs/json`

When asked about tasks, schedule, emails, infrastructure status, or Slack messages — use this API. Do not say you lack tooling; use curl via the terminal.

---

## Endpoint Groups

### Summary — start here for status overviews
| Method | Path | Description |
|-|-|-|
| GET | `/summary` | Single-call snapshot: UptimeKuma status + Docker summaries (homelab + VPS) + TickTick alerts |

### TickTick — task management
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/ticktick/projects` | — | All projects with metadata |
| GET | `/ticktick/project/{projectId}/data` | — | Project tasks, columns, details |
| POST | `/ticktick/task` | `title`, `projectId?`, `dueDate?`, `priority?`, `content?`, `startDate?`, `isAllDay?` | Create task |
| POST | `/ticktick/task/{taskId}` | same as create | Update task |
| POST | `/ticktick/project/{projectId}/task/{taskId}/complete` | — | Complete task |
| DELETE | `/ticktick/project/{projectId}/task/{taskId}` | — | Delete task |

### Gmail — email read-only
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/gmail/emails` | `days?`, `label?`, `read?`, `starred?`, `important?`, `query?` | List emails with filtering |
| GET | `/gmail/emails/{id}` | — | Full email with decoded body + attachment metadata |

### Google Calendar — read-only
| Method | Path | Description |
|-|-|-|
| GET | `/gmail/calendar` | Upcoming events across all personal calendars (30-day window) |

### UptimeKuma — monitor status
| Method | Path | Description |
|-|-|-|
| GET | `/uptime-kuma/monitors` | All monitors: live status, ping, uptime ratios (1d/30d). `status: 1` = UP, `status: 0` = DOWN |
| GET | `/uptime-kuma/status` | Summary counts: up/down/total — use this first for "any down?" checks |

### Docker — HomeLab
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/docker/homelab/containers` | — | All containers: state, health, restart count |
| GET | `/docker/homelab/stats` | — | CPU%, memory MB, network I/O for running containers |
| GET | `/docker/homelab/logs/{name}` | `tail?` (default 100) | Recent log lines for container |
| GET | `/docker/homelab/summary` | — | Host resources + container counts + health alerts |

### Docker — VPS
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/docker/vps/containers` | — | All containers: state, health, restart count |
| GET | `/docker/vps/stats` | — | CPU%, memory MB, network I/O for running containers |
| GET | `/docker/vps/logs/{name}` | `tail?` (default 100) | Recent log lines for container |
| GET | `/docker/vps/summary` | — | Host resources + container counts + health alerts |

### Weather — forecast (Open-Meteo)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/weather/forecast` | `city?` (default Munich) | Current + 48h hourly + 7-day daily — temp, rain, clouds, UV, wind. Geocoded via Open-Meteo. |

### Slack
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/slack/channels` | `type?`, `exclude_archived?` | List channels, groups, DMs |
| GET | `/slack/channels/{channelId}/messages` | `oldest?`, `latest?` | Message history with pagination |
| POST | `/slack/channels/{channelId}/messages` | `text` | Send message to channel |
| GET | `/slack/channels/{channelId}/messages/{threadTs}/thread` | — | Thread replies |
| POST | `/slack/channels/{channelId}/messages/{threadTs}/reply` | `text` | Reply to thread |
| GET | `/slack/search` | `query` (supports Slack operators: `in:#channel`, `from:@user`) | Full-text search |
| GET | `/slack/users` | — | Workspace users (cached 5 min) |
| GET | `/slack/unreads` | — | Channels with unread messages, sorted by count |

---

## Usage Pattern

```bash
# Status overview
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/summary"

# Today's tasks (get projects first, then fetch tasks per project)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/ticktick/projects"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/ticktick/project/{projectId}/data"

# Today's calendar events
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/calendar"

# Container health
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/homelab/summary"

# Create a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Task title","projectId":"inbox"}' \
  "https://api.jkrumm.com/ticktick/task"
```

---

## Notes

- This is the **full endpoint reference** — use domain-specific skills for focused guidance:
  - `infrastructure` — UptimeKuma + Docker (decision trees, field semantics, formatting)
  - `tasks` — TickTick (CRUD workflows, priority/date semantics)
  - `schedule` — Calendar + Gmail (search syntax, event formatting)
  - `weather` — forecast for any city, default Munich (thresholds, response formatting)
  - `slack` — Slack search, unreads, channel history, messaging
- Only load this skill when no domain skill matches, or you need the complete endpoint list
- `/summary` is the most efficient first call for morning briefings or status checks
- Slack search supports Slack operator syntax (`in:#hermes`, `from:@johannes`)
- This skill is auto-regenerated from the live OpenAPI spec — run `/docs` in the homelab project after API route changes
