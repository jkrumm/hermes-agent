---
name: capture
description: Capture a todo, reminder, or issue from natural language and route it — TickTick (Personal/Work/Shopping) or GitHub Issue on the right repo. Single entry point for "remind me to…", "I should…", "todo:", "issue:" intents
version: 1.0.0
metadata:
  hermes:
    tags: [capture, todo, reminder, issue, ticktick, github, routing]
    related_skills: [tasks, argo-api]
---

# Capture (TickTick + GitHub Issues)

Single entry point for capturing things Johannes wants to track.
You decide where it lands. No double-tracking — one item, one home.

---

## Mental Model (the routing rule)

> **GitHub** = a *concrete code change* a Claude coding agent can execute end-to-end — implement, fix, refactor, write tests, bump deps, wire config.
> **TickTick** = anything a *human* does — including research, evaluation, exploration, decisions, manual ops, errands, appointments.

**Key distinction (this is where most mistakes happen):** "dev-flavoured" wording does NOT mean GitHub. *Researching* a tool, *checking out* a library, *evaluating* options, *deciding* between two approaches — these are human cognitive tasks. They go to TickTick even when the topic is engineering. Only translate to a GitHub issue when the work is "go change the code in X way."

| Phrase | Where | Why |
|-|-|-|
| "Implement X" / "Fix Y" / "Refactor Z" | GitHub | Concrete change |
| "Add tests for X" / "Bump dep Y" | GitHub | Concrete change |
| "Look into X" / "Checkout Y" / "Research Z" | TickTick | Human exploration |
| "Compare A vs B" / "Decide on X" | TickTick | Human decision |
| "Evaluate Z for our use case" | TickTick | Human judgment |

**Hard override:** anything IU / International University / work / colleague names → TickTick `💼Work`. **Never** GitHub, even if it's an engineering task.

---

## Decision Tree

Walk top to bottom. First match wins.

1. **IU / Work signal?** ("IU", "International University", "work", colleague name, EP-XX ticket, IU project) → TickTick `💼Work`.
2. **Names a known repo or matches a repo's domain?** → GitHub Issue in that repo.
3. **Shopping signal?** ("buy X", "pick up Y", grocery items, items to acquire) → TickTick `📦Shopping`.
4. **Personal life?** (appointment, errand, "water plants", "cancel subscription", "release the X video", health, finance, household) → TickTick `🏠Personal`.
5. **Unclear** → ask one short question ("→ GitHub `homelab` or TickTick `🏠Personal`?"). If still unclear after one round, fall back to TickTick Inbox.

**Confidence:** if ≥90% sure, write silently and confirm with link. If less, ask first.

---

## Repo Detection (GitHub path)

A capture maps to a repo when it:
- **Names the repo explicitly** ("homelab", "dotfiles", "basalt-ui").
- **Names a service/domain owned by that repo** — e.g. "the watchdog cron" → `homelab` (or `watchdog` repo, check both); "the slack patch" → `dotfiles`; "the morning briefing prompt" → `dotfiles`; "rollhook deploy logs" → `rollhook`.
- **Names a file/path** that lives in a known repo.

If the repo identity is genuinely ambiguous between two candidates, ask.

### Common repo → domain hints

| Repo | Owns |
|-|-|
| `homelab` | Docker stack, 25+ containers, infra services on home network |
| `homelab-private` | Private homelab services (homelab API, secrets) |
| `vps` | VPS Docker stack, Traefik, RollHook, Postgres, Valkey |
| `dotfiles` | Claude Code config, Hermes skills/cron/SOUL/scripts, statusline, hooks, dotfiles |
| `basalt-ui` | NPM-published Tailwind v4 design system |
| `basalt-ui-playground` | TanStack Start boilerplate using basalt-ui |
| `watchdog` | Self-healing infrastructure agent + React SPA |
| `rollhook` / `rollhook-action` | Zero-downtime Docker rolling deploys + GitHub Action |
| `sideclaw` | MCP tooling used by skills |
| `jkrumm.dev` | Personal site |
| `home` | Home dashboard |
| `Auto-Claude` | Autonomous multi-session AI coding |
| `homebrew-tap` | Homebrew formulas for jkrumm tools |

This list is a hint, not exhaustive. The live cache (see below) is the source of truth.

---

## State Cache

**File:** `~/.hermes/skills/capture/state.json` (gitignored, seeded from `state.example.json` on first `make setup`)

```json
{
  "repos": [
    {"name": "homelab", "description": "...", "visibility": "PUBLIC"},
    ...
  ],
  "repos_last_refresh": "2026-04-30T12:00:00Z",
  "ticktick_projects": [
    {"id": "69a32ea26de7515d72e6c664", "name": "🏠Personal"},
    {"id": "69a32ea26df1515d72e6c668", "name": "💼Work"},
    {"id": "69a32ea26dc8115d72e6c66c", "name": "📦Shopping"}
  ],
  "ticktick_last_refresh": "2026-04-30T12:00:00Z"
}
```

**Refresh policy:** never expire. Refresh **on miss only** — if the user mentions a repo or TickTick project not in the cache, refresh that cache once and try again.

### Read cache

```bash
cat ~/.hermes/skills/capture/state.json | jq '.repos[].name'
cat ~/.hermes/skills/capture/state.json | jq '.ticktick_projects'
```

### Refresh repos cache (run on miss)

```bash
TMP=$(mktemp)
gh repo list jkrumm --limit 200 --json name,description,visibility,isArchived \
  | jq '[.[] | select(.isArchived==false) | {name, description, visibility}]' > "$TMP"
jq --slurpfile repos "$TMP" \
  '.repos = $repos[0] | .repos_last_refresh = (now | strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  ~/.hermes/skills/capture/state.json > "$TMP.merged"
mv "$TMP.merged" ~/.hermes/skills/capture/state.json
rm -f "$TMP"
```

### Refresh TickTick projects cache (run on miss)

```bash
TMP=$(mktemp)
curl -s -H "Authorization: Bearer $HOMELAB_API_KEY" \
  "https://argo.jkrumm.com/api/ticktick/projects" \
  | jq '[.data[] | select(.closed != true) | {id, name}]' > "$TMP"
jq --slurpfile projects "$TMP" \
  '.ticktick_projects = $projects[0] | .ticktick_last_refresh = (now | strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  ~/.hermes/skills/capture/state.json > "$TMP.merged"
mv "$TMP.merged" ~/.hermes/skills/capture/state.json
rm -f "$TMP"
```

---

## Writing the Item

### TickTick (Personal / Work / Shopping / Inbox)

Use the `tasks` skill's POST. Resolve project name → ID via the cache.

```bash
# Resolve project ID (cache hit expected)
PROJECT_ID=$(jq -r '.ticktick_projects[] | select(.name == "💼Work") | .id' ~/.hermes/skills/capture/state.json)

# Create task — title is short imperative, dueDate optional
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d "{\"title\":\"Renew Tailscale cert\",\"projectId\":\"$PROJECT_ID\",\"dueDate\":\"2026-05-30\",\"priority\":3}" \
  "https://argo.jkrumm.com/api/ticktick/task"
```

**Inbox fallback:** `projectId: "inbox"` (literal string, no cache lookup needed).

**Date inference (default to giving every TickTick task a `dueDate`):**
- "tomorrow", "next Monday", "in 2 weeks" → resolve relative to today's date and pass `dueDate` as `YYYY-MM-DD`.
- "this week" / "soon" / vague urgency → today + 7 days.
- "this month" → end of current month.
- **No urgency cue at all** → default `dueDate` = today + 7 days. Tasks without dates fall out of `/summary` and become invisible in briefings, so the default lean is *give it a date*.
- **Only omit `dueDate`** when the task is genuinely time-flexible AND high-priority enough that it should surface anyway (`priority: 5` will cause briefings to flag it). When in doubt, set a date.

**Priority inference:**
- "urgent" / "ASAP" → `5` (High).
- Default → omit (None).

### GitHub Issue

```bash
gh issue create -R jkrumm/<repo> \
  --assignee jkrumm \
  --title "<short imperative title>" \
  --body "$(cat <<'EOF'
<one-line context Hermes inferred>

Original capture: <verbatim user text>
EOF
)"
```

**Rules:**
- Assignee: always `jkrumm`. No labels at v1.
- Title: short, imperative. Strip filler ("can you...", "I think we should...").
- Body: one inferred context line + `Original capture: <verbatim>`. **Never** invent reproduction steps, acceptance criteria, or facts not present in the user's message.
- The `gh` CLI returns the issue URL on stdout — capture and surface it in the confirmation.

---

## Confirmation Format (Slack)

After writing, reply with **one line** containing:
- The destination (icon + project/repo)
- The title
- A clickable link

```
:white_check_mark: TickTick 💼Work — "Renew Tailscale cert" → https://ticktick.com/...
:white_check_mark: GitHub `homelab` — "Patch slack cannot_reply_to_message edge case" → https://github.com/jkrumm/homelab/issues/123
```

If you asked first and the user confirmed, no need to repeat the title — just the link.

---

## Edge Cases & Failure Modes

- **Repo cache miss:** user mentions a repo not in cache → refresh repos once → if still missing, ask ("I don't see `<name>` in your repos — did you mean `<closest match>`?").
- **TickTick project miss:** new project added in TickTick → refresh once, retry.
- **`gh` not authenticated:** if `gh issue create` fails with auth error, surface the error verbatim and tell Johannes to run `gh auth status` on the Mac Mini.
- **Cross-cutting items:** never create both. If the item is repo work *and* something Johannes needs to remember, GitHub wins (the watchdog/briefing reads issues anyway).
- **Multiple items in one message** ("remind me to X and also open an issue for Y"): split, route each independently, return one confirmation line per item.
- **Not a capture:** if the message is a question or status check, don't capture — route normally.

---

## Examples

**"Remind me to renew the Tailscale cert next month"**
→ TickTick `🏠Personal`, dueDate = today + 30d.

**"I need to fix the slack patch breaking on long threads"**
→ GitHub `dotfiles` (concrete code change).

**"Buy oat milk"**
→ TickTick `📦Shopping`, dueDate = today + 7d (vague urgency).

**"EP-1234 — finish the enrolment form validation"**
→ TickTick `💼Work` (IU ticket → never GitHub).

**"The watchdog cron prompt could be tighter"**
→ GitHub `dotfiles` (concrete code change to `hermes/cron/watchdog.prompt.txt`).

**"Cancel the Spotify family subscription"**
→ TickTick `🏠Personal`, dueDate = today + 7d.

**"Refactor BasaltUI Button to use the new tokens"**
→ GitHub `basalt-ui` (concrete refactor a coding agent can execute).

**"Checkout imgproxy and Backblaze for image hosting"**
→ TickTick `😇Dev` (or `🏠Personal` if Dev project not used) — *research* + *evaluation* is human work, not coding-agent work, even though the topic is technical. dueDate = today + 14d (typical research lead time).

**"Look into the morning briefing prompt — it's getting long"**
→ TickTick `🏠Personal` — *look into* = exploration, not a code change. (If after reviewing the user wants to *trim* it, that follow-up becomes a GitHub `dotfiles` issue.)

**"Compare Tailscale vs Cloudflare Tunnel for the homelab"**
→ TickTick `🏛HomeLab` (or `🏠Personal`) — comparison + decision is human judgment.

**"Evaluate moving from Postgres to SQLite for the small VPS apps"**
→ TickTick `😇Dev` — evaluation/decision, dueDate = today + 14d.

**"Doctor's appointment Thursday at 3pm"**
→ TickTick `🏠Personal`, dueDate = next Thursday. (Calendar events are a separate concern — capture only stores the reminder.)

**"Release v0.4 of basalt-ui"**
→ TickTick `🏠Personal`, dueDate = today + 3d. ("Release X" = pressing publish, human action.)

**"Add OG tags to jkrumm.dev"**
→ GitHub `jkrumm.dev` (concrete code addition).

**Ambiguous:** "Look at the morning briefing"
→ Default to TickTick `🏠Personal` (exploration), dueDate = today + 7d. If the user later says "actually make the prompt shorter," that follow-up is a GitHub `dotfiles` issue.
