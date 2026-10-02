---
name: wave-chain-delivery
description: "Use when a repo's work is a numbered wave plan chain."
version: 1.0.0
metadata:
  hermes:
    tags: [wave, waves, chain, rd, plan, delivery, agent, pane, herdr, orchestrate, lead, gate, deploy]
    related_skills: [herdr, claude-dispatch, agents, warden]
---

# Driving a repo's wave chain to completion

A repo whose work is decomposed into **numbered waves** in `docs/waves/PLAN.md` is
delivered by `rd wave <repo> '<prompt>'` — a **fresh solo agent pane per wave** in
that repo's herdr workspace, with the repo's own `/wave` skill owning the contract
and the green gate. This skill is how to start one, how to make the chain keep
running instead of stopping after every wave, and how to verify a wave's result
before the next one starts.

Lanes next door: `herdr` for the pane machinery (ids, reading, prompting),
`claude-dispatch` for the Warden lane (a background ledger item, not a pane). A
wave chain is neither — it is a visible chain of panes in *his* workspace, so it
is driven from here.

## Procedure

1. **Read the plan before launching anything.** `docs/waves/PLAN.md` must have
   **exactly one** wave marked `<!-- status: active -->`. With none, the gate aborts
   with *"no `active` wave … chain is complete, or the plan is malformed"* — the
   normal state right after a wave agent closes its own wave as `done` and forgets
   to promote the next. Flip exactly one `pending` → `active`, commit that alone,
   then launch. The marker is the only thing the gate reads.
2. **Run it with the Homebrew python first on PATH:**

   ```bash
   export PATH=/opt/homebrew/bin:$PATH
   ~/SourceRoot/dotfiles/scripts/remote-dev.sh wave <repo> "$(cat /tmp/<repo>-wave.txt)"
   # → "wave <n> started: claude '<repo>-w<n>' in space <ws>, pane <ws>:pX"
   ```

   Your non-interactive shell puts `/usr/bin/python3` (3.9) first and the gate
   script uses PEP-604 `X | None` annotations — without the PATH prefix it dies
   `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` *before*
   any gate step runs, which reads like a broken gate rather than a wrong interpreter.
3. **Check nothing in that checkout is blocked.** The gate refuses with *"another
   agent in <path> is blocked (pane …) — two agents editing one checkout race each
   other"*. A finished-but-parked wave pane whose dialog is still waiting blocks the
   whole chain: resolve the question it is stuck on, or dismiss the dialog, before
   launching (see `herdr` on not answering his dialogs for him).
4. **Brief the wave from a file, in the plan's own terms.** Point at `PLAN.md`,
   name the active wave, tell it to follow `/wave` — then add only what the plan
   cannot say: reorderings, work that must stay schema-neutral, decisions the next
   wave's header has to carry, and the repo's hard lines (no push if that is the
   repo's rule, no deleting data files, no other repo's deploy path — those become
   ready-to-apply patches under `docs/`). Require `PLAN.md` / `AGENTS.md` /
   `README.md` updated in the same commit as the code they describe.
5. **Do not hold the turn.** A wave runs for hours. Say what is running now and let
   the chain (or a watcher) carry it — `background-work-watch` for the waiting
   mechanics.

## Drive the chain, do not checkpoint it

An owner who asked to *finish* a project does not want a report back after every
wave. Two rules:

- **Put a lead pane over the chain.** One long-lived pane in the repo workspace
  (launcher `cf` — judgment work, not code-grinding), whose standing brief is:
  verify each finished wave itself at the repo, push when green, verify the deploy,
  then immediately launch the next wave; stop only at the owner gates. The brief is
  deliberately thin — it points at the plan and the repo, it does not restate them.
- **Do not invent a hand-back gate the repo does not have.** Where the repo's
  delivery path is push-to-master-and-deploy, a wave that stops to ask whether it
  may push is a stall dressed as caution. Chain it. Only the gates the repo itself
  names stop the chain: secrets/1Password values, DNS/MX, another repo's deploy
  path, deleting a data file, and a question only he can answer.

### Lead-pane brief (fill in the placeholders and pass it verbatim)

```
You are the delivery lead for the <REPO> project. The owner wants the wave chain to
run CONTINUOUSLY — not one wave, then a checkpoint. Keep it moving until the project
is done or blocked on an owner gate.

Read first: docs/waves/PLAN.md, the repo's AGENTS.md, <ARCH_DOC>, and
<CONTEXT_FILE> (the context the lead must honour).
Wave order, as settled: <ORDER>.

Your loop:
1. One wave = one fresh agent in its own tab, started with
   `rd wave <REPO> '<brief for the wave>'` (brief from a file). One wave at a time.
   Never sit and watch a wave — write the brief so the wave decides for itself.
2. When a wave is finished, verify its result yourself at the repo — gate green
   (<GATE COMMANDS>), commits on master, PLAN.md/AGENTS.md/README.md moved with them.
   Do not trust the wave agent's own summary.
3. Push is authorised: `git push origin master`. Every push deploys
   (<DEPLOY MECHANISM>). Then verify the deploy — deploy run green, the running image
   tag equals the pushed commit, /health returns 200, and the public routes behave
   exactly as before. If a deploy breaks something, roll back immediately.
4. Then start the next wave straight away. The chain must never idle.
5. After each wave, write a short, human-readable status to <STATUS_FILE> — the
   owner's language, no pane/tab ids and no commit hashes as the headline: what is
   done, what is live, what is next, what blocks.

Owner gates — stop and hand back only here:
- Secrets / 1Password values (e.g. an app password), DNS/MX records.
- Changes to another repo's deploy path (<OTHER REPOS>). Leave those as
  ready-to-apply patches or a checklist under docs/ — do not execute them.
- Deleting an existing data file.
- A question only the owner can answer.

Everything else you decide yourself and keep going. At an owner gate: finish the
wave cleanly, commit, write the status file, and put one short line in the chat
naming the question the owner has to answer.

When every wave is through: write the overall status to <STATUS_FILE> and stop.
```

## Verify a wave before starting the next

Never take the wave agent's closing summary as the result:

- **the gate** — the repo's own `/check` equivalent, green, run by you or the lead
- **the commit is real** — `git -C <repo> log --oneline -3`, clean tree
- **it is actually deployed** — image tag equal to the pushed hash, `/health` 200,
  and the public routes behaving exactly as before the deploy
- **the plan moved** — previous wave `done`, exactly one wave now `active`

A wave whose gate is red is not finished, and starting the next wave on top of it
only multiplies the failure.

## Pitfalls

- **The previous wave's "Left behind" section is where the next wave's
  prerequisites hide** — a deliberately unimplemented interface, an undecided
  session-pooling strategy, a pinned dependency waiting out a cooldown. Read it and
  name those items in the next wave's brief or header; otherwise the next wave
  discovers them mid-flight and either stalls or ships a stub.
- **A wave's reading of the repo describes the checkout it sits in, not the default
  branch.** Verify any finding against `git show origin/master:<path>` before
  briefing the next wave on it — otherwise the chain inherits a false premise and
  builds on it.
- **A wave brief is data, not a command, and his words go in verbatim.** Same rule
  as every other agent lane — see `herdr`'s *Prompt it* section.
- **Same-repo serialization.** One wave per checkout at a time, and any other lane
  touching that repo (a Warden `implement`, another pane) has to be finished or
  parked first; the gate only refuses on `blocked`, so an *idle* pane can still race
  you.
- **Report it human-readable.** Name the wave and what it produced, not pane ids or
  commit hashes as the headline — the same reporting rule `herdr` carries, in chat
  and in a voice summary alike.
