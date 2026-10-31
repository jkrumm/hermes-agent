---
name: herdr
description: Open, inspect and steer terminals, tabs and agents in Johannes's Herdr workspace on this mini (the Herdr app + herdr-core, driven with `hc` and `rd`). Use when he explicitly names Herdr or asks for a terminal/tab/agent there ("mach einen herdr tab auf", "starte cf in <repo>", "open a herdr tab", "schreib das in den Tab", "schau in den Tab von <repo>", "was macht der Agent in <repo>", "sag dem Agenten …", "stopp den Agenten"). Also the path for starting an interactive Claude Code session in a repo on his request, prompting it and reading its answer back. Not for unattended background work.
version: 2.0.0
metadata:
  hermes:
    tags: [herdr, hc, rd, terminal, tab, tabs, space, agent, claude, claude-code, cf, cs, interactive, steer, mini]
    related_skills: [capture, verify]
---

# Herdr — Johannes's visible terminal workspace

Herdr is two parts on this mini. **herdr-core** is a launchd service that owns the
terminals and keeps them alive; **hc** is its CLI. The **Herdr app** (on his MacBook)
shows them: one **space** per project, **tabs** inside it, a terminal per tab. Agents
are terminals that report `idle` / `working` / `done` / `blocked` / `error`.

Manuals that are always current — read them instead of trusting this page for flags:

- `hc --skill` — running, waiting on, sending to and reading terminals.
- `herdr-app --skill` — spaces, tabs and the window layout. (It may not be on this
  mini's `PATH`; the app lives on the MacBook. Say so rather than guessing.)

## Which lane is this

| He asks for | Lane |
|-|-|
| "look into the repo and tell me why X" · "fix it" · anything that needs a repo's source | `capture` → a GitHub issue; the owner starts the repo work. |
| "what are my agents doing", a cross-project status read | `agw agents --text` (cross-project overview, read-only) |
| **"open a herdr tab"**, "start `cf` in dotfiles", "write that into the tab", "tell the agent in <repo> …", "stop that agent" | **this skill** |

The difference is not safety, it is **who owns the work**. A filed issue is a
note for later. A Herdr tab is *his* workspace — he asked for it, he can see it in
the app, he steers it himself afterwards. So: never silently substitute an issue
for a Herdr request. If he says Herdr, use Herdr. If Herdr genuinely cannot do it,
say so and stop — do not do something else and call it done.

Unattended work you decide to start yourself is filed as an issue (`capture`), never
started. Nothing here schedules itself.

## The layout rules

- **One space per project.** `~/SourceRoot/dotfiles` and `~/IuRoot/dotfiles` are two
  spaces, never one. You never create or rename spaces — `rd` places a tab in the
  right one.
- **Orchestrator visible, workers hidden.** A wave's orchestrator is a labelled tab.
  Its workers are unlabelled children of it: no tab, no pane; the app lists them as
  the parent's `sub_agents`. A worker you cannot see in the app still shows in
  `hc ls` (with `parent`) and in `agw agents`.
- **Accounts are on the command, not inherited.** `rd work|wave` picks a Claude Max
  account per spawn (`claude-account pick`) and passes it in the spawn's `env`
  (`CLAUDE_CONFIG_DIR`; absent for the IU route). If no account has room it
  **pauses** — `paused: …` — and never falls back to IU API tokens. Retry after a
  reset; do not route around it. Which account an agent runs on is the `account`
  field (`me`, `me2`, `iu`) in `agw agents`.

## You are not inside a terminal

`hc`'s manual assumes the caller is a terminal (`$HC_TERMINAL_ID`). You are not.

- **Always pass the target explicitly** — an address (`t7`), a name (`dotfiles-w5`)
  or `machine/t7`. `hc read`, `hc get`, `hc wait` and `hc interrupt` with no target
  mean "the calling terminal", which is none for you.
- Read addresses and names out of `hc ls` / the JSON a command returns, never out of
  an example or a guess.
- Never `hc attach` — you cannot drive a TUI. Read and send instead.
- Never bare `hc` with no subcommand.

## Read the topology

```bash
hc ls | jq -r '.terminals[] | "\(.address)  \(.name // "-")  \(.agent)  \(.status // "-")  \(.parent // "-")  \(.cwd)"'
rd agents                 # SOURCE NAME STATUS CWD ID — hc rows first, classic rows after
agw agents --text --format plain     # per project, with account, git state, human queue
```

`hc ls` is JSON (`.terminals[]`: `address`, `name`, `agent`, `cwd`, `state`,
`status`, `parent`, `turn`, `where` = the app's "space / tab"). It lists **all** live
terminals, including his plain shells — `hidden_finished` counts finished ones it
leaves out. A terminal's repo is its `cwd`; to act "in repo X" find the one
whose `cwd` is that repo.

`status`: `idle` (ready for input) · `working` · `done` (a turn finished) ·
`blocked` (waiting on an approval/question dialog) · `error`. A plain program such
as `zsh` has **no status** — absence is not proof of completion. Do not guess
status from screen text.

## Read what a terminal says

```bash
hc read --lines 120 dotfiles-w5      # screen plus 120 lines of history — plain text, not JSON
hc get dotfiles-w5                   # one terminal's state/status (JSON)
```

`hc read` output is **plain text** — do not pipe it to `jq`. If more `--lines`
reveals nothing more, the program is on the alternate screen and the rows are
unrecoverable: ask the agent to write its answer to a file and read the file instead.
`rd read <agent> [lines|visible]` is the same by repo name or classic pane id.

## Start an agent — `rd`, not `hc run`

`rd` is the dotfiles script `~/SourceRoot/dotfiles/scripts/remote-dev.sh`; if the bare
`rd` name does not resolve in your shell, call it by that path. It does the account
pick, the space/tab placement, the parent rules and the prompt delivery. A hand-rolled
`hc run … claude` inherits the core's environment, not an account, and lands wherever
the app puts it.

| Verb | What it starts |
|-|-|
| `rd work <repo> [--role R]` | a labelled tab with an interactive `claude` for that repo, no prompt (idempotent: it reports an agent already there instead of stacking a second) |
| `rd wave <repo> '<prompt>'` | a fresh tab + solo agent with the prompt as claude's first argument — long work he watches or steers |
| `rd fan <repo> <brief-files…>` | one worktree + hidden child terminal per brief (workers). Only on his request. |
| `rd merge <repo> <branches…>` | rebase/check/merge train, GitHub only |
| `rd read <agent>` / `rd say <agent> <text>` / `rd close <agent>` | read, steer, close a finished agent |
| `rd agents` | every agent on the host, hc and classic |

`<agent>` is whichever of repo name, hc address / name (`t7`, `iris-w3`) or classic
pane id `rd agents` put in front of you.

**Launchers and models.** "Mit `cf`" / "`cs`" means the model: `c` = default, `cf` = Fable,
`cs` = Sonnet, all on the Max subscription. `rd wave` takes its model from the
`RD_WAVE_MODEL` env var (`RD_WAVE_MODEL=<alias> rd wave …`), `rd work` only from `--role R`
(tier + effort from the factory role table: `mother|lead|wave|worker|mechanical`). If neither
gives him the model he named, the fallback is a plain shell he can see:
`hc run --bg --name <repo>-hermes --cwd <repo-path> --keep`, then
`hc send <repo>-hermes cf` (the launcher picks the account itself). Its tab is where the app
puts it — read `where` from `hc ls` and tell him, because `rd` does not place this one. `ca` is
the IU endpoint route, off Max: never start development work with it.

**Do not push a long brief through `rd` argv.** Put the full text in a file and
make the prompt "read `<path>` and do what it says". Nothing here sends a raw
`claude --bg` / `claude -p`, which loses the keychain credential and the house flags.

Confirm it started: `rd agents` shows the new row `working`, or `hc get <agent>`
says so. A zero exit is not proof of delivery — read the terminal before claiming it
started.

## Prompt it, and read the answer back

**Pass Johannes's words verbatim — never pre-digest them.** When he hands over a
voice memo, a transcript or a wall of text, write it into the prompt file *as it
stands* and pass that. Do not restructure it into numbered points, do not
summarize it, do not "clean it up", do not strip the rambling — the agent has the
full repo, the rules and the domain context you don't, and it is better at
extracting the real task from his phrasing than you are at guessing it. Your
reformatting silently deletes signal. This holds for briefs to any agent lane
(Herdr tab, `capture` issue), not just this one.

A long or multi-line prompt goes through a file — never try to inline it, quoting
will bite you:

```bash
cat > /tmp/hermes-prompt.txt <<'BRIEF'
…the full text, verbatim, as many lines as it takes…
BRIEF
hc send dotfiles-w5 "$(cat /tmp/hermes-prompt.txt)"     # or: rd say dotfiles-w5 "$(cat …)"
```

`hc send` pastes the text and presses Enter. It **refuses on `blocked`** — read the
terminal, tell Johannes what it is asking, and let him decide. Never `--force` it:
that types into a permission dialog and is a permission decision. `--if idle` makes
the send conditional (a working agent keeps its turn).

### A draft in the input line is not yours to send

Terminals regularly show a **non-empty input line** at the bottom — text someone typed
that never got submitted (`weiter, commit und push wenn der Trip durch ist`). It is
almost always Johannes's, typed while the agent worked, with his Enter swallowed.

- **Never hit Enter on it and never re-send it through `hc send`.** You cannot
  tell his draft from a stale artifact, and acting on a guess puts words in his
  mouth at an agent that is about to write to a repo.
- **Name it and ask**, in one clause, at the end of your report — *"im Tab
  steht ein ungesendeter Entwurf: <text> — von dir?"*
- **The work must not stall while you wait.** If his draft states the obvious next
  step and that step is already authorized, send that same instruction **in your
  own words** via `hc send`. That is relaying, not submitting his text.
- Three of these in one afternoon means the submit path is broken, not that
  he changed his mind. Say so once, name the workaround (`sag mir, was der Agent tun
  soll`), and move on.

Stopping: `hc interrupt <agent>` ends the current turn, not the process. `hc kill
<agent>` then `hc rm <agent>` (or `rd close`) ends the terminal — only one you
opened, only when he asked, and `rd close` only closes a clean, pushed one.

## Always report where it is

Every answer about a terminal names **what the tab is for and what is running in it** —
that is what he can act on. Johannes does not read `t22` or `sp-…`; a bare address is
noise in a chat message and unusable in a voice memo.

- Say: *"der Validierungs-Tab im email-gateway (läuft gerade die Prüfung durch)"*,
  *"der Wave-3-Tab, Agent `email-gateway-w3`, arbeitet an den Jobs"*.
- Give the raw address only when he asks for it, or when he needs it to find the
  thing in the app right now — then in a trailing parenthesis, never as the subject.
- Same rule in a spoken/TTS summary: name the tab by its purpose, never by address.
- "Started" without saying which tab and what it does is not an answer.
- A hidden worker has no tab: name it as "ein Helfer von <orchestrator>", not as a tab.

## After you finish steering an agent

An agent works in the checkout it was started in — unless it is a `rd fan` worker, there
is no worktree isolation. In a repo whose files are **symlinked live** (dotfiles,
hermes-agent) that means its branch is the running configuration. Always close the loop:

```bash
git -C <repo> branch --show-current   # back on master? if not: git -C <repo> switch master
git -C <repo> status --short
```

Leaving dotfiles on a `fix/...` branch makes the live config the unmerged branch — a
one-line botched edit pages the dev host. Restore the default branch as soon as the
agent reports done; the branch is pushed, so nothing is lost.

## Watching an agent to an outcome

**One blocking call, never a watcher script** (no `/tmp/watch-*.sh`, no `sleep` loop, no
ad-hoc cron):

```bash
hc wait <agent> --timeout 120      # returns when it stops working, blocks, errors or exits
```

Your terminal tool dies at 180 s, so keep `--timeout` ≤ 150 and, on a timeout (`reason:
timeout` — a check-in, not a failure), re-issue the same call once or twice, then stop and tell
him it is still running. A `blocked` status means the agent asks him something — report
that, never answer for him.

`done` ends a *turn*: an agent that parked a background shell goes `done` and resumes later.
Before reporting an outcome, confirm the **external effect** the brief asked for (PR state,
the commit on master, `/health`, the report file). For anything that must survive past this
conversation, do not wait at all — file it as an issue (`capture`).

## Rules

- Only on his explicit request. Never open a tab as a side effect of some other task.
- Never close or kill a terminal, tab or space you did not open, unless he asked.
- **Never** `hc server stop|restart`, `hc update`, `hc machine update` or kill the
  core process — one core serves every agent on the machine, and a restart ends or
  replaces them all. launchd owns the core; do not start one by hand either.
- Never `hc attach`; read and send instead.
- Never `hc send --force`, and do not answer an agent's approval/question dialog for him.
- Don't inspect terminals he didn't ask about just because `hc ls` lists them — it
  includes his plain shells.
- Classic `herdr` CLI panes (the `herdr` row source in `rd agents` / `agw agents`) are
  being retired; if `rd read|say` reaches one, treat it like any other agent, but do not
  start new work there. <!-- TODO(Wave 7): drop classic -->
