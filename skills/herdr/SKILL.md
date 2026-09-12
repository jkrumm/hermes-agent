---
name: herdr
description: Open, inspect and steer herdr panes, tabs and workspaces on this mini — Johannes's own visible terminal workspace. Use when he explicitly names herdr or asks for a pane/tab/agent there ("mach einen herdr tab auf", "starte eine pane in <repo> mit cf", "open a herdr pane", "schreib das in eine pane", "schau in die pane von <repo>", "was macht der Agent in <repo>", "sag dem Agenten …", "stopp den Agenten in der pane"). Also the path for starting an interactive Claude Code session (`c` / `cf` / `cs`) in a repo on his request, prompting it and reading its answer back. Not for unattended background work — that is `claude-dispatch` → Warden.
version: 1.0.0
metadata:
  hermes:
    tags: [herdr, pane, panes, tab, tabs, workspace, terminal, multiplexer, agent, claude, claude-code, cf, cs, interactive, steer, mini]
    related_skills: [agents, claude-dispatch, warden]
---

# herdr — Johannes's visible terminal workspace

herdr runs on this mini and organises terminals into **workspaces → tabs → panes**.
It recognises coding agents inside panes and exposes everything through the `herdr`
CLI, which is on your `PATH` and talks to the running server over its socket. You
may use every verb it has.

## Which lane is this

| He asks for | Lane |
|-|-|
| "look into the repo and tell me why X" · "fix it" · anything **unattended, tracked, to an outcome** | `claude-dispatch` → Warden. Ledger, budgets, tiers, draft PR. |
| "what are my agents doing", a cross-project status read | `agents` (sideclaw overview, read-only) |
| **"open a herdr pane/tab"**, "start `cf` in warden", "write that into a pane", "tell the agent in <repo> …", "stop that agent" | **this skill** |

The difference is not safety, it is **who owns the work**. A Warden dispatch is
*your* background job, invisible until it reports. A herdr pane is *his* workspace —
he asked for it, he can see it in the TUI, he steers it himself afterwards. So:
never silently substitute a Warden dispatch for a herdr request. If he says herdr,
use herdr. If herdr genuinely cannot do it, say so and stop — do not do something
else and call it done.

Unattended work you decide to start yourself still goes to Warden. Nothing here
schedules itself.

## You are not inside a pane

Every example in herdr's own docs assumes it runs *in* a pane. You do not.

- **Never** `--current`, `--pane` without an id, or anything that depends on focus —
  you would target whichever pane Johannes is looking at.
- **Always** pass explicit ids: workspace `w1E`, tab `w1E:t9`, pane `w1E:p4`.
- **Never** `--focus` unless he asked to be taken there. Default `--no-focus`.
- Read ids out of the JSON a command returns, never out of an example or a guess.
- Never run bare `herdr` — it tries to attach a TUI.

## Read the topology

```bash
herdr workspace list | jq -r '.result.workspaces[] | "\(.workspace_id)  \(.label)  \(.agent_status)"'
herdr tab list --workspace w1E | jq -r '.result.tabs[] | "\(.tab_id)  \(.label)"'
herdr pane list --workspace w1E | jq -r '.result.panes[] | "\(.pane_id)  \(.agent // "-")  \(.agent_status)  \(.cwd)"'
herdr agent list | jq -r '.result.agents[] | "\(.pane_id)  \(.agent)  \(.agent_status)  \(.terminal_title_stripped)"'
```

**Workspaces are labelled by repo** (`warden`, `hermes-agent`, `brain`, …) plus
separator rows (`── INFRA ──`). To act "in repo X", find the workspace whose label
is X. Separator workspaces are not work areas — never open anything there.

`agent_status`: `idle` (ready for input) · `working` · `blocked` (waiting on an
approval/question dialog) · `done` (finished unseen background work) · `unknown`
(a process herdr cannot classify — *not* proof of completion).

## Read what a pane says

```bash
herdr pane read w1E:p4 --source recent-unwrapped --lines 120
herdr agent read w1E:p4 --source recent-unwrapped --lines 120
```

Output is **plain text, not JSON** — do not pipe it to `jq`. Use
`recent-unwrapped` for transcripts and logs, `visible` for the current viewport.
If more `--lines` reveals nothing more, the agent is on the terminal's alternate
screen and the rows are unrecoverable — ask the agent to write its answer to a
file and read the file instead.

## Open a tab or a pane

A new tab in an existing repo workspace (the normal case):

```bash
herdr tab create --workspace w1E --cwd /Users/jkrumm/SourceRoot/warden --label hermes --no-focus
# → .result.tab.tab_id, .result.root_pane.pane_id
```

A sibling pane next to an existing one:

```bash
herdr pane split w1E:p4 --direction right --cwd /Users/jkrumm/SourceRoot/warden --no-focus
# → .result.pane.pane_id
```

Split wide panes `right`, tall ones `down`. Always pass `--cwd` explicitly — a pane
that inherits an unstated directory is exactly the bug the repo guards exist for.

## Run a command in a pane

```bash
herdr pane run w1E:p4 'git status'
herdr pane wait-output w1E:p4 --match 'nothing to commit' --timeout 60000
herdr pane read w1E:p4 --source recent-unwrapped --lines 60
```

`pane run` types the command and presses Enter atomically. `pane send-text` types
without Enter; `pane send-keys` sends logical keys (`Enter`, `esc`, `ctrl+c`).

## Start an interactive Claude Code session

The pane's shell is an interactive zsh, so the **dotfiles launchers** work there —
this is how Johannes starts one himself, and what he means by "mit cf":

| Launcher | What it starts |
|-|-|
| `c` | Claude Code on the Max subscription, current default model |
| `cf` | same, pinned to **Fable** |
| `cs` | same, pinned to **Sonnet** |
| `ca [model]` | the IU endpoint route, off Max |

Start it by typing the launcher into the pane — **not** `herdr agent start`, which
uses herdr's own bare `claude` command and loses the house flags:

```bash
herdr pane run w1E:p4 'cf'
herdr pane wait-output w1E:p4 --regex 'bypass permissions|Welcome|>' --timeout 90000
herdr agent list | jq -r '.result.agents[] | select(.pane_id=="w1E:p4")'
```

Wait until that pane shows up in `agent list` as `claude`/`idle` before prompting.

## Prompt it, and read the answer back

A long or multi-line prompt goes through a file — never try to inline it, quoting
will bite you:

```bash
cat > /tmp/hermes-prompt.txt <<'BRIEF'
…the full text, verbatim, as many lines as it takes…
BRIEF
herdr agent prompt w1E:p4 "$(cat /tmp/hermes-prompt.txt)"
```

`agent prompt` refuses with `agent_blocked` if the agent sits at an approval
dialog — read the pane, tell Johannes what it is asking, and let him decide.

**Do not use `--wait` on a long turn.** Your terminal tool times out at 180 s, so a
wait above ~150000 ms kills the call, not the agent. Prompt without waiting, tell
him it is running, and poll instead:

```bash
herdr agent get w1E:p4 | jq -r '.result.agent.agent_status'
herdr agent read w1E:p4 --source recent-unwrapped --lines 150
```

Steering an existing agent is the same two verbs: `agent prompt` for text,
`agent send-keys` for `esc` (interrupt) or `ctrl+c` (stop).

## Always report where it is

Every answer about a pane names the ids, so he can find it: workspace label, tab
id, pane id, and what is running in it. "Started" without a pane id is not an
answer.

## Rules

- Only on his explicit request. Never open a pane as a side effect of some other task.
- Never close a workspace, tab or pane you did not open, unless he asked.
- Never `herdr server stop`, never kill the herdr process — that takes down every
  agent on the machine.
- Never `--takeover` on `agent attach`, and never attach at all from here; you
  cannot drive a TUI. Read and prompt instead.
- Do not answer an agent's approval/question dialog for him.
- Don't inspect panes he didn't ask about just because you can.
