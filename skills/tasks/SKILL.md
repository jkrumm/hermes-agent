---
name: tasks
description: Manage TickTick tasks — list projects, view tasks, create, update, and complete tasks via homelab API with curl
version: 1.0.0
metadata:
  hermes:
    tags: [ticktick, tasks, todo, projects, productivity]
    related_skills: [homelab-api]
---

# Task Management (TickTick)

Query, create, update, and complete tasks in TickTick.

**Base URL:** `https://api.jkrumm.com`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# List all projects (get projectId for further queries)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/ticktick/projects"

# Get tasks for a specific project
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/ticktick/project/{projectId}/data"

# Overdue + due-soon tasks (from /summary, includes project names)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/summary" | jq '.ticktick'

# Create a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Task title","projectId":"inbox","dueDate":"2026-04-20","priority":3}' \
  "https://api.jkrumm.com/ticktick/task"

# Update a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Updated title","priority":5}' \
  "https://api.jkrumm.com/ticktick/task/{taskId}"

# Complete a task
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://api.jkrumm.com/ticktick/project/{projectId}/task/{taskId}/complete"

# Delete a task
curl -s -X DELETE -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://api.jkrumm.com/ticktick/project/{projectId}/task/{taskId}"
```

---

## Workflow

**"What are my tasks?" / "What's due?"**
→ Call `/summary` first — it returns `overdue` and `dueSoon` (next 7 days) with project names already resolved
→ Only call `/ticktick/projects` + `/ticktick/project/{id}/data` if full project listing is needed

**"Add a task" / "Remind me to..."**
→ POST to `/ticktick/task` with at minimum `title`
→ Use `projectId: "inbox"` if no project specified
→ Always use `YYYY-MM-DD` for dates

**"Mark X as done"**
→ Need both `projectId` and `taskId`
→ `/summary` gives `taskId` and `projectName` but NOT `projectId` — call `/ticktick/projects` to resolve the name to an ID
→ POST to `/ticktick/project/{projectId}/task/{taskId}/complete`

---

## Field Semantics

### Priority
| Value | Meaning |
|-|-|
| `0` | None |
| `1` | Low |
| `3` | Medium |
| `5` | High |

### Task Status
| Value | Meaning |
|-|-|
| `0` | Active |
| `2` | Completed |

### Dates
- Always use `YYYY-MM-DD` format when creating or updating tasks
- API returns dates in `YYYY-MM-DD` format
- `dueDate` — when the task is due
- `startDate` — optional, when to start working on it

---

## Response Formatting

- **Today's tasks:** Group by project, show title + due date + priority (if set). Lead with overdue items.
- **Task created:** Confirm title, project, and due date in one line
- **Quick overview:** Use `/summary` ticktick data — it already groups overdue vs due-soon
- **Don't list closed projects** — filter by `closed: false` if listing projects
