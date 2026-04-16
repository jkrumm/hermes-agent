---
name: slack
description: Search Slack messages, check unreads, read channel history, and send messages — use curl with Bearer $HOMELAB_API_KEY
version: 1.0.0
metadata:
  hermes:
    tags: [slack, messages, search, unreads, channels, threads]
    related_skills: [homelab-api]
---

# Slack

Search messages, check unread channels, read history, and send messages via the homelab API.

**Base URL:** `https://api.jkrumm.com`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

---

## Quick Commands

```bash
# Channels with unread messages (sorted by count, top 10 include latest message)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/unreads"

# Search messages (supports Slack operators)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/search?q=from:@johannes+in:%23hermes"

# Channel history (newest first, default 50)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/channels/{channelId}/messages?limit=20"

# Thread replies
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/channels/{channelId}/messages/{threadTs}/thread"

# List channels (to find channel IDs)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/channels"

# Send a message
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"message here"}' \
  "https://api.jkrumm.com/slack/channels/{channelId}/messages"

# Reply to a thread
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"reply here"}' \
  "https://api.jkrumm.com/slack/channels/{channelId}/messages/{threadTs}/reply"

# Resolve user IDs to names (cached 5 min)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://api.jkrumm.com/slack/users"
```

---

## Decision Tree

**"What did I miss?" / "Any recent messages?"**
→ Check recent messages in relevant channels — use the Known Channels table below for IDs
→ For #alerts: `curl ... "https://api.jkrumm.com/slack/channels/C0AS1LAUQ3C/messages?limit=10"`
→ For #hermes: `curl ... "https://api.jkrumm.com/slack/channels/C0ASRUD7K1U/messages?limit=10"`
→ Note: `/slack/unreads` shows the **bot's** unread state, not the user's — avoid using it for "do I have unreads?" questions

**"Search for X" / "What did Y say about Z?"**
→ Call `/slack/search?q=...` — supports Slack search operators
→ Results grouped by channel with message previews

**"What's happening in #channel?"**
→ Use the Known Channels table for IDs, then `/slack/channels/{id}/messages`
→ Or search: `/slack/search?q=in:%23channel-name`

**"Read that thread" / following up on a message**
→ Call `/slack/channels/{channelId}/messages/{threadTs}/thread`

---

## Search Operators

The search endpoint supports standard Slack query syntax:

| Operator | Example | Meaning |
|-|-|-|
| `in:#channel` | `in:%23hermes` | Messages in a specific channel |
| `from:@user` | `from:@johannes` | Messages from a specific user |
| `has:link` | `has:link` | Messages containing URLs |
| `has:file` | `has:file` | Messages with attachments |
| `before:date` | `before:2026-04-01` | Messages before a date |
| `after:date` | `after:2026-04-10` | Messages after a date |

Combine operators: `from:@johannes in:%23hermes after:2026-04-10`
URL-encode `#` as `%23` in curl.

---

## Field Semantics

| Field | Notes |
|-|-|
| `ts` | Message timestamp — unique ID within a channel, also used as thread parent reference |
| `thread_ts` | If set, this message is part of a thread |
| `reply_count` | Number of replies (only on thread parent messages) |
| `user` | User ID (e.g., `U01ABC123`) — resolve via `/slack/users` if display name needed |
| `text` | May contain Slack mrkdwn (`*bold*`, `<@U123>` user mentions, `<#C123>` channel links) |

---

## Known Channels

Use these IDs directly — no need to call `/slack/channels` first:

| Channel | ID | Purpose |
|-|-|-|
| #hermes | `C0ASRUD7K1U` | Main conversation with Johannes |
| #alerts | `C0AS1LAUQ3C` | Automated Docker/UptimeKuma alerts |
| #watchdog | `C0ASRULFTSS` | Hermes proactive monitoring results |
| #inbox | `C0AT6TB49HP` | Voice memos, links, digests |
| #briefings | `C0AT6TH404R` | Morning/evening audio briefings |
| #journal | `C0ATN8W6N2U` | Structured journal entries |
| #news | `C0ASXJD0ZEG` | Daily digest |

---

## Response Formatting

- **Unreads:** List channels with counts, highlight high-count channels. Don't dump all message text.
- **Search results:** Show channel name + matching messages with brief context
- **Channel history:** Summarize conversation flow, don't list every message verbatim
- **When user IDs appear in messages:** resolve to display names if context requires it, otherwise skip
