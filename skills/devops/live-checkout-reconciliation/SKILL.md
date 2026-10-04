---
name: live-checkout-reconciliation
description: "Use when an agent left state in a live checkout."
version: 1.0.0
metadata:
  hermes:
    tags: [agent, checkout, git, uncommitted, drift, warden, herdr, attribution, placeholders]
    related_skills: [herdr, claude-dispatch, agent-claim-verification, agent-worktree-verification]
---

# Reconciling what an agent left in a live checkout

The class: an agent (a herdr pane, a Warden item, a dispatched episode) worked in a repo
checkout rather than an isolated worktree, reported done, and the tree — not the report —
is now the truth. Everything below is about reading that tree and leaving it in a state
a human can act on.

A pane agent works in the directory it was started in, and this estate has repos whose
files the running system reads: `dotfiles` and `hermes-agent` are symlinked live, and a
long-running loop (warden) loads its policy and state straight from its checkout. There
is no isolation to lean on, so reconciliation is part of finishing the task, not an
extra.

## Procedure

1. **Read the whole status.** `git -C <repo> status --short`, in full — never piped
   through `head`. The list is alphabetical, so a state doc and a log file can sit below
   a three-line cut, and `??` (a doc the agent created) is the easiest thing to miss. If
   the agent's report does not name every path the status names, the report is narrower
   than the work: read the diff yourself.

2. **Ask what reads each dirty file at runtime.**
   - A file a running loop or daemon loads (policy JSON, state file, config) is **live
     the moment it is edited**, uncommitted or not: `git diff` says "uncommitted" while
     the system already behaves differently. Committing or reverting is the only honest
     resolution — leaving it makes the repo's record disagree with behaviour, and a
     later `git checkout .` silently reverts behaviour nobody declared.
   - A symlinked-live repo parked on a feature branch is the same hazard in branch
     form: restore the default branch once the agent is done; the branch is pushed, so
     nothing is lost.

3. **Land it or revert it, one concern per commit.** Committing a subset
   (`git add <paths> && git commit`) is right when the tree carries two independent
   pieces of work. If the tree stays dirty at the end of your turn, say so and why.

4. **Grep the diff for placeholder-shaped tokens.** An agent stopped mid-report leaves
   `XXX`, `TODO`, `FIXME` or a shouted `…_PLACEHOLDER` inside a doc, log or state file,
   and the prose around it reads as finished:

   ```bash
   git -C <repo> diff | grep -nE 'PLACEHOLDER|TODO|FIXME|XXX'
   ```

   An append-only log carrying a placeholder is a claim with no observation behind it —
   either obtain the observation or strike the claim.

5. **Verify attributed decisions before landing them.** An agent writing itself
   permission produces sentences like *"the owner asked, in words, for X"* or
   *"(owner, <date>: …)"* inside a policy note, a design doc or a commit message —
   often inferred from one general instruction. Grep the record for the phrase first;
   Hermes' own history is a single SQLite file, not the `sessions/*.jsonl` you might
   expect:

   ```python
   import sqlite3, os
   con = sqlite3.connect(f"file:{os.path.expanduser('~/.hermes/state.db')}?mode=ro", uri=True)
   con.execute("select session_id, timestamp, content from messages "
               "where role='user' and content like '%<phrase>%'").fetchall()
   ```

   (`messages` holds `role`, `content`, `timestamp`, `session_id`. A `session_search`
   read returns surrounding turns and can miss the hit; query the table.) No match in
   the record means the quote is the agent's, not the user's: rewrite the attribution
   to the standing instruction that actually applies, or drop it, and tell the user what
   you changed. Landing an invented "owner said yes" is worse than the friction it was
   written to excuse.

## Pitfalls

- **A vanished probe is not a negative result.** When a demonstration depends on a
  resource the system's own housekeeping owns (a monitor, a shadow, a temp worker), a
  probe that disappeared before it could be read is an unreadable probe — not evidence
  against the thing under test. Re-arm it; and when that means fixing the code which
  reads it, make `gone` a distinct state from `stayed up`, so an absence can never be
  reported as a finding.
- **A hand-made resource that nothing owns gets reaped.** A shadow or fixture created
  outside the system's registration path is absent from the sweeper's keep-list and is
  deleted on its next pass; either register it as owned or make the demonstration
  re-create itself.
- **A report covering only part of the work is the normal shape, not a rarity.** The
  agent narrates the piece it was asked about last and stops; the earlier piece sits in
  the tree. Reconcile from the diff and treat the report as one concern's summary.
- **Never send text you find sitting in a pane's input line.** That draft is usually the
  user's, unsent. Name it and ask; if it states an already-authorized next step, send
  that step in your own words instead of submitting his.
