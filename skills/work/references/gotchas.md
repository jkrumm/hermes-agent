# Defaults and gotchas

> **Calendar `start`/`end` (`/m365/calendar/upcoming`) are UTC — convert to Europe/Berlin before narrating a time.**
> CEST is UTC+2 in summer, CET UTC+1 in winter, so `UTC 08:45` is the `10:45`
> standup. Reading the raw value aloud shifts every work meeting an hour or two
> earlier, and it looks plausible — which is why it survives review. The personal
> Google calendar (`/api/calendar`) does not have this problem; only this endpoint.
> All-day events are `YYYY-MM-DD` (no time).

- **System messages filtered by default.** `/m365/chats/{id}/messages`, channel messages, and `/gitlab/.../discussions` drop join/leave/label-change/merge events unless `?includeSystem=true`. Only flip it for explicit membership/process questions.
- **Page sizes.** GitLab/Confluence cap at 100, Jira `/my-issues` at 100, M365 chat/channel messages at 50, `/m365/important` at 200. Default to the smallest cap that answers the question — summaries beat dumps.
- **Confluence `bodyFormat=view`** = rendered HTML (easiest). Use `storage` for XHTML source, `atlas_doc_format` for ADF JSON.
- **Response wrappers — counts must dereference the array key.** Most list endpoints return an object that wraps the array, not a bare array:
  - GitLab MR endpoints: `{mergeRequests: [...]}` → count with `jq '.mergeRequests | length'`
  - Jira list endpoints: `{issues: [...]}` → count with `jq '.issues | length'`
  - M365 chats/teams/channels/messages: `{chats: [...]}`, `{teams: [...]}`, `{channels: [...]}`, `{messages: [...]}`
  - M365 `/important`: `{messages: [...]}`
  - Confluence list endpoints: `/spaces` → `{spaces: [...]}`, `/pages/:id/children` and `/recently-updated` → `{pages: [...]}`, `/search` → `{results: [...]}`
  - Calendar (`/m365/calendar/upcoming`): **bare array** — `jq 'length'` works directly on this one only.
  - Single-resource endpoints (`/atlassian/jira/issue/:key`, `/gitlab/projects/.../merge-requests/:iid`, `/atlassian/confluence/pages/:id`) return the resource object directly.
  - Never `jq 'length'` on a wrapper object — it counts top-level keys (almost always 1), not items.

## Failure modes

- **`503 M365 not authenticated …`** → tell Johannes to run `bun m365:auth:prod` from `~/SourceRoot/argo`. Don't retry silently.
- **`503` on `/gitlab/*`** → GitLab PAT revoked or scope missing (needs `read_user` for `/events/recent`). Don't retry.
- **`503` on `/atlassian/*`** → Jira/Confluence token expired.
- **In briefings,** surface as a single line ("IU work calendar unavailable — token expired") and continue with the rest of the report.
- **`404` on a specific MR/ticket/page** → not found OR no permission. Don't fabricate.
- **Other non-2xx:** name the status code, do not retry, do not pretend data was returned.
- Jira write failures (400/422/404/409/503): `jira-write.md`.
