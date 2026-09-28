# Schedule & Email (Google Calendar + Gmail + Proton)

Check upcoming events across all personal calendars and query mail. Two
separate APIs, two separate bearer keys — do not mix them up.

## Calendar — argo

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

## Mail (Gmail + Proton) — email-gateway

**Not argo.** Gmail reads moved here 2026-09-28 (email-gateway
`docs/architecture.md` Decision D3); this door also reaches the owner's
Proton `hello@` mailbox, which argo never exposed.
**Base URL:** `https://mail.<domain>` (the owner's email-gateway host)
**Auth:** `Authorization: Bearer $EMAIL_GATEWAY_API_KEY` (distinct from
`$EMAIL_GATEWAY_SECRET_KEY`, which fpp-analytics uses for the *send* routes —
this is the mail *read* API's own key)

---

## Quick Commands

```bash
# Upcoming calendar events (default 30 days)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/calendar"

# Shorter window
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/calendar?days=7"

# Which mail accounts are configured (find the right `account` id — e.g.
# gmail:me@gmail.com or proton:hello@<domain>)
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" "https://mail.<domain>/api/accounts"

# Recent emails, Gmail only, last 3 days. Unlike the old /gmail/emails
# proxy, `since`/`until` are absolute ISO 8601 timestamps, not a relative
# `days` count — compute the timestamp yourself (e.g. `date -u -v-3d
# +%Y-%m-%dT%H:%M:%S.000Z` or the language equivalent).
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" \
  "https://mail.<domain>/api/messages?account=gmail:me@gmail.com&since=2026-09-25T00:00:00.000Z&limit=25"

# Omit `account` to see every synced mailbox (Gmail + Proton) — a real
# capability upgrade over the old Gmail-only proxy; scope to one account
# only when the ask is specifically about Gmail.
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" \
  "https://mail.<domain>/api/messages?since=2026-09-25T00:00:00.000Z&limit=25"

# Messages the classifier flagged as needing action (its own LLM judgment —
# not the same as Gmail's native "important"/"starred" flags)
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" \
  "https://mail.<domain>/api/needs-action?limit=25"

# Free-text search (subject, addresses, classification summary — NOT
# bodies, and NOT a per-field from:/to:/subject: query — see gaps below)
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" \
  "https://mail.<domain>/api/search?q=amazon.de&limit=25"

# One message: envelope + classification. Add include=body for the cached
# html/text (never a live provider fetch).
curl -s -H "Authorization: Bearer $EMAIL_GATEWAY_API_KEY" \
  "https://mail.<domain>/api/messages/<key>?include=body"
```

**Two capability gaps vs. the old `/gmail/emails` proxy — do not invent
parameters that don't exist:**
- No `unread=`/`important=`/`starred=` filter. Each message's `flags:
  string[]` carries raw IMAP flags — derive unread from the *absence* of
  `\Seen`, starred/important from the *presence* of `\Flagged`.
- No `query=from:X`/`to:X`/`subject:X` field search. `/api/search`'s `q` is
  free-text over subject/addresses/summary only, no operator syntax.

---

## Decision Tree

**"What's on my calendar?" / "Any meetings today?"**
→ Call `/calendar?days=7` — filter results to today/this week in your response
→ Events include `start`, `end`, `isAllDay`, `location`, `videoLink`, `attendees`

**"What's my schedule this week?"**
→ Combine `/calendar?days=7` with tasks from the tasks reference for a full picture

**"Any new emails?" / "Check my inbox"**
→ Call `/api/messages?since=<3 days ago, ISO>&limit=25` (add `account=` to
scope to one mailbox); note messages have no unread flag param — check each
row's `flags` for `\Seen` if the ask is specifically about unread mail
→ Show subject, sender, and the classification summary — don't fetch bodies
(`include=body`) unless asked to read one

**"Anything I need to deal with?"**
→ Call `/api/needs-action?limit=25` — this is the classifier's judgment, not
a Gmail flag; say so if asked why something is/isn't on the list

**"What did X send me?" / email search**
→ `/api/search?q=<free text>` — a name or domain works; there is no
`from:`/`to:` operator, so a full email address in `q` is your best bet, not
guaranteed to be precise
→ To find every message from one address reliably, list `/api/messages` for
the relevant account and filter client-side on `fromAddress`, since search
only covers subject/addresses/summary text

**"Read that email" / "What does it say?"**
→ Call `/api/messages/<key>?include=body` for the cached html/text (the
`key` comes from a prior list/search call, not a Gmail message id)
→ For a longer thread, `/api/threads/<key>/summary` gives a cached 2-4
sentence LLM summary instead of reading every message

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

### Messages (`/api/messages`, `/api/needs-action`, `/api/search` results)
| Field | Notes |
|-|-|
| `key` | Stable message id — use this, not a Gmail message id, for every follow-up call |
| `account` | `gmail:<address>` or `proton:<address>` — which mailbox this came from |
| `fromAddress` / `toAddresses` | Sender / recipients |
| `subject` / `date` | Envelope subject and date |
| `flags` | Raw IMAP flags (`\Seen`, `\Flagged`, …) — derive read/starred state from these, there is no separate boolean field |
| `threadKey` | Pass to `/api/threads/:key` or `/api/threads/:key/summary`; `null` if the message has no known thread |
| `classification` | `{ category, priority, actionRequired, summary, suggestedAction, language, facts }` — the LLM's own read on the message, `null` until classified |
| `body` | Only present with `?include=body` on `/api/messages/:key` — `{ html, text }`, may be `null` if never cached |

### Query params
| Param | Applies to | Notes |
|-|-|-|
| `account` | `/api/messages`, `/api/needs-action`, `/api/search` | e.g. `gmail:me@gmail.com`; comma-separated for multiple; omit for every account |
| `since` / `until` | `/api/messages`, `/api/needs-action` | Absolute ISO 8601, not a relative day count |
| `limit` | most list endpoints | 1-100, default 25 |
| `cursor` | most list endpoints | From the previous response's `nextCursor`, for the next page |

---

## Response Formatting

- **Today's schedule:** List events chronologically with time, title, and location/video link. Flag conflicts.
- **Email summary:** Group by the classifier's `priority`/`actionRequired` when available, otherwise most-recent-first. Show sender + subject + `classification.summary` (fall back to a short excerpt of the body only if not yet classified and the caller asked to read it).
- **Don't dump raw attendee lists** unless asked — just mention count ("3 attendees, all accepted")
- **All-day events:** Show as "All day" not a time range
- **Calendar + tasks combo:** When asked about "my day" or "schedule", consider combining calendar events with due tasks for a complete picture
- **Say which mailbox:** since this door now spans Gmail and Proton, name the account (`gmail:…`/`proton:…`) when it isn't obvious from context, so the owner isn't left guessing which inbox a result came from
