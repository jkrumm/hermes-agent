# Homelab API — Reference

Personal integration layer exposing TickTick, Gmail, Calendar, Docker, UptimeKuma, and Slack
over a single authenticated REST API.

**Base URL:** `https://api.jkrumm.com`
**Auth:** All endpoints (except `/health`) require `Authorization: Bearer ${HOMELAB_API_KEY}`
**OpenAPI spec:** `https://api.jkrumm.com/docs/json`

---

## Endpoint Groups

### Summary (start here for status overviews)
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
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/gmail/calendar` | — | Upcoming events across all personal calendars (30-day window) |

### UptimeKuma — monitor status
| Method | Path | Description |
|-|-|-|
| GET | `/uptime-kuma/monitors` | All monitors: live status, ping, uptime ratios (1d/30d) |
| GET | `/uptime-kuma/status` | Summary counts: up/down/total (excludes monitor groups) |

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
# Status overview (use for morning briefing, watchdog checks)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/summary"

# Today's tasks
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/ticktick/projects"

# Today's calendar
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/calendar"

# Container health (homelab)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/docker/homelab/summary"

# Create a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Task title","projectId":"inbox"}' \
  "https://api.jkrumm.com/ticktick/task"
```

---

## Notes

- `/summary` is the most efficient call for status checks — use it first before drilling into individual endpoints
- Docker logs endpoint: use `?tail=50` for quick checks, omit for full default (100 lines)
- Gmail search supports standard Gmail query syntax in the `query` param (e.g., `is:unread from:newsletter@example.com`)
- Slack search supports Slack operator syntax (e.g., `in:#hermes from:@johannes`)
- This reference is auto-generated from the live OpenAPI spec — run `/docs` in the homelab project to regenerate
