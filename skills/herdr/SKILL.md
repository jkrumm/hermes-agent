---
name: herdr
description: Open, inspect and steer herdr panes, tabs and workspaces on this mini — Johannes's own visible terminal workspace. Use when he explicitly names herdr or asks for a pane/tab/agent there ("mach einen herdr tab auf", "starte eine pane in <repo> mit cf", "open a herdr pane", "schreib das in eine pane", "schau in die pane von <repo>", "was macht der Agent in <repo>", "sag dem Agenten …", "stopp den Agenten in der pane"). Also the path for starting an interactive Claude Code session (`c` / `cf` / `cs`) in a repo on his request, prompting it and reading its answer back. Not for unattended background work — that is `claude-dispatch` → Warden.
version: 1.0.0
metadata:
  hermes:
    tags: [herdr, pane, panes, tab, tabs, workspace, terminal, multiplexer, agent, claude, claude-code, cf, cs, interactive, steer, mini]
    related_skills: [dispatch, warden, verify]
---

# herdr — Johannes's visible terminal workspace

herdr runs on this mini and organises terminals into **workspaces → tabs → panes**.
It recognises coding agents inside panes and exposes everything through the `herdr`
CLI, which is on your `PATH` and talks to the running server over its socket. You
may use every verb it has.

## Which lane is this

| He asks for | Lane |
|-|-|
| "look into the repo and tell me why X" · "fix it" · anything **unattended, tracked, to an outcome** | `dispatch` → Warden (`hermes-cc.sh run`). Tracked to a merged, verified fix. |
| "what are my agents doing", a cross-project status read | `warden` skill → `references/agents.md` (sideclaw overview, read-only) |
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
that inherits an unstated directory silently runs in the wrong repo.

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

**Pass Johannes's words verbatim — never pre-digest them.** When he hands over a
voice memo, a transcript or a wall of text, write it into the prompt file *as it
stands* and pass that. Do not restructure it into numbered points, do not
summarize it, do not "clean it up", do not strip the rambling — the agent has the
full repo, the rules and the domain context you don't, and it is better at
extracting the real task from his phrasing than you are at guessing it. Your
reformatting silently deletes signal. This holds for briefs to any agent lane
(herdr pane, `dispatch`), not just this one.

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

### A draft in the input line is not yours to send

Panes regularly show a **non-empty input line** at the bottom — text someone typed
that never got submitted (`weiter, commit und push wenn der Trip durch ist`). It is
almost always Johannes's, typed while the agent worked, with his Enter swallowed.

- **Never hit Enter on it and never re-send it through `agent prompt`.** You cannot
tell his draft from a stale artifact, and acting on a guess puts words in his
mouth at an agent that is about to write to a repo.
- **Name it and ask**, in one clause, at the end of your report — *"in der Pane
  steht ein ungesendeter Entwurf: <text> — von dir?"*
- **The work must not stall while you wait.** If his draft states the obvious next
  step and that step is already authorized, send that same instruction **in your
own words** via `agent prompt`. That is relaying, not submitting his text: `agent
  prompt` submits reliably (verified) while his typing path does not.
- Three of these in one afternoon means the pane's submit path is broken, not that
  he changed his mind. Say so once, name the workaround (`sag mir, was der Agent tun
  soll`), and move on.

**Do not use `--wait` on a long turn.** Your terminal tool times out at 180 s, so a
wait above ~150000 ms kills the call, not the agent. Prompt without waiting, tell
him it is running, and poll instead:

```bash
herdr agent get w1E:p4 | jq -r '.result.agent.agent_status'
herdr agent read w1E:p4 --source recent-unwrapped --lines 150
```

Steering an existing agent is the same two verbs: `agent prompt` for text,
`agent send-keys` for `esc` (interrupt) or `ctrl+c` (stop).

## The `rd` lane — placing durable work on the mini

`rd` is not on Hermes' PATH; it is `~/SourceRoot/dotfiles/scripts/remote-dev.sh`.
It spawns *through* a herdr pane so the Max keychain credential is reachable (a
bare `ssh mini 'claude …'` comes up `Not logged in` and silently bills the API).

| Verb | What it starts |
|-|-|
| `rd wave <repo> '<prompt>'` | a fresh herdr tab labelled `wave <n>` running one bounded wave |
| `rd agents` / `rd read` / `rd say <pane>` | track, read, steer |

The model is an env var, not a flag: **`RD_WAVE_MODEL`** (default `sonnet`). `rd` is the only way to place work on the mini — never a raw `claude --bg` / `claude -p`, which loses the keychain credential and the house flags.

A long prompt is safe: the script base64s it and stages it in a temp file,
because a pane's canonical input stops at 1024 bytes — never inline a brief
longer than ~700 bytes by hand.

## Integrations — the difference between a pane and an agent

`herdr integration status` lists every agent herdr 0.9.1 knows; `herdr integration
install <name>` wires one. Two kinds, and the difference decides what a pane can do:

- **Lifecycle authority** (Pi, OMP, Kimi Code CLI, OpenCode, Kilo Code, MastraCode) —
  hook/plugin events author `idle`/`working`/`blocked`, with no screen-manifest fallback.
- **Session identity** (Claude Code, Codex, Copilot, Devin, Droid, Qoder, Qwen, Letta,
  Cursor, Hermes Agent, Antigravity, Grok) — a session reference for restore
  (`claude --resume <id>`, `opencode --session <id>`); state still comes from the screen.

Without its integration a pane still works, but state is screen-read and the agent
**cannot be resumed after a herdr restart**. A stale one is silent: status prints
`outdated (v8 < v10)` — re-run the install after a herdr upgrade, since the version
lives in the hook/plugin file. Traps: Claude's install rewrites only
`~/.claude/hooks/herdr-agent-state.sh` (the SessionStart entry lives in dotfiles'
settings template — leave it alone); Codex additionally needs `[features] hooks = true`
in `~/.codex/config.toml`, which belongs in `config/codex/config.toml.tpl` or
`make setup` drops it; the **Hermes** integration writes `~/.hermes/config.yaml`, so it
is a human's call, never this skill's.

## Always report where it is

Every answer about a pane names **what the tab is for and what is running in it** —
that is what he can act on. Johannes does not read `w1Y:tA` / `w1Y:pA`; a bare id is
noise in a chat message and unusable in a voice memo.

- Say: *"der Validierungs-Tab im email-gateway (läuft gerade die Prüfung durch)"*,
  *"der Wave-3-Tab, Agent `email-gateway-w3`, arbeitet an den Jobs"*.
- Give the raw ids only when he asks for them, or when he needs them to find the
  thing in the TUI right now — then in a trailing parenthesis, never as the subject.
- Same rule in a spoken/TTS summary: name the tab by its purpose, never by id.
- "Started" without saying which tab and what it does is not an answer.

## After you finish steering a pane agent

A pane agent works in the checkout it was started in — there is no worktree isolation.
In a repo whose files are **symlinked live** (dotfiles, hermes-agent) that means its
branch is the running configuration. Always close the loop:

```bash
git -C <repo> branch --show-current   # back on main? if not: git -C <repo> switch main
git -C <repo> status --short
```

Leaving dotfiles on a `fix/...` branch makes the live config the unmerged branch — a
one-line botched edit pages the dev host. Restore the default branch as soon as the
agent reports done; the branch is pushed, so nothing is lost.

## Watching a pane agent to an outcome

A watcher that keys on `agent_status` **ends early**: a Claude pane that started a
backgroundshell, a monitor or a subagent goes `done` or `idle` at the end of each
turn while the work is still running, then resumes itself when that shell reports.
An `idle` pane is therefore not a finished pane.

Watch the **artifact or the external effect** instead, and treat status as colour:

| Signal | Use |
|-|-|
| the report file the brief asked for (`-s /tmp/<x>-report.md`) | primary |
| the real-world result it claims (PR state, master head, `/health`, the commit) | primary |
| `agent_status` | colour only — never a terminal condition |
| identical line N times in a row | real stall detection |

Poll every 60–90 s, log one line per tick so a timeout is diagnosable, and exit with
a distinct code per outcome (report / external-effect / stalled / timeout). A watcher
that exits `4 idle_no_report` four times in a row is not four findings — it is one
bad condition; fix the watcher before reporting again.

## Rules

- Only on his explicit request. Never open a pane as a side effect of some other task.
- Never close a workspace, tab or pane you did not open, unless he asked.
- Never `herdr server stop`, never kill the herdr process — that takes down every
  agent on the machine.
- Never `--takeover` on `agent attach`, and never attach at all from here; you
  cannot drive a TUI. Read and prompt instead.
- Do not answer an agent's approval/question dialog for him.
- Don't inspect panes he didn't ask about just because you can.
