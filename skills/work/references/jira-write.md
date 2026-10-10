# Jira write surface — create / update / comment

Argo exposes three write endpoints for the Prometheus board (EP project, board 272). **Every call auto-stamps Team=Prometheus** — you do NOT supply the team. Tickets are filed as the authenticated Jira user; no attribution footer is added, so write the description/body as if Johannes himself were typing. Jira writes are a delegated personal action (his tickets, his team's board), not posting on behalf of the team.

## Workflow before creating any ticket

1. **Read create-meta** (once per session): `GET /atlassian/jira/create-meta` — returns the valid `issueType`, `priority`, `sprint`, and `transition` enums plus the team's title-bracket convention. Cache it.
2. **Inspect sibling tickets** for title convention: `GET /atlassian/jira/current-sprint` — read the summaries of 5-10 sibling tickets to see the bracketed-topic pattern in use (e.g. `[FE][Booking] Phase 4 - Migrate OverviewInformation`, `[MS][TMC][Cancellation] Block finance fields`, `[BI] Fix 2 failed prod imports`, `[Admission] …`). Match the existing taxonomy — don't invent new prefixes.
3. **Resolve people** via `/m365/team` → `members[].atlassian.accountId`. Pass `accountId` to `assigneeAccountId` (NOT email or display name). For Johannes use `/atlassian/jira/me` or the self-flagged member in the roster.
4. **Default to backlog** for non-urgent tickets (omit `sprint`). Only set `sprint: "current"` when Johannes explicitly says "into this sprint" or the work is time-critical.
5. **Omit storyPoints** by default — points are set during team refinement. Only fill when Johannes asks for a specific number ("a 1-point chore").
6. **Compose the body locally** in the Markdown subset below. Do NOT compose ADF JSON — Argo converts the string itself.
7. `POST /atlassian/jira/issues` with `issueType`, `summary`, `description`, optional `sprint`, `assigneeAccountId`, `priority`, `parentKey` (for Sub-task), `epicKey`, `links`.
8. Read back the returned `key` + `url` and quote them to Johannes ("Created EP-17920 — <url>"). One line, no fluff.

## Description = Markdown subset

The `description` (and comment `body`) field accepts:

- `#`, `##`, `###` for h1/h2/h3 headings — use `## Acceptance Criteria` style.
- `**bold**`, `*italic*` / `_italic_`, `` `code` ``.
- Fenced ``` ```lang ... ``` ``` code blocks.
- `- ` / `* ` bullet lists (consecutive lines = one list).
- `1. ` ordered lists.
- `[text](url)` links.
- **Bare issue keys (`EP-17587`) and `/browse/<KEY>` URLs are auto-linked to Jira smart-link inlineCards** — never paste a raw `https://<your-jira-host>/browse/EP-X` URL when you can write `EP-X` and let Argo render it as a smart-link.
- Blank line splits paragraphs; single newline inside a paragraph = hard break.

**NOT supported** (will render as literal characters in Jira): tables, blockquotes, nested lists, task lists, images, HTML, link references. If Johannes wants any of those, surface the gap.

## Issue type, links, sub-tasks

**Issue-type swap:** `PATCH /atlassian/jira/issues/{key}` accepts `issueType` — Story↔Task↔Spike↔Bug swap without losing the key. Jira may reject combinations that change schema-required fields; if you get a 400 the body explains which field is missing.

**Structured issue links:** both `POST` and `PATCH` accept a `links: [{type, key}]` array. `type` accepts the direction-flavored phrase ("blocks", "is blocked by", "duplicates", "is duplicated by", "causes", "is caused by", "relates to", "tests", "clones") OR the canonical type name ("Blocks", "Relates"). The phrase form is preferred — it carries the direction unambiguously. PATCH `links` is ADDITIVE (no remove-link endpoint; drop stale links in the Jira UI).

**Before adding links via PATCH, READ the existing ones.** `GET /atlassian/jira/issue/{key}` returns a `links: [{type, direction, phrase, key, url, summary, status}]` field — check it first so you don't pile up duplicates with the additive PATCH. Fetch the tenant-valid type set from `GET /atlassian/jira/create-meta` `linkTypes[]`.

**No native "Follows" link type in this tenant.** Closest semantic is `Blocks` reversed: "EP-NEW follows EP-17587" ≡ "EP-NEW is blocked by EP-17587". Use `{type: "is blocked by", key: "EP-17587"}`.

## Request → call chain

| Question | Call chain |
|-|-|
| "Create a Spike for migrating X" | (cache `/create-meta` + `/current-sprint` for title norm) → `POST /atlassian/jira/issues` `{issueType:"Spike", summary:"[Topic] …", description:"…", sprint:"backlog"}` — read back `key` + `url` and quote them to Johannes |
| "Open a ticket for me about X, put it in this sprint" | resolve self via `/me` → `POST /atlassian/jira/issues` `{issueType:"Task", summary, description, sprint:"current", assigneeAccountId:<self>}` |
| "Move EP-XXXX to Code Review" / "Mark EP-XXXX as Done" | (optional, if unsure which transitions are reachable) `GET /atlassian/jira/issues/EP-XXXX/transitions` → `PATCH /atlassian/jira/issues/EP-XXXX` `{status:"Code Review"}` — returns `transitioned:true`. The name matches case-insensitively and falls back to target-status matching. On 409 the response lists valid transitions from the current state — quote them to Johannes and ask which to use. |
| "Comment on EP-XXXX: tested locally, looks good" | `POST /atlassian/jira/issues/EP-XXXX/comments` `{body:"Tested locally, looks good — ready for review"}`. Confirm "Commented on EP-XXXX." — no need to echo the body. |
| "Re-assign EP-XXXX to fabi" | resolve via `/m365/team` `alias="fabi"` → `members[].atlassian.accountId` → `PATCH /atlassian/jira/issues/EP-XXXX` `{assigneeAccountId:"<accountId>"}` |
| "Add EP-XXXX to next sprint" | `PATCH /atlassian/jira/issues/EP-XXXX` `{sprint:"next"}` |
| "Link EP-XXXX as a sub-task of EP-YYYY" | Sub-task hierarchy is set at creation only via `parentKey`. For structural "Blocks / Relates / Duplicates" links between existing tickets use the next row. |
| "EP-NEW blocks EP-17587" / "EP-NEW relates to EP-Y" / "Mark EP-NEW as duplicate of EP-Z" / "EP-NEW follows EP-17587" | `PATCH /atlassian/jira/issues/EP-NEW` `{links:[{type:"blocks",key:"EP-17587"}]}` (or `"relates to"`, `"is duplicated by"`, `"is blocked by"` for follows-semantics). Additive — never replaces existing links. |
| "Change EP-XXXX from Story to Task" / "Wrong type, should be a Spike" | `PATCH /atlassian/jira/issues/EP-XXXX` `{issueType:"Task"}` — preserves key + history. 400 if Jira's workflow can't accept the new type (rare on EP — workflow is shared). |
| "Change story points on EP-XXXX to 3" | `PATCH /atlassian/jira/issues/EP-XXXX` `{storyPoints:3}` (Johannes is asking explicitly — refinement override) |

## Write failure modes

- `400/422` on create → field validation failed. Read the message; common cause is missing `parentKey` on `Sub-task` or unknown `epicKey`.
- `404` on update/comment → bad issue key OR no permission (likely a different project Johannes can't write to).
- `409` on `status` transition → the requested transition isn't available from the current state. Body lists what's valid. Don't guess — quote the valid options back to Johannes.
- `503` → upstream Jira hiccup. Don't retry silently; surface the error.

## Curl templates

```bash
# Jira WRITE — fetch create-meta first (cache for the session)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/atlassian/jira/create-meta"

# Jira WRITE — create with markdown body (headings + bullet list + auto-linked issue key)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X POST "https://argo.jkrumm.com/api/atlassian/jira/issues" \
  -d '{
    "issueType": "Spike",
    "summary": "[Topic] Concise imperative title",
    "description": "## Context\n\nWe need X because Y. Related to EP-17587.\n\n## Acceptance Criteria\n\n- **Foo** must happen\n- `bar` config flipped\n- Smoke test green",
    "sprint": "backlog"
  }'

# Jira WRITE — create a ticket assigned to Johannes in the current sprint
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X POST "https://argo.jkrumm.com/api/atlassian/jira/issues" \
  -d '{
    "issueType": "Task",
    "summary": "[Admission] Fix something specific",
    "description": "...",
    "assigneeAccountId": "<resolved-from-/atlassian/jira/me>",
    "sprint": "current",
    "priority": "High"
  }'

# Jira WRITE — update ticket + transition status in one call
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X PATCH "https://argo.jkrumm.com/api/atlassian/jira/issues/EP-17849" \
  -d '{ "status": "Code Review" }'

# Jira WRITE — change issue type (preserves key + history)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X PATCH "https://argo.jkrumm.com/api/atlassian/jira/issues/EP-17863" \
  -d '{ "issueType": "Task" }'

# Jira WRITE — add structured issue links (additive)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X PATCH "https://argo.jkrumm.com/api/atlassian/jira/issues/EP-17863" \
  -d '{ "links": [
    { "type": "is blocked by", "key": "EP-17587" },
    { "type": "relates to",    "key": "EP-17666" }
  ] }'

# Jira WRITE — create + link in one shot
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X POST "https://argo.jkrumm.com/api/atlassian/jira/issues" \
  -d '{
    "issueType": "Task",
    "summary": "[Hermes] verify write surface",
    "description": "Smoke test for the new write endpoints.",
    "sprint": "backlog",
    "links": [{ "type": "relates to", "key": "EP-17863" }]
  }'

# Jira WRITE — add a comment
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -X POST "https://argo.jkrumm.com/api/atlassian/jira/issues/EP-17849/comments" \
  -d '{ "body": "Tested locally, ready for review." }'

# Jira WRITE — see what transitions are available before patching status
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/atlassian/jira/issues/EP-17849/transitions"
```
