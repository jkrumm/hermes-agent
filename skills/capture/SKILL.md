---
name: capture
description: Capture a todo, reminder, or issue from natural language and route it — TickTick (Personal/Work/Shopping) or GitHub Issue on the right repo. Single entry point for "remind me to…", "I should…", "todo:", "issue:" intents
version: 1.0.0
metadata:
  hermes:
    tags: [capture, todo, reminder, issue, ticktick, github, routing]
    related_skills: [argo-api, karakeep, obsidian]
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

**Not a task at all? Redirect — don't force it into TickTick/GitHub:**
- A **link/article/video to read or keep later**, or a snippet to re-find → the `karakeep` skill (read-later bucket).
- A **durable idea / knowledge note** to develop → the `obsidian` skill (the vault).
- A request to **research something now and report back** (not a task to remember) → the `research-gateway` skill (cited answer from the research-gateway). Note the split: "research X" / "recherchier mal" = answer now → `research-gateway`; **"remind me to research X / look into Y later"** = a task to track → TickTick (the `Research Z` row above).

Capture owns *actionable* items (do-this) and *concrete code changes*. "Keep / read later" is reference; "note this idea" is knowledge — both have their own skills.

---

## Decision Tree

Walk top to bottom. First match wins.

1. **IU / Work signal?** ("IU", "International University", "work", colleague name, EP-XX ticket, IU project) → TickTick `💼Work`.
2. **Names a known repo or matches a repo's domain?** → GitHub Issue in that repo.
3. **Shopping signal?** ("buy X", "pick up Y", grocery items, items to acquire) → TickTick `📦Shopping`.
4. **Personal life?** (appointment, errand, "water plants", "cancel subscription", "release the X video", health, finance, household) → TickTick `🏠Personal`.
5. **Unclear** → ask one short question ("→ GitHub `homelab` or TickTick `🏠Personal`?"). If still unclear after one round, fall back to TickTick Inbox.

**Confidence:** write, then reply with the link. Ask first only when the destinations are genuinely a coin flip.

---

## Repo Detection (GitHub path)

A capture maps to a repo when it:
- **Names the repo explicitly** ("homelab", "dotfiles", "basalt-ui").
- **Names a service/domain owned by that repo** — e.g. "the watchdog cron" → `warden`; "the slack patch" or "the morning briefing prompt" → `hermes-agent`; "rollhook deploy logs" → `rollhook`.
- **Names a file/path** that lives in a known repo.

If the repo identity is genuinely ambiguous between two candidates, ask.

The repo → domain hint table is in `references/repo-hints.md`; it is a hint, not exhaustive. The live cache (`references/state-cache.md`) is the source of truth.

---

## Writing the Item

### TickTick (Personal / Work / Shopping / Inbox)

POST to the argo TickTick endpoint (`argo-api` → `references/tasks.md` has the field semantics). Resolve project name → ID via the cache.

```bash
# Resolve project ID (cache hit expected)
PROJECT_ID=$(jq -r '.ticktick_projects[] | select(.name == "💼Work") | .id' ~/.hermes/skills/capture/state.json)

# Create task — title is short imperative, dueDate optional
curl -s -X POST -H "Authorization: Bearer $HOMELAB_API_KEY" -H "Content-Type: application/json" \
  -d "{\"title\":\"Renew Tailscale cert\",\"projectId\":\"$PROJECT_ID\",\"dueDate\":\"2026-05-30\",\"priority\":3}" \
  "https://argo.jkrumm.com/api/ticktick/tasks"
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
- Assignee: always `jkrumm`. No labels by default. Warden picks up every owner issue on its
  own — never add a hand-off label.
- Title: short, imperative. Strip filler ("can you...", "I think we should...").
- Body: one inferred context line + `Original capture: <verbatim>`. **Never** invent reproduction steps, acceptance criteria, or facts not present in the user's message.
- The `gh` CLI returns the issue URL on stdout — capture and surface it in the confirmation.

---

## Confirmation

After writing, report per SOUL.md.

---

## Edge Cases & Failure Modes

- **Repo cache miss:** user mentions a repo not in cache → refresh repos once (`references/state-cache.md`) → if still missing, ask ("I don't see `<name>` in your repos — did you mean `<closest match>`?").
- **TickTick project miss:** new project added in TickTick → refresh once (`references/state-cache.md`), retry.
- **`gh` not authenticated:** if `gh issue create` fails with auth error, surface the error verbatim and tell Johannes to run `gh auth status` on the Mac Mini.
- **Cross-cutting items:** never create both. If the item is repo work *and* something Johannes needs to remember, GitHub wins (warden and the briefing read issues anyway).
- **Multiple items in one message** ("remind me to X and also open an issue for Y"): split, route each independently, return one confirmation line per item.
- **Social media link capture** (Instagram, TikTok, etc.): the user is asking for the thing *behind* the link, not the link itself. Extract full content before writing the item. For Instagram: the caption is visible even behind the login wall — extract the entity name from the snapshot, then web-search for the canonical source (e.g. `filmsimrecipes.com` for Fujifilm recipes). See `references/social-media-extraction.md` for the full escalation path.
- **Not a capture:** if the message is a question or status check, don't capture — route normally.

---

## More references

Read the matching file when the situation fits:

- `references/examples.md` — Use when a capture's routing is unclear and a worked example would help
- `references/repo-hints.md` — Use when mapping a capture to a GitHub repo
- `references/state-cache.md` — Use when reading or refreshing the repo / TickTick project cache (`state.json`)
- `references/voice-memo-briefs.md` — Use when a voice memo must become a brief or prompt
- `references/voice-memo-intake.md` — Use when an audio file or voice memo must become text
