---
name: m365
description: IU work Microsoft 365 surface — read-only Outlook calendar (today, upcoming, free/busy). Mail is intentionally NOT exposed. Teams routes ship under the same tag when they land.
version: 1.0.0
metadata:
  hermes:
    tags: [m365, outlook, iu, work, calendar, teams, meetings]
    related_skills: [schedule, argo-api]
---

# M365 (IU Microsoft 365)

Argo wraps the IU M365 MCP server (Outlook + Teams + Graph) behind a curated read-only REST surface on `argo.jkrumm.com/api`. **Source of truth: argo's `/api/openapi/json` filtered by `tag=M365`.** Routes are added there without re-deploying Hermes — when a question doesn't fit the curated commands below, re-hit the spec.

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`
**Scope:** read-only. Write paths (send mail, create meeting, post Teams message) are deliberately not exposed — decline gracefully if asked.

---

## When to route here

- "my calendar", "next meeting", "what's tomorrow", "agenda for the week", "do I have time on Friday"
- "wann hab ich Zeit", "was steht an", "nächster Termin"
- "Teams meeting link for X", "join URL for the Y call"
- Anything about **IU work meetings or colleagues** (johannes.krumm@iu.org)

**Personal calendar** (Google) lives in `schedule` — route those queries to `GET /calendar` instead. See *Schedule vs M365* in SOUL.md.

**Mail (Outlook):** not exposed. If asked "do I have any IU emails", decline — mail is explicitly out of scope.

---

## Quick Commands

```bash
# Upcoming work meetings (default 14 days, cap days≤60)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/calendar/upcoming?days=14"

# This week's work calendar
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/calendar/upcoming?days=7"

# Today + tomorrow
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/calendar/upcoming?days=2"

# Discover new M365 routes (Teams, channels, alerts) as they land
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/openapi/json" | jq '.paths | to_entries[] | select(.value | to_entries[].value.tags? // [] | contains(["M365"])) | .key'
```

---

## Decision Tree

**"What's on my work calendar?" / "Any IU meetings today?"**
→ Call `/m365/calendar/upcoming?days=2` and filter client-side to today.

**"What's on my work calendar this week?"**
→ Call `/m365/calendar/upcoming?days=7`. Summarize by day; mention conflicts (overlap) explicitly.

**"Any meetings tomorrow?"**
→ Call `/m365/calendar/upcoming?days=2`, filter to tomorrow's date in `start`.

**"Join link for the prometheus daily" / "Teams URL for X"**
→ Call `/m365/calendar/upcoming?days=7`, match `title` (fuzzy), return `videoLink`. If no match, say so — do **not** fabricate a link.

**"Do I have time on Friday?" / "When am I free?"**
→ Call `/m365/calendar/upcoming?days=<enough to cover Friday>`. Cross-reference with the personal `/calendar` if the question is ambiguous about work vs personal.

**Anything that smells like an M365 question but doesn't fit above**
→ Re-hit `/api/openapi/json`, look for the matching `tag=M365` route, use it. New routes (Teams messages, channels, presence) will land under the same tag.

**"Send a Teams message to X" / "Reply to that meeting invite" / write paths in general**
→ Decline politely. Read-only surface by design. Do **not** attempt to dispatch through any "generic execute" path — there are none, intentionally.

**"Do I have any IU emails?" / Outlook mail**
→ Decline politely. Mail is out of scope. Personal Gmail is available via `schedule` — make sure the user wants work mail before redirecting (they usually don't).

---

## Field Semantics

### `/m365/calendar/upcoming` response

Returns an array of events sorted by `start`. Fields:

| Field | Notes |
|-|-|
| `id` | Outlook event ID |
| `title` | Subject line |
| `start` / `end` | UTC ISO 8601 — convert to Europe/Berlin for display |
| `isAllDay` | `true` = no specific time |
| `isOnlineMeeting` | `true` = Teams/Zoom/etc. is attached |
| `location` | Free-text room or location string (nullable) |
| `organizer` | `{name, email}` |
| `attendees` | Array — count usually more useful than names |
| `bodyPreview` | First few lines of the invite body (plaintext) |
| `videoLink` | Teams/Meet/Zoom join URL (nullable) |
| `webLink` | Outlook Web URL for the event |

**Time-zone gotcha:** `start` and `end` are UTC. Always convert before showing local times.

---

## Response Formatting

- **Work meetings in a daily briefing:** prefix with `:office:` so they're visually distinct from personal events.
- **Time first, then title.** Mention attendee count only if relevant (e.g. >5 attendees = wider audience).
- **Video link:** present as a single hint ("Teams") rather than dumping the full URL unless asked.
- **All-day events:** show as "All day" not a time range.
- **Conflicts:** if two work events overlap, flag it ("⚠ conflicts with 14:00 …").

---

## Failure Mode

`503 M365 not authenticated …` (token expired or revoked) → tell the user to run `bun m365:auth:prod` from `~/SourceRoot/argo`. Do **not** retry silently. In briefings, surface as a single line ("IU work calendar unavailable — token expired") and continue with the rest of the report.

Other non-2xx → name the status code, do not retry, do not pretend the data was returned.
