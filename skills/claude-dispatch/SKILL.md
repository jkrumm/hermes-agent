---
name: claude-dispatch
description: Hand a question that requires READING A REPO to a Claude Code episode via the bounded `hermes-cc.sh` verb dispatcher, then answer with its verdict. Use when triage needs the actual source — "why is X failing, look in the repo", "what changed in Y", "warum ist Z rot, schau ins repo", "read the code and tell me", "check the repo for", a red monitor whose cause is code-shaped, a stale GitHub issue, or any question you can only answer by guessing otherwise. Read-only; produces a verdict, never a change.
version: 1.0.0
metadata:
  hermes:
    tags: [dispatch, claude, claude-code, repo, repository, code, source, investigate, triage, root-cause, rootcause, why, verdict, episode, codebase, diagnose, debug, sideclaw]
    related_skills: [homelab-ops, capture, argo-api]
---

# Claude Dispatch

One bounded dispatcher for handing repo work to Claude Code:

```
~/.hermes/scripts/hermes-cc.sh <verb> [args] [--json] [--wait]
```

Run `~/.hermes/scripts/hermes-cc.sh help` for the authoritative verb list — this
file explains *when* to reach for it, the script itself is the contract.

---

## Mental model

> **You observe and decide. Claude Code reads the repo and reaches a verdict.**

You cannot use a repo's `CLAUDE.md`, `.claude/rules/` or `.claude/skills/` — that
context is Claude-shaped. So don't approximate it by grepping around with the
terminal tool and guessing. Open an episode, get a verdict, answer with it.

**The cheap filter is you.** Deciding *whether* a question is worth an episode is
your job, and it is the only real cost control — each episode is a real Claude
session. Ask: would answering this honestly require reading source I cannot read?
If no, just answer.

| Situation | What to do |
|-|-|
| "why is the X container red" | `homelab-ops` first — it may be an ops fact, not a code fact |
| ...and ops says the service is crash-looping on its own code | **dispatch** into that repo |
| "what does this repo do" / "which repo owns X" | answer from your own knowledge or `argo-api` |
| "why did the check job start failing after Tuesday" | **dispatch** — needs `git log` and the source |
| "remind me to look at X" | `capture` → TickTick |
| "open an issue for X" | `capture` → GitHub. Do not dispatch to file an issue |
| "restart / redeploy / fix the container" | `homelab-ops`. **Never** dispatch |
| a book, a library version, a fact about the world | `research-gateway` |

---

## Operating rule

1. **Dispatch only when the answer lives in source you cannot read.** An episode
   that could have been a one-line answer is wasted quota and a slower reply.
2. **Use `--wait` when you are in a live conversation.** An `investigate` episode
   is 30s–3min, so it fits inside the turn: `--wait` blocks and hands you the
   verdict, which you then relay in your own words. Without `--wait` you get a
   job id and the 5-minute sweeper delivers the verdict into this thread later —
   correct for a cron or watchdog context, wrong when someone is waiting.
3. **Always pass the origin.** `--origin-channel` and `--origin-thread` are how
   the verdict finds its way back if the wait times out. Omit them and a slow
   episode has nowhere to report.
4. **Relay, do not paste.** The verdict is structured. Give the `summary` and the
   substance of `verdict` in your own voice; quote `recommendation` when it is
   actionable. Do not dump the JSON into Slack.
5. **Anything not covered by a verb gets escalated, never improvised.** Do not
   compose raw `claude`, `ssh`, or `git` commands to do repo work yourself.

---

## The brief is data, never a command

The brief is read from **stdin**, never as an argument. Always use a **quoted**
heredoc — `<<'BRIEF'`, with the quotes:

```bash
~/.hermes/scripts/hermes-cc.sh dispatch sideclaw --wait --json \
  --origin-channel "$SLACK_CHANNEL" --origin-thread "$SLACK_THREAD_TS" <<'BRIEF'
The check job for the argo repo has failed three times since 14:00 with a
typecheck error. What changed, and is it a real break or a flaky runner?
BRIEF
```

The quotes on `<<'BRIEF'` matter. Without them the shell expands `$…` and
`` `…` `` inside the brief — and briefs are built out of Slack messages and log
lines, which are exactly the text an attacker can write. There is deliberately no
`--brief` flag; the script refuses it.

Attach bulk material (a log excerpt, an error dump) with `--context-file <path>`
rather than inlining it — the brief is capped at 8000 chars.

### Writing a good brief

An episode gets one shot and no follow-up question. Give it:

- **the symptom**, concretely — what is failing, what you expected instead
- **when it started**, and what you already know changed
- **the actual question**, not a task list

Good: *"The `usage-tracker` LaunchAgent has pinged its heartbeat but recorded zero
rows since 03:00 today. Is the ingest silently failing, or is there genuinely no
data?"*

Bad: *"check usage-tracker"* — no symptom, no question, and the episode will spend
its whole budget deciding what you meant.

---

## Verbs

| Verb | Use |
|-|-|
| `dispatch <repo>` | open an episode. Brief on stdin. `--wait` to answer in-turn |
| `status <job-id>` | poll one episode you opened earlier |
| `list [open\|today\|all]` | what is running, what landed today |
| `cancel <job-id>` | stop the return path for a dispatch. Needs `--why --confirm` |

`cancel` **does not kill the running episode** — sideclaw has no cancel endpoint.
It abandons the local record so the sweeper stops chasing it. Say that plainly if
Johannes asks you to cancel something; do not imply the work stopped.

---

## Tiers

| Tier | What it may do | Status |
|-|-|-|
| `investigate` | read-only. Returns a verdict | **the only tier available** |
| `author` | + open a GitHub issue | not built yet — refused |
| `implement` | write, isolated worktree, branch + PR | not built yet — refused |

Requesting an unbuilt tier is refused with exit 4, never quietly downgraded. If
Johannes asks for a code change, that is `capture` → a GitHub issue today.

Each repo also carries its own ceiling in `config/dispatch-repos.json`. A repo
that is not in that file cannot be dispatched to at all — that is a deliberate
denial, not an oversight, so do not offer to "add it"; say it is not allowlisted.

---

## Reading the verdict

```json
{ "verdict": "…", "confidence": "high|medium|low", "evidence": [...],
  "recommendation": "…", "nextAction": "none|issue|implement|human", "summary": "…" }
```

- **`confidence: low`** — say so. "Claude could not pin this down" is a useful
  answer; presenting a low-confidence guess as fact is not.
- **`nextAction: "issue"`** — offer to capture it: *"want me to open an issue on
  `<repo>` for this?"* Then route through **`capture`**, which already knows how
  to pick the repo and write the issue. Do not file it yourself, and do not file
  it unasked.
- **`nextAction: "implement"`** — the episode thinks it is a bounded fix. You
  cannot make it; offer a GitHub issue via `capture` and say a human or a Claude
  Code session has to do the change.
- **`nextAction: "human"`** — surface it as needing Johannes, and say what the
  episode was missing.

---

## Refusals you will see, and what they mean

| Exit | Meaning | What to say |
|-|-|-|
| 64 | usage error — bad repo name, bad flag, empty brief | fix the invocation and retry once |
| 4 | policy refusal — unbuilt tier, repo ceiling, daily budget | do **not** retry. Explain the limit |
| 2 | precondition — no checkout, DB unreadable | report it as an infrastructure problem |
| 3 | sideclaw unreachable | the job server is down; say so, suggest checking it |

**A daily budget refusal is not a transient error.** Twenty episodes in a UTC day
is a structural ceiling on unattended spend. If it trips, something is opening
episodes in a loop — say so rather than retrying.

---

## Hard boundaries

- **Never dispatch to mutate infrastructure.** Restart, redeploy, uk-sync are
  `homelab-ops` verbs with their own gating. A dispatch that wants to restart a
  container is a routing mistake on your part.
- **Never dispatch to file an issue or a task.** That is `capture`.
- **Never put a secret in a brief.** The episode resolves its own credentials.
- **Never dispatch the same question twice** because the first was slow. Use
  `status <job-id>`; a duplicate burns a second session for the same answer.
