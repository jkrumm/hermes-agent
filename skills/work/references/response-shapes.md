# Response shapes (key fields by endpoint)

Authoritative field reference for the endpoints the briefing prompts and the recurring-question playbook depend on. Use as a contract — if Argo's response is missing one of these, surface the gap explicitly rather than hallucinating a default.

## `/m365/team` — identity hub

```ts
{
  team: string,
  members: Array<{
    alias: string,                // canonical short id (lowercase first name)
    displayName: string | null,   // "Last, First" Teams format
    role: "PO" | "EM" | "TechLead" | "UX" | "AgileCoach" | "Dev",
    self?: boolean,
    ms:        { userId: string | null },          // Azure AD GUID
    atlassian: { accountId: string | null },       // JQL: assignee = "<accountId>"
    gitlab:    { username: string | null }         // null for non-devs
  }>,
  repos: Array<{
    alias: string,                                  // "studentEnrolment", "bookingFe"
    purpose: string,
    kind: "backend" | "frontend" | "internal",
    domains: string[],
    gitlab: { projectId: number, path: string, defaultBranch: string, webUrl: string }
  }>
}
```

## `/atlassian/jira/current-sprint` (also `/sprints/:id`)

```ts
{
  board:  { id: number, name: string, type: string, projectKey, projectName },
  sprint: null | {
    id: number,
    name: string,                          // e.g. "Prometheus 107"
    state: "active" | "closed" | "future",
    startDate: string | null,              // ISO 8601
    endDate:   string | null,              // ISO 8601 — use for "N days remaining"
    completeDate: string | null,
    goal: string | null,
    boardId: number
  },
  issues: Issue[]                          // see Issue shape below
}
```

`sprint: null` → no active sprint; surface "no active sprint" and return without listing issues.

## `/atlassian/jira/my-issues`, `/issue/:key`, `/search`, `/backlog`

`my-issues` returns `{ issues: Issue[], isLast: bool }`. `issue/:key` returns a single `Issue`. `search` returns `{ issues: Issue[], isLast: bool, nextPageToken: string | null }` (cursor-paginated). `backlog` returns `{ issues: Issue[], total: int, startAt: int, isLast: bool }` (offset-paginated).

**Issue shape:**

```ts
{
  key: string,                             // "EP-17849"
  url: string,
  summary: string,
  status: string,                          // raw workflow status (German on EP board)
  statusCategory: "todo" | "in-progress" | "done" | "unknown",
  issueType: string,
  isSubtask: boolean,
  priority: string | null,                 // "Highest", "High", "Medium", "Low"
  project:  { key: string, name: string },
  assignee: { name: string, email: string | null } | null,
  reporter: { name: string, email: string | null } | null,
  dueDate: string | null,                  // "YYYY-MM-DD"
  created: string,                         // ISO 8601
  updated: string,                         // ISO 8601
  labels: string[],
  parent: { key: string, summary: string } | null,
  links: Array<{
    type: string,                          // "Blocks", "Relates", "Duplicate", ...
    direction: "inward" | "outward",       // which end THIS ticket is on
    phrase: string,                        // "blocks" or "is blocked by" — the side for THIS ticket
    key: string,                           // the OTHER ticket
    url: string,
    summary: string,
    status: string,
    statusCategory: "todo" | "in-progress" | "done" | "unknown"
  }>
}
```

Group/filter by `statusCategory` (normalized), not `status` (workflow-specific).

## `/gitlab/merge-requests` (list — all `scope=…` flavors)

```ts
{ mergeRequests: MR[] }
```

**MR shape** (also returned bare by `/projects/:projectId/merge-requests/:iid`):

```ts
{
  id: number,                              // global
  iid: number,                             // per-project (the !1234)
  projectId: number,                       // matches /m365/team repos[].gitlab.projectId
  projectPath: string | null,              // "iu-group/epos/prometheus/..."
  title: string,
  state: "opened" | "closed" | "merged" | "locked",
  draft: boolean,
  webUrl: string,
  sourceBranch: string,                    // may encode jira key
  targetBranch: string,
  author:    { username: string, name: string } | null,
  assignees: Array<{ username, name }>,
  reviewers: Array<{ username, name }>,
  labels: string[],
  upvotes: number,
  downvotes: number,
  userNotesCount: number,
  mergeStatus: string | null,              // "can_be_merged" = no conflicts
  hasConflicts: boolean,
  createdAt: string,                       // ISO 8601
  updatedAt: string,
  jiraKeys: string[]                       // auto-extracted: title + branch + description
}
```

## `/gitlab/projects/:projectId/merge-requests/:iid/approvals`

```ts
{ approved: boolean, approvalsRequired: number, approvalsLeft: number, approvedBy: Array<{username,name}> }
```

## `/gitlab/projects/:projectId/merge-requests/:iid/discussions`

```ts
{ discussions: Array<{
    id: string,
    individualNote: boolean,               // false = threaded conversation
    notes: Array<{
      id: number,
      body: string,                        // markdown
      author: { username, name } | null,
      system: boolean,                     // auto-event (filtered by default)
      resolvable: boolean,
      resolved: boolean,
      createdAt: string,
      updatedAt: string
    }>
}> }
```

See `gitlab-mr.md` for the blocker check.

## `/m365/calendar/upcoming` — **bare array, no wrapper**

`start`/`end` are UTC — see `gotchas.md` before narrating a time.

```ts
Array<{
  id: string,
  title: string,
  start: string,                           // ISO 8601 UTC, or "YYYY-MM-DD" for isAllDay
  end:   string,
  isAllDay: boolean,
  isOnlineMeeting: boolean,
  location?: string,
  organizer?: { name: string, email: string },
  attendees: Array<{ name, email, status }>,
  bodyPreview?: string,
  videoLink?: string,                      // Teams joinUrl
  webLink?: string                         // Outlook web URL
}>
```

## `/m365/important` (curated alerts feed)

```ts
{ messages: Array<{
    source: "chat" | "channel",
    sourceId: string,                      // composite: "chat:<id>" or "channel:<team>:<channel>"
    label: string,                         // user tag
    displayName: string | null,
    notes: string | null,
    message: ChatMessage                   // see /m365/chats/:id/messages for shape
}> }
```

## `/atlassian/confluence/search`

```ts
{
  results: Array<{
    id: string,
    title: string,
    type: "page" | "blogpost" | "comment" | "attachment",
    url: string,
    spaceKey: string | null,
    spaceName: string | null,
    excerpt: string,
    lastModified: string | null            // ISO 8601
  }>,
  start: number, limit: number, totalSize: number, isLast: boolean
}
```

Offset-paginated (`start` is 0-based) — **not** cursor-paginated like Jira `/search`.
