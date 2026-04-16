---
name: schedule
description: Check Google Calendar events and Gmail inbox — upcoming meetings, today's schedule, important emails, and email search via homelab API
version: 1.0.0
metadata:
  hermes:
    tags: [calendar, gmail, email, schedule, meetings, events]
    related_skills: [homelab-api]
---

# Schedule & Email (Google Calendar + Gmail)

Check upcoming events across all personal calendars and query the Gmail inbox.

**Base URL:** `https://api.jkrumm.com`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Upcoming calendar events (default 30 days)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/calendar"

# Shorter window
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/calendar?days=7"

# Recent emails (default 7 days, max 50)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails?days=3"

# Unread emails only
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails?unread=true"

# Important/starred emails
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails?important=true"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails?starred=true"

# Search with Gmail query syntax
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails?query=from:amazon.de"

# Full email body (when asked about a specific email)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/gmail/emails/{id}"
```

---

## Decision Tree

**"What's on my calendar?" / "Any meetings today?"**
→ Call `/gmail/calendar?days=7` — filter results to today/this week in your response
→ Events include `start`, `end`, `isAllDay`, `location`, `videoLink`, `attendees`

**"What's my schedule this week?"**
→ Combine `/gmail/calendar?days=7` with tasks from the `tasks` skill for a full picture

**"Any new emails?" / "Check my inbox"**
→ Call `/gmail/emails?unread=true&days=3`
→ Show subject, sender, and snippet — don't read full bodies unless asked

**"What did X send me?" / email search**
→ Use `/gmail/emails?query=from:person@example.com`
→ Gmail query syntax works: `from:`, `to:`, `subject:`, `has:attachment`, `after:YYYY/MM/DD`

**"Read that email" / "What does it say?"**
→ Call `/gmail/emails/{id}` for full decoded body

---

## Field Semantics

### Calendar Events
| Field | Notes |
|-|-|
| `start` / `end` | ISO timestamp, or `YYYY-MM-DD` for all-day events |
| `isAllDay` | `true` = no specific time |
| `attendees` | Array with `status`: `accepted`, `declined`, `tentative`, `needsAction` |
| `videoLink` | Google Meet or conference link (nullable) |
| `calendarName` | Which calendar the event belongs to |

### Emails
| Field | Notes |
|-|-|
| `snippet` | 200-char preview — usually enough for overview |
| `isRead` | `true` = already read |
| `hasAttachments` | Check before mentioning attachments |
| `labels` | Gmail label IDs (INBOX, IMPORTANT, STARRED, etc.) |
| `body` | Only in `/emails/{id}` — decoded plaintext |

### Email Filters
| Param | Default | Notes |
|-|-|-|
| `days` | 7 | How far back to search |
| `maxResults` | 50 | Cap results |
| `scope` | inbox (or all if label set) | `all` includes archived |
| `excludeCategories` | spam, promotions, forums | Auto-excluded |

---

## Response Formatting

- **Today's schedule:** List events chronologically with time, title, and location/video link. Flag conflicts.
- **Email summary:** Group by importance — unread first, then starred, then recent. Show sender + subject + snippet.
- **Don't dump raw attendee lists** unless asked — just mention count ("3 attendees, all accepted")
- **All-day events:** Show as "All day" not a time range
- **Calendar + tasks combo:** When asked about "my day" or "schedule", consider combining calendar events with due tasks for a complete picture
