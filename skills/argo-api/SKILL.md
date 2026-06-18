---
name: argo-api
description: Call the argo REST API (https://argo.jkrumm.com/api) for TickTick tasks, Gmail, Calendar, Docker (homelab + VPS), UptimeKuma, Slack, weather, Garmin Health, Strength tracking, WalkingPad treadmill stats, AI usage/cost, user profile, and read-only SQL — use curl with Bearer $HOMELAB_API_KEY
version: 1.5.0
metadata:
  hermes:
    tags: [ticktick, tasks, gmail, calendar, docker, uptime, slack, weather, garmin, strength, workouts, weight, profile, walking-pad, walkingpad, treadmill, steps, usage, cost, spend, tokens, sql, homelab, api]
    related_skills: [capture, work, karakeep, obsidian, reading, research-gateway]
---

# Argo API

Personal integration layer for TickTick, Gmail, Calendar, Docker, UptimeKuma, Slack, weather, fitness tracking, and user profile over a single authenticated REST API. Use `curl` with `$HOMELAB_API_KEY` from the environment (env var name kept for shell/cron compatibility — the value is the argo API key).

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY` (available in env)
**OpenAPI spec:** `https://argo.jkrumm.com/api/openapi/json`
**Discovery:** `GET /` — public root returning `{name, version, description, docs, auth, tags[]}`. Use for bootstrap orientation; read `/openapi/json` for the full surface.

When asked about tasks, schedule, emails, infrastructure status, or Slack messages — use this API. Do not say you lack tooling; use curl via the terminal.

## Response envelope — listing endpoints

**Listing endpoints** wrap their results in `{data: [...], total: N}`:

- `/daily-metrics`, `/activities`, `/weight-log` (Garmin Health)
- `/workouts`, `/workout-sets`, `/exercises` (Strength)

Always read `response.data` for the array and `response.total` for the row count. **Bare arrays are no longer returned.**

**Detail / aggregate / summary endpoints** return bare objects:

- `/recovery`, `/training-load`, `/fitness-direction`, `/user-profile`
- `/workouts/summary/*` (each has its own shape — `points[]`, `byExercise{}`, etc.)
- `/summary`, `/health`, `/calendar`, `/weather/forecast`
- `/daily-metrics/{summary,series,sync-status}`, `/weight-log/{summary,series}`, `/activities/summary`
- `/uptime-kuma/{status,monitors}`, `/docker/*/{summary,stats,containers}`

## Tag taxonomy (14 tags — what this skill covers)

The live OpenAPI surface has **14 tags**. They split three ways: this skill (`argo-api`)
owns the **personal** domains; IU-work domains live in the separate `work` skill; two
tags are infrastructure Hermes deliberately does **not** call.

**Personal — this skill (`argo-api`):**

| Tag | Covers | Focused guidance |
|-|-|-|
| **Garmin Health** | `/daily-metrics/*`, `/activities/*`, `/recovery/*`, `/training-load`, `/fitness-direction`, `/weight-log/*`, `/user-profile` | `references/garmin-health.md` |
| **Strength** | `/workouts/*` (incl. all 13 `/workouts/summary/*` analytics), `/workout-sets/*`, `/exercises` | `references/strength.md` |
| **WalkingPad** | `/walking-pad/*` — treadmill sessions, live snapshot, achievements, analytics | `references/walking-pad.md` |
| **Productivity** | `/ticktick/*`, `/gmail/*`, `/calendar`, `/slack/*` | `references/{tasks,schedule,slack}.md` |
| **Infrastructure** | `/docker/*`, `/uptime-kuma/*` | `references/infrastructure.md` |
| **External Data** | `/weather/*` | `references/weather.md` |
| **Reading** | `/reading/*` — Hardcover shelf (ratings, genres, statuses, want-to-read) | **`reading` skill** (top-level) |
| **Usage Tracking** | `/usage/*` — AI token/cost KPIs across all sources | group below |
| **System** | `/`, `/health`, `/summary`, `/query`, `/openapi/json`, `/oauth/google/*` | this file |

**Work — the `work` skill (NOT here):** **M365** (`/m365/*`), **Atlassian** (`/atlassian/jira/*` + `/confluence/*`), **GitLab** (`/gitlab/*`). Route IU-work questions there.

**Not agent-facing (Hermes does NOT call these):**
- **Hermes Chat** (`/hermes/*`) — the *argo dashboard → Hermes* path (argo calls Hermes here). Calling it from Hermes would be talking to itself.
- **AI Gateway** (`/ai/v1/*`) — OpenAI-compatible model + audio proxy. Hermes reaches its brain and the **audio-gateway directly** (`config.yaml`), not through Argo's `/ai` hop. Never route TTS/STT/chat through `/ai/v1/*`.

---

## Endpoint Groups

### System — start here for status overviews
| Method | Path | Description |
|-|-|-|
| GET | `/` | Discovery index — name, version, docs, auth scheme, tag list |
| GET | `/summary` | Single-call snapshot: UptimeKuma status + Docker summaries (homelab + VPS) + TickTick alerts |
| GET | `/health` | Service healthcheck |
| POST | `/query` | Execute a read-only SQL query against the homelab DB |
| GET | `/openapi` | Scalar OpenAPI UI |
| GET | `/openapi/json` | Raw OpenAPI 3 spec |

### Productivity — TickTick task management
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/ticktick/projects` | — | All projects with metadata |
| GET | `/ticktick/projects/{projectId}/data` | — | Project tasks, columns, details |
| POST | `/ticktick/tasks` | `title`, `projectId?`, `dueDate?`, `priority?`, `content?`, `startDate?`, `isAllDay?` | Create task |
| POST | `/ticktick/tasks/{taskId}` | same as create | Update task |
| POST | `/ticktick/projects/{projectId}/tasks/{taskId}/complete` | — | Complete task |
| DELETE | `/ticktick/projects/{projectId}/tasks/{taskId}` | — | Delete task |

### Productivity — Gmail (read-only)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/gmail/emails` | `days?`, `maxResults?`, `query?`, `label?`, `unread?`, `important?`, `starred?`, `excludeCategories?`, `scope?` (`inbox`/`all`) | List emails with filtering |
| GET | `/gmail/emails/{id}` | — | Full email with decoded body + attachment metadata |

### Productivity — Google Calendar (read-only)
| Method | Path | Description |
|-|-|-|
| GET | `/calendar` | Upcoming events across all personal calendars (30-day window) |

### Productivity — Slack
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

### Infrastructure — UptimeKuma
| Method | Path | Description |
|-|-|-|
| GET | `/uptime-kuma/monitors` | All monitors: live status, ping, uptime ratios (1d/30d). `status: 1` = UP, `status: 0` = DOWN |
| GET | `/uptime-kuma/status` | Summary counts: up/down/total — use this first for "any down?" checks |

### Infrastructure — Docker (HomeLab)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/docker/homelab/containers` | — | All containers: state, health, restart count |
| GET | `/docker/homelab/stats` | — | CPU%, memory MB, network I/O for running containers |
| GET | `/docker/homelab/logs/{name}` | `tail?` (default 100) | Recent log lines for container |
| GET | `/docker/homelab/summary` | — | Host resources + container counts + health alerts |

### Infrastructure — Docker (VPS)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/docker/vps/containers` | — | All containers: state, health, restart count |
| GET | `/docker/vps/stats` | — | CPU%, memory MB, network I/O for running containers |
| GET | `/docker/vps/logs/{name}` | `tail?` (default 100) | Recent log lines for container |
| GET | `/docker/vps/summary` | — | Host resources + container counts + health alerts |

### External Data — Weather (Open-Meteo)
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/weather/forecast` | `city?` (default Munich) | Current + 48h hourly + 7-day daily — temp, rain, clouds, UV, wind. Geocoded via Open-Meteo. |

### System — Google OAuth (public, no auth required)
| Method | Path | Description |
|-|-|-|
| GET | `/oauth/google/init` | Begin Google OAuth flow |
| GET | `/oauth/google/callback` | OAuth callback handler |

### Garmin Health — daily metrics, activities, recovery, weight, profile
*For focused guidance + field semantics load `references/garmin-health.md`.*

| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/daily-metrics` | `dateFrom?`, `dateTo?`, `order?`, `page?`, `limit?` | Daily Garmin metrics list (HRV, sleep, RHR, body battery, stress) |
| GET | `/daily-metrics/summary` | — | Latest-day summary snapshot |
| GET | `/daily-metrics/series` | `dateFrom?`, `dateTo?` | Time-series across the date range |
| GET | `/daily-metrics/sync-status` | — | garmin-sync state (queued / in-progress / last success) |
| POST | `/daily-metrics/refresh` | — | Trigger an on-demand Garmin sync |
| GET | `/activities` | `dateFrom?`, `dateTo?`, `sort?` (`start_time_local`/`date`/`duration_sec`/`calories`), `order?` | Garmin activities list |
| GET | `/activities/summary` | — | Rolled-up activity counts + duration |
| GET | `/recovery` | — | Composite recovery score (HRV 40% + Sleep 35% + RHR 25%, minus strain-debt) |
| GET | `/recovery/series` | `dateFrom?`, `dateTo?` | Recovery score time-series |
| GET | `/training-load` | — | Whole-body activity ACWR (EWMA acute / chronic, zones from Gabbett 2016) |
| GET | `/fitness-direction` | — | 3-level signal (improving / maintaining / declining) from 14-day RHR + HRV regression |
| GET | `/weight-log` | `order?` | List all weight entries |
| GET | `/weight-log/summary` | — | Latest weight + 7d/30d MA + trend + phase + intensity |
| GET | `/weight-log/series` | `dateFrom?`, `dateTo?` | Weight time-series |
| POST | `/weight-log` | `date!`, `weight_kg!` | Add weight entry |
| DELETE | `/weight-log/{id}` | — | Delete weight entry |
| GET | `/user-profile` | — | Get profile (single row, auto-created on first access) |
| PUT | `/user-profile` | `height_cm?`, `birth_date?`, `gender?`, `goal_weight_kg?` | Update profile fields |

### Strength — workouts, sets, exercises, analytics
*For focused guidance, set-type semantics, and the full analytics suite load `references/strength.md`.*

| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/exercises` | — | All exercises sorted by `display_order` |
| GET | `/workouts` | `dateFrom?`, `dateTo?`, `exercise?`, `sort?` (`date`/`id`/`exercise_id`/`created_at`), `order?`, `page?`, `limit?` | List workouts |
| GET | `/workouts/{id}` | — | Workout with sets and computed e1RM metrics |
| POST | `/workouts` | `date!`, `exercise_id!`, `sets!`, `notes?` | Create workout with sets (transactional) |
| PATCH | `/workouts/{id}` | `date?`, `exercise_id?`, `notes?`, `sets?` | Update workout |
| DELETE | `/workouts/{id}` | — | Delete workout + cascade-delete its sets |
| GET | `/workout-sets` | `workoutId?`, `order?`, `page?`, `limit?` | List workout sets |
| POST | `/workout-sets` | `workout_id!`, `set_number!`, `set_type!`, `weight_kg!`, `reps!` | Create workout set |
| PATCH | `/workout-sets/{id}` | `set_number?`, `set_type?`, `weight_kg?`, `reps?` | Update workout set |
| DELETE | `/workout-sets/{id}` | — | Delete workout set |
| GET | `/workouts/summary/strength` | — | Per-exercise aggregates: `currentE1RM`, `bestE1RM`, volume, trends |
| GET | `/workouts/summary/series` | — | Strength time-series by exercise |
| GET | `/workouts/summary/series-detailed` | — | Per-session e1RM + 30d MA + INOL + max weight + best set + volume |
| GET | `/workouts/summary/sparklines` | — | Compact arrays per exercise (last 20 e1RM, 10 weekly volume, 15 INOL) + velocity + direction |
| GET | `/workouts/summary/records` | — | Running-max PRs per exercise + metric |
| GET | `/workouts/summary/relative-progression` | — | % change of best-of-day e1RM from first-in-window baseline |
| GET | `/workouts/summary/weekly-volume` | — | Per-exercise weekly tonnage by set_type + MEV/MAV/MRV landmarks |
| GET | `/workouts/summary/training-load` | — | Per-exercise ACWR (strength-specific, weekly tonnage). Zones identical to Garmin `/training-load` |
| GET | `/workouts/summary/heroes` | — | Hero composites for the strength tracker dashboard |
| GET | `/workouts/summary/composite/{exerciseId}` | — | Z-scored composite signals for one exercise |
| GET | `/workouts/summary/alignment` | — | 3×3 grid bucketing sessions by recovery × ACWR (90-day window) |
| GET | `/workouts/summary/deload-signal` | — | Verdict ∈ {`progress`, `monitor`, `deload`} + active signal list |
| GET | `/workouts/summary/readiness` | — | Per-day strength readiness from Garmin recovery + fatigue debt (48h lookback); the cross-skill "ready to train hard today?" endpoint |

### WalkingPad — treadmill sessions, live state, analytics
*For field semantics + response formatting load `references/walking-pad.md`.*

| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/walking-pad/sessions/summary` | `dateFrom?`, `dateTo?` | Totals over a window: `sessions`, `duration_s`, `distance_m`, `steps`, `kcal`, `avg_session_min`. **Start here for "how much did I walk?"** |
| GET | `/walking-pad/sessions` | `dateFrom?`, `dateTo?`, `order?`, `page?`, `limit?` | List sessions |
| GET | `/walking-pad/sessions/series` | `dateFrom?`, `dateTo?`, `bucket?` | Time-bucketed series for charts |
| GET | `/walking-pad/sessions/heroes` | — | Hero stats: total volume, pace, streak |
| GET | `/walking-pad/sessions/hour-of-day` | — | Hour-of-day × day-of-week matrix |
| GET | `/walking-pad/sessions/length-histogram` | — | Session-length distribution |
| GET | `/walking-pad/live` | — | Current live session snapshot (null if idle) |
| GET | `/walking-pad/achievements` | — | Unlocked achievements |

*Write endpoints (`POST /walking-pad/{live,sessions}`, `DELETE …/sessions/{uuid}`) are device-ingest only — Hermes reads, doesn't push sessions.*

### Usage Tracking — AI token/cost telemetry
| Method | Path | Key params | Description |
|-|-|-|-|
| GET | `/usage/headline` | — | KPI snapshot: `costUsd30d`, `costUsd7d`, `tokens30d`, `errorRate30d`, `cacheHitRatio30d`, `sourcesActive`. **Start here for "what have I spent on AI?"** |
| GET | `/usage/summary` | `dateFrom?`, `dateTo?` | Aggregated record summary over a window |
| GET | `/usage/breakdown` | `by?` (source/model) | Cost/token breakdown by dimension |
| GET | `/usage/timeseries` | `dateFrom?`, `dateTo?`, `bucket?` | Cost/token series for charts |

*`POST /usage/records` is collector-ingest only — not agent-facing.*

### Reading — Hardcover shelf
The Reading tag (`/reading/*`) is owned by the dedicated **`reading` skill** (book
recommendations + Hardcover shelf). For a bare taste pull use `GET /api/reading`
(summary + shelf); for recommendations, freshness sync, and want-to-read, load that skill.

---

## Usage Pattern

```bash
# Discovery (start here if unsure what exists)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/"

# Status overview
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/summary"

# Today's tasks (get projects first, then fetch tasks per project)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/ticktick/projects"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/ticktick/projects/{projectId}/data"

# Today's calendar events
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/calendar"

# Container health
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/docker/homelab/summary"

# Create a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Task title","projectId":"inbox"}' \
  "https://argo.jkrumm.com/api/ticktick/tasks"
```

---

## Notes

- This is the **full endpoint reference** — load domain-specific references for focused guidance (decision trees, field semantics, response formatting):
  - `references/infrastructure.md` — UptimeKuma + Docker health checks and field semantics
  - `references/tasks.md` — TickTick CRUD workflows, priority/date codes, project resolution
  - `references/schedule.md` — Calendar + Gmail search syntax, event/email formatting
  - `references/weather.md` — Forecast thresholds, geocoding, response guidance
  - `references/slack.md` — Search operators, known channel IDs, response formatting
  - `references/garmin-health.md` — Daily metrics, recovery, training-load, fitness-direction, weight log, user profile (field semantics, trend arrows, null handling)
  - `references/strength.md` — Workouts, sets, full `/workouts/summary/*` analytics suite (e1RM, INOL, ACWR, volume landmarks, readiness, deload-signal)
  - `references/walking-pad.md` — WalkingPad treadmill sessions, live snapshot, achievements, analytics (field semantics, response formatting)
- The `reading` skill owns `/reading/*` (Hardcover shelf + book recommendations); the `research-gateway` skill owns deep cited web research (the research-gateway service, not Argo).
- The `capture` skill provides TickTick + GitHub Issue routing for new captures (standalone — has its own state cache and routing logic)
- Endpoint groups without a domain reference yet: `/query` (SQL escape hatch), `/health`, `/oauth/*`. Call them via this skill.
- Only load this skill when no domain reference matches, or you need the complete endpoint list
- `/summary` is the most efficient first call for morning briefings or status checks
- Slack search supports Slack operator syntax (`in:#hermes`, `from:@johannes`) + optional `sort`, `sortDir`, `count`, `page` paging params
- `/query` accepts arbitrary read-only SQL (JSON body: `{"sql": "SELECT …"}`). Use sparingly — prefer named endpoints when one exists.
- **Query param convention:** canonical names are camelCase (`dateFrom`, `dateTo`, `workoutId`, `sortDir`) and json-server-style underscored aliases (`_order`, `_sort`, `_start`, `_end`, `date_from`) still work as backwards-compat. Prefer canonical names in new code; keep legacy in the morning-briefing cron prompt for stability.
- **Request body fields** are snake_case where the schema says so (`exercise_id`, `weight_kg`, `set_number`, `set_type`, `birth_date`, `height_cm`, `goal_weight_kg`); response field naming is unchanged from each endpoint's source.
- **Trailing slashes** are tolerated but not preferred — use `/workouts`, not `/workouts/`.
- This skill is auto-regenerated from the live OpenAPI spec (`https://argo.jkrumm.com/api/openapi/json`) — run `/docs` in the homelab project after API route changes. The regen pass rewrites this file using the **14-tag taxonomy** above: keep the personal / work / not-agent-facing split (don't fold M365/Atlassian/GitLab in here — they're the `work` skill — and never add `/hermes/*` or `/ai/v1/*`).
