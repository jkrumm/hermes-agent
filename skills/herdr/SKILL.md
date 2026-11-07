---
name: herdr
description: Read and steer EXISTING terminals and agents in Johannes's Herdr workspace on this mini, with `hc`. Use when he explicitly names Herdr or a tab and wants to see or talk to a running terminal ("schau in den Tab von <repo>", "was macht der Agent in <repo>", "schreib das in den Tab", "sag dem Agenten …", "stopp den Agenten"). Never for starting agent work (that is the `fleet` skill) and never for fleet status.
version: 3.0.0
metadata:
  hermes:
    tags: [herdr, hc, terminal, tab, agent, steer, read, mini]
    related_skills: [fleet, capture]
---

# Herdr — read and steer an existing terminal

**herdr-core** (launchd) owns the terminals; **hc** is its CLI; the Herdr app on his MacBook shows them (one space per project, tabs inside). Agents are terminals reporting `idle` / `working` / `done` / `blocked` / `error`. Current manual: `hc --skill`.

## Lanes

| He asks for | Path |
|-|-|
| "let an agent do X", "start an agent …", any new agent work | `skill_view('fleet')` → `factory signal file`. This skill starts nothing. |
| "how is X going", what is running, what needs him | `skill_view('fleet')` → `factory read …`. Never the pane list. |
| Look into / talk to a terminal that already exists | this skill |

Only on his explicit request. Never touch a terminal as a side effect of another task.

## You are not inside a terminal

- **Always pass the target explicitly**: address (`t7`), name, or `machine/t7`. A bare `hc read|get|wait|interrupt` means "the calling terminal", which is none for you.
- Take addresses and names from `hc ls` output, never from an example or a guess.
- Never bare `hc`, never `hc attach`.

## Find it, read it

```bash
hc ls | jq -r '.terminals[] | "\(.address)  \(.name // "-")  \(.agent)  \(.status // "-")  \(.cwd)"'
hc read --lines 120 <target>     # plain text, not JSON: no jq
hc get <target>                  # one terminal's state (JSON)
```

`hc ls` lists all live terminals including his plain shells (`--all` adds finished ones). A terminal's repo is its `cwd`. A plain program (`zsh`) has no status: absence is not proof of completion; do not guess status from screen text. Do not inspect terminals he did not ask about. If more `--lines` shows nothing new the program is on the alternate screen: ask the agent to write its answer to a file and read that.

## Steer it

```bash
hc send <target> "<text>"            # pastes, presses Enter; refuses on a blocked terminal
hc send <target> "<text>" --if idle  # only when it is not mid-turn
hc interrupt <target>                # ends the current turn, not the process
```

- **Pass his words verbatim.** Do not restructure, summarize or clean up a transcript; the agent extracts the task better than you do. Long or multi-line text: write it to a file and `hc send <target> "$(cat /tmp/hermes-prompt.txt)"`.
- `blocked` = the agent asks him something: read the terminal, tell him what it asks, let him decide. Never `hc send --force`, never answer a dialog for him.
- **A draft in the input line is not yours.** Non-empty text at the bottom prompt is probably his unsent draft. Never press Enter on it or re-send it. Name it in one clause and ask. If the next step is already authorized, relay the instruction in your own words.
- `hc kill` / `hc rm` only a terminal you opened, only when he asked.

## Watch to an outcome

One blocking call, never a watcher script or `sleep` loop:

```bash
hc wait <target> --timeout 120
```

Your terminal tool dies at 180 s: keep `--timeout` at or below 150. On `reason: timeout` (a check-in, not a failure) re-issue once or twice, then tell him it is still running. `done` ends a turn only: confirm the external effect (PR state, commit, `/health`) before reporting an outcome. For anything that must outlive this conversation, file it (`fleet` or `capture`) instead of waiting.

## Always say where it is

Name the tab by what it is for and what runs in it ("the validation tab in email-gateway, running the checks"), never by address. Give the address only when he asks, in a trailing parenthesis. A hidden helper has no tab: "a helper of <orchestrator>".

## After steering an agent

An agent works in the checkout it started in. In a repo whose files are symlinked live (dotfiles, hermes-agent) its branch is the running configuration. When it reports done:

```bash
git -C <repo> branch --show-current   # not master? git -C <repo> switch master
git -C <repo> status --short
```

## Rules

- **Never** `hc server stop|restart`, `hc update`, `hc machine update`, or kill the core: one core serves every agent on the machine; launchd owns it.
- Never `hc attach`, never `hc send --force`.
- Never close or kill a terminal, tab or space you did not open unless he asked.
