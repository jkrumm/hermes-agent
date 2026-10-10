---
name: work
description: IU work surface — Outlook calendar, Teams chats/channels + curated alerts, Jira tickets/sprint/backlog (read + create/update/comment on Johannes's behalf, always Team=Prometheus), Confluence docs, GitLab MRs + approvals + discussions. Cross-system identity via /m365/team roster. Personal assistant only, never team-facing.
version: 1.4.0
metadata:
  hermes:
    tags: [work, iu, calendar, teams, outlook, jira, jira-create, jira-update, sprint, confluence, gitlab, mr, review, ticket]
    related_skills: [capture, argo-api]
---

# Work (IU)

Johannes's **personal** work assistant over his IU systems via the Argo API. Source of truth: `/api/openapi/json` across four tags — **M365**, **Atlassian** (Jira + Confluence), **GitLab**. Re-hit the spec when a question doesn't fit the curated commands — new routes land under the same tags without a SKILL.md edit.

**Base URL:** `https://argo.jkrumm.com/api`
**Auth:** `Authorization: Bearer $HOMELAB_API_KEY`

## Scope (read first)

- **Read** across M365, Atlassian (Jira + Confluence), GitLab.
- **Write to Jira only** — create/update/comment/transition Johannes's own tickets via `/atlassian/jira/issues*` (Argo stamps Team=Prometheus; no attribution). Details: `references/jira-write.md`.
- **Off-limits:** Teams messages, Outlook mail, Confluence pages, GitLab MRs. Decline cleanly, then offer to draft the text for him to paste.
- **Personal only.** Never push or ping teammates, write standup notes or stakeholder summaries, or speak as Johannes to anyone but Johannes. Team-facing requests ("ping the team", "remind everyone", "let X know"): decline, ask whether a personal note would do, or offer draft text he can paste himself — Hermes never speaks for teammates.
- **Reporting:** report per SOUL.md.

## When to route here

- **Calendar:** "next IU meeting", "Teams link for X", "do I have time on Friday for work", "wann hab ich Zeit"
- **Sprint / tickets (read):** "what's in my sprint", "EP-XXXX status", "what's on my plate at work", "current sprint", "backlog", "my open tickets"
- **Sprint / tickets (write):** "create a Jira ticket for …", "open a Spike for …", "add EP-17849 to current sprint", "move EP-17849 to Code Review", "comment on EP-17849: …", "assign EP-XXXX to fabi"
- **MRs / code review:** "open MRs", "what needs my review", "is MR !nnn blocked", "did Y merge", "approvals on X"
- **Teams chats/channels:** "what's in the alerts chat", "messages in #team-foo", "what did X say in Teams"
- **Confluence:** "find the doc about X", "Confluence page on Y", "team wiki for Z"
- **Cross-system:** "what should I focus on today", "my work overview", "what's blocked on me"

**Personal calendar** (Google) → `schedule`. **Personal mail** (Gmail) → `schedule`. **Outlook mail** → intentionally not exposed; decline.

## Identity model — start every "person" or "repo" question with `/m365/team`

`GET /m365/team` is the integration hub (fetch once per session, mental-cache it). Full shape: `references/response-shapes.md`.

- **members[]** — `alias` (stable short id: `johannes`, `dmytro`, `fabi`; canonical in your reasoning), `displayName` (Teams "Last, First"; can be null), `role` (`PO` | `EM` | `TechLead` | `UX` | `AgileCoach` | `Dev`), `self` (`true` for Johannes), `ms.userId` (Azure AD GUID), `atlassian.accountId` (plug into JQL: `assignee = "<accountId>"`, `reporter = "<accountId>"`), `gitlab.username` (plug into `/gitlab/merge-requests?authorUsername=…`; null for non-devs: PO/EM/UX/AgileCoach).
- **repos[]** — `alias` (`studentEnrolment`, `bookingFe`, …), `kind` (`backend` | `frontend` | `internal`), `domains[]` (`booking`, `profile`, `internal`), `gitlab.projectId` (pass **directly** into `/gitlab/projects/{projectId}/*`), `gitlab.path`, `defaultBranch`, `webUrl`.

Use `alias` for cross-system reasoning; platform IDs for API calls. Names don't always match (GitLab username `dmytrorozhko1` ≠ display name "Rozhko, Dmytro") — **always** resolve through `/m365/team`.

## Recurring-question playbook

| Question | Call chain |
|-|-|
| "What's on my plate?" | `/atlassian/jira/my-issues` (cross-project) + `/atlassian/jira/current-sprint?onlyMine=true` (board-scoped) + `/gitlab/merge-requests?scope=created_by_me&state=opened` |
| "What should I focus on?" / "My work overview" | In parallel: `/atlassian/jira/current-sprint?onlyMine=true`, `/gitlab/merge-requests?scope=reviews_for_me&state=opened`, `/gitlab/merge-requests?scope=created_by_me&state=opened`, `/m365/calendar/upcoming?days=2`, `/m365/important?top=3&limit=30`. Rank: (a) **blocked / awaiting Johannes** — his MRs with `approvalsLeft=0 && mergeStatus=can_be_merged` (he just needs to merge); (b) sprint commitments due in the next 2 days; (c) MRs needing his review; (d) calendar today; (e) labeled alerts with new messages since last check |
| "What needs my review?" | `/gitlab/merge-requests?scope=reviews_for_me&state=opened` |
| "What's the team shipping today?" | `/atlassian/jira/current-sprint` (no `onlyMine`) + `/gitlab/merge-requests?scope=all&state=opened&authorUsername=<each dev's gitlab.username>`. **Cost note:** this fans out to N calls per dev — cap at the 5 most-active devs from the roster unless Johannes explicitly asks for everyone. There is no team-wide cross-author MR endpoint. |
| "What's the status of EP-XXXX?" | `GET /atlassian/jira/issue/EP-XXXX` + `/atlassian/jira/search?jql=text ~ "EP-XXXX"` OR scan recent MRs and grep `jiraKeys`. Report ticket status + assignee + linked MR(s) state + last update |
| "Is MR !nnn blocked / ready to merge?" | `references/gitlab-mr.md` (three parallel calls + the blocker check + MR↔Jira link) |
| "What did Y push this week?" | `/gitlab/events/recent?days=7` is **YOU-only** (authenticated user). For a teammate: `/gitlab/merge-requests?scope=all&authorUsername=<gitlab.username>&state=all` filtered by `updatedAt` |
| "Releases since last week?" | `/gitlab/projects/{projectId}/releases` per repo (no cross-project releases endpoint; iterate `/m365/team` `repos[]`) |
| "Important Teams messages?" / "What's in chat / channel X?" | `references/m365-teams.md` |
| "Upcoming work meetings?" | `/m365/calendar/upcoming?days=N` (default 14, max 60) — UTC, see `references/gotchas.md` |
| "Wann hab ich Zeit diese Woche?" | `/m365/calendar/upcoming?days=7` (work) + personal `GET /calendar` via `argo-api` (`references/schedule.md`); merge timelines, find gaps ≥30 min |
| "Find the Confluence page about X" / "Confluence context for X?" | `/atlassian/confluence/search?cql=text ~ "X"` (or `title ~ "X"` for a stricter match; combine with `space=EP` if scoped) → pick the top result by `lastModified` recency → `/atlassian/confluence/pages/{id}?bodyFormat=view` → summarize sections |
| Create / update / move / comment / assign / link a Jira ticket | `references/jira-write.md` |
| "Send a Teams message to X" / "Reply to that meeting invite" / "Open MR" / Confluence page write | Decline politely — these write paths are not exposed. Offer to draft the text for Johannes to paste |

## Read commands

```bash
# Identity hub — fetch once per session, mental-cache the result
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/m365/team"

# Jira — my open issues across all projects
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/atlassian/jira/my-issues?limit=50"

# Jira — current sprint (mine only)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/atlassian/jira/current-sprint?onlyMine=true"

# Jira — one ticket
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/atlassian/jira/issue/EP-17849"

# Jira — JQL search (escape hatch)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  --get --data-urlencode 'jql=assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC' \
  "https://argo.jkrumm.com/api/atlassian/jira/search"

# Confluence — CQL search → page body (view = rendered HTML, easiest)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  --get --data-urlencode 'cql=text ~ "migration"' \
  "https://argo.jkrumm.com/api/atlassian/confluence/search"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/atlassian/confluence/pages/{id}?bodyFormat=view"

# Discover new endpoints
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/openapi/json"
```

GitLab curls: `references/gitlab-mr.md`. Calendar + Teams curls: `references/m365-teams.md`. Jira write curls: `references/jira-write.md`.

## References (load on demand, paths relative to this skill)

- `references/jira-write.md` — create/update/comment/transition/link tickets, markdown subset, call chains, write failure modes, write curls
- `references/response-shapes.md` — field contract per endpoint (team, sprint, Issue, MR, approvals, discussions, calendar, important, Confluence search); the morning briefing prompt cites it
- `references/gitlab-mr.md` — MR↔Jira link, "is MR blocked" check, GitLab curls
- `references/m365-teams.md` — calendar, curated `/m365/important`, chats/channels, M365 curls
- `references/gotchas.md` — UTC calendar warning, response-wrapper / `jq length` trap, paging caps, failure modes (503 etc.)
