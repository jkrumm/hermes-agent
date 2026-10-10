# GitLab / merge requests

GitLab is read-only: never open, approve or merge an MR (decline, offer to draft the MR description).

## The MR ↔ Jira link

Every MR returned by `/gitlab/*` carries `jiraKeys: string[]` — auto-extracted from title, source branch, and description. Two affordances follow:

- **When summarizing an MR, always inline the linked Jira summary (+ status) if `jiraKeys` is non-empty.** One extra `GET /atlassian/jira/issue/{key}` call, saves Johannes the click.
- **When a ticket is mentioned**, find related MRs via `/gitlab/merge-requests?scope=all&authorUsername=<dev>&state=all` and grep client-side for the key in `jiraKeys`. Or run JQL via `/atlassian/jira/search` with `text ~ "!nnn"`.

## "Is MR !nnn blocked / ready to merge?"

1. Resolve `projectId` from `/m365/team` `repos[]` (by alias or URL).
2. Fetch in parallel: `/gitlab/projects/{projectId}/merge-requests/{iid}` + `/approvals` + `/discussions`.
3. An MR is **mergeable** when ALL true:
   - `mergeStatus === "can_be_merged"`
   - `hasConflicts === false`
   - `draft === false`
   - `approvalsLeft === 0` (from `/approvals`)
   - No unresolved discussion notes (from `/discussions`: `notes[].resolvable && !notes[].resolved`)
4. Spell out which single condition is the blocker — don't just say "blocked". If multiple, list them in priority order.
5. If `jiraKeys` is non-empty, inline the Jira ticket summary + status.

**Two levels.** Asked about one MR: the full 5-condition check above. The morning briefing's "ready to merge" tally uses only the 3 list-level fields (`mergeStatus`, `hasConflicts`, `draft`) — it does not call `/approvals` or `/discussions` per MR, for cost.

## Curl templates

```bash
# GitLab — MRs needing my review
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/gitlab/merge-requests?scope=reviews_for_me&state=opened"

# GitLab — my open MRs
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/gitlab/merge-requests?scope=created_by_me&state=opened"

# GitLab — one MR + approvals + discussions (call in parallel)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/gitlab/projects/{projectId}/merge-requests/{iid}"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/gitlab/projects/{projectId}/merge-requests/{iid}/approvals"
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" "https://argo.jkrumm.com/api/gitlab/projects/{projectId}/merge-requests/{iid}/discussions"
```
