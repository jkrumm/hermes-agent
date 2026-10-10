# M365 — Teams and calendar

## Calendar

- `/m365/calendar/upcoming?days=N` (default 14, max 60) returns a bare array of work events. Timestamps are UTC — see `gotchas.md`.
- **Recurring meetings are flattened.** Each occurrence is its own entry; no series objects.
- Personal calendar (Google) is not here — `argo-api` `references/schedule.md`.

## Teams — curated alerts vs. browsing

- **`/m365/important` is curated, not search — and never wired into briefings/watchdog.** Only returns messages from chats and channels Johannes labeled via the dashboard (`POST /m365/labels`). Common labels: `alerts`, `pr-reviews`, `general`. If an expected chat returns nothing, it isn't labeled — say so ("doesn't look like that chat is labeled — add it in the dashboard if you want it surfaced here") rather than trying to discover content via `/m365/chats` or `/m365/teams/.../channels`. This endpoint is **ad-hoc only**: it is intentionally not folded into the morning briefing, evening report, or watchdog (work signals don't belong in those — see SOUL.md's personal-orientation rule).
- "Important Teams messages?" / "Anything important from the team this morning?" / "Was Wichtiges in den Arbeits-Chats?" → `/m365/important?top=5&limit=30`. Filter `message.createdAt` to the implied window (this morning → last 8h, today → last 24h). `?label=alerts` to scope to one tag. Each entry has `label`, `notes`, `message`.
- **`/m365/important` soft-fails per source** — one revoked chat doesn't sink the feed. Trust the partial result.
- "What's in chat / channel X?" → chats: `/m365/chats` → pick id → `/m365/chats/{chatId}/messages?top=20`. Channels: `/m365/teams` → `/m365/teams/{teamId}/channels` → `/m365/teams/{teamId}/channels/{channelId}/messages`.
- **`from.email` on Teams messages is currently null** (Graph API gap). Resolve sender by matching `from.name` against `/m365/team` `members[].displayName`. From `displayName` you can hop to `atlassian.accountId` / `gitlab.username`.

## Curl templates

```bash
# Calendar
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/calendar/upcoming?days=14"

# Teams — curated alerts feed (top N per labeled source, merged + capped)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/important?top=5&limit=100"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/important?label=alerts"

# Teams — chats → messages
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/chats?top=50"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/chats/{chatId}/messages?top=20"
```
