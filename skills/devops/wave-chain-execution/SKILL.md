---
name: wave-chain-execution
description: Use when a repo runs a wave chain (`rd wave`).
version: 1.0.0
metadata:
  hermes:
    tags: [wave, rd, plan, PLAN.md, email-gateway, basalt-ui, agent, claude-code, gate, herdr, mini]
    related_skills: [herdr, claude-dispatch, background-work-watch]
---

# Wave chains (`rd wave`)

A **wave chain** is a repo's own plan file (`docs/waves/PLAN.md`) plus one fresh solo
agent pane per wave, each gated on the repo's green check. It is the third lane:
`claude-dispatch` → Warden is a tracked one-off, the `herdr` skill is the pane he
opened by hand, and a wave chain is the long multi-day build of a repo. Use this
when the repo carries a `docs/waves/PLAN.md` and "run the next wave" is the work.

**Pane mechanics live in the `herdr` skill** (explicit ids, never `--current`, `pane
read` is plain text, no `--wait`). This file is the wave lane on top of it, and the
`rd wave` gate, which that skill does not cover.

## Launch

`rd` is a **zsh function** (`~/.zsh/conf.d/remote-dev.zsh`), so the `terminal` tool's
shell does not have it. Call the script it wraps, with `/opt/homebrew/bin` first on
`PATH`:

```bash
export PATH=/opt/homebrew/bin:$PATH
~/SourceRoot/dotfiles/scripts/remote-dev.sh wave <repo> "$(cat /tmp/wave-brief.txt)"
# → wave 3 started: claude '<repo>-w3' in space w1Y, pane w1Y:pB
```

**Do not open a pane first.** The wave lane creates its own pane in the repo's
workspace and prints tab/pane id — those ids are what you report back.

**`PATH` pitfall.** House scripts call `python3` and use 3.10+ syntax
(`def f(x: str) -> str | None`). Under the `terminal` tool `/usr/bin/python3`
(macOS 3.9) wins, and the script dies at the `def` line with `TypeError: unsupported
operand type(s) for |: 'type' and 'NoneType'` — which reads like a broken repo gate
rather than a wrong interpreter. Prepend `/opt/homebrew/bin` (3.14) for any
`remote-dev.sh` / `wave-gate.py` / house-script call.

## The pre-flight gate refuses twice — both are the contract, not a broken tool

- `no 'active' wave in …/docs/waves/PLAN.md — chain is complete, or the plan is
  malformed` → the plan must carry **exactly one** wave header marked
  `<!-- status: active -->`. An agent that closes its own wave flips *that* header to
  `done` and does not necessarily flip the next one; make the one-line edit and commit
  it, then re-run. Reach for this before concluding the chain is finished.
- `another agent in <repo> is blocked (pane w1E:pNN) — two agents editing one checkout
  race each other` → the previous wave's pane is parked on a question dialog. Clear it
  with `herdr agent send-keys <pane> esc`: that **cancels** the dialog (the pane then
  reads "User declined to answer questions") without answering it — answering is still
  forbidden — and it is the only way to release the checkout. Never route around it by
  starting the wave in a second checkout.

## The brief

Pass the owner's words **verbatim** — never pre-digest them — plus: read the plan
first, execute the active wave, follow the repo's own `/wave` skill. Then the hard
lines the wave must not cross, every time:

- do **not** push (`master` usually deploys, via RollHook, from the same repo), the
  old data file is never deleted, no hostname published, no other repo's deploy path
  edited, no secrets;
- such steps come back as a ready-to-apply patch or checklist under `docs/`;
- gate green → commit per logical concern, update the plan/`AGENTS.md`/`README.md` in
  the same commit as the code they describe, then **stop and hand back**.

If the work depends on a corrective finding from a validation pass, point the wave at
that file (`/tmp/<x>-validate.md`) and name the plan edits it must fold into the wave
header **before** writing code — a wave that starts coding before amending its own
header builds on the old plan.

## Read it back without losing the report

Have the wave agent keep the deliverable on disk as it goes, and read the file rather
than the screen — a pane on the alternate screen loses rows you cannot recover, and a
status flip proves nothing on its own (an agent can be `done` with the report
half-written). Poll status plus file in one loop, `sleep 20`, no `--wait`:

```bash
for i in $(seq 1 14); do
  st=$(herdr agent list | jq -r '.result.agents[] | select(.pane_id=="w1Y:pB") | .agent_status')
  f=$(test -s /tmp/x.md && echo yes || echo no); echo "$st $f"
  { [ "$st" != working ] && [ "$f" = yes ]; } && break
  sleep 20
done
```

## When the wave hands back a push

A wave agent stopping on "push now?" is not stuck work — treat it as the deploy gate
and **decide it explicitly** rather than leaving the pane parked (a parked `blocked`
pane refuses the next wave in that checkout). Validate the diff against the repo's
live callers first — import-only moves, additive optional parameters defaulting to the
old singletons, untouched routes/env/migrations all read as "additive, no behaviour
change" — then push and verify the deploy, because a green gate locally says nothing
about the running app:

```bash
gh run list --limit 3; gh run watch <run-id> --exit-status        # deploy run
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/health    # the door
```

and confirm the container is running **the commit you pushed** — RollHook tags the
image with the commit hash, so read it out of `/docker/vps/containers` (or
`docker ps --format '{{.Image}}'` on the VPS) and compare. A `200` from `/health` on
the *previous* image is not verification. Then exercise the live routes unchanged
(send routes still answer, gated routes still `401`).

## Rules

- One wave at a time per checkout; the gate enforces it — do not parallelise around it.
- Never `close`/`abort`/re-plan a wave on your own judgement; the plan is the owner's.
- Report the outcome (gate, commit, deploy) with the tab/pane id, never "wave started".
