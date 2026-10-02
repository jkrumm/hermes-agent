---
name: status-projection-verification
description: "Use when relaying an automated pipeline's reported status."
version: 1.0.0
metadata:
  hermes:
    tags: [status, reporting, control-plane, warden, dispatch, staleness, verification]
    related_skills: [warden, defect-report-verification, warden-digest-triage, claude-dispatch]
---

# Status projection verification

An automated pipeline reports its own state through projections — a board row, a
card, a digest line, a `note` column, a job status. Those projections are written
at a transition and are **not** re-derived on read, so they lag the state machine
that produced them. Relaying one as the live reason is how a stale sentence
becomes the user's plan for the day.

Use this whenever you report what a pipeline is doing: a Warden item, a dispatch
job, a CI run, a queue, a digest. The read-only endpoint skills (`warden`) own
*how to call* the surface; this skill owns *what the answer may claim*.

## Rules

1. **Read a projected field against the current state, never on its own.** A
   `note`/card/digest line is written only when a transition passes one — a
   transition that passes none leaves the previous phase's text in place, and
   readers render it verbatim. A row in `investigating` carrying "waiting for a
   free slot" while its `dispatch_job` is already set is leftover text from the
   earlier state, not a live reason. Check the transitions and the identifying
   field (`dispatch_job`, run id, PR url) and describe the actual state; quote
   the note only when it matches it.
2. **"Not done" is a claim about the default branch, not about the estate.**
   Before relaying that something is unimplemented or missing, list the live work
   in flight for that repo — running jobs, their worktrees, open branches — and
   read the in-flight diff. Work can already carry part of the change, so the
   claim reads true and misleads. Say which part is covered and sequence new work
   behind the merge instead of starting a second episode on the same file.
3. **A verdict's own summary is usually the finding; the state name is not.**
   Relay the substance (what was found, what it rests on), then the state. "In
   `verdict`" tells the user nothing they can act on.
4. **Separate live / latent / cleared.** Reproduces now, condition gone but the
   defect still in the code, or the affected data was repaired — three different
   answers that change what the user does next. Never collapse them into "fixed".
5. **A queue/backlog is not a hang.** Distinguish a job waiting on a concurrency
   slot from one wedged: compare the oldest pending age against the running set
   and the cap, and check that the running jobs are still advancing. "Backed up
   behind N running jobs" and "stuck" are different reports.
6. **Name the mechanism, not the symptom.** Which rule, filter, lock, or cap
   produced this state — that is the part the user can act on.

## Pitfalls

- **A card is only re-synced on the next state change**, so a card in flight can
  be hours behind the ledger. Verify against the live store before reporting it
  as outstanding work, and lead with the corrected fact when it has moved on.
- **A status field that doubles as a timestamp or a sentinel is a status wearing
  another column's clothes.** When a system overloads one column, read the schema
  or the writer's docstring before interpreting a value — a string where a
  timestamp belongs usually means "closed, never deliverable", not a date.
- **A retry loop is invisible in the item's state.** Repeated failed operations
  with the same refusal mean the pipeline is stuck against a wall (a ceiling, a
  denied repo, a missing permission) while the state still reads as progressing.
  Count the operations rather than trusting the state name.
- **A missing permission and a broken client look identical from the log.** A
  write path that 403s every tick is a credential-scope problem, not a code bug —
  see `credential-scope-verification` before proposing a fix in the repo.
- **Don't dispatch to close a status line.** A repo capped below the tier the fix
  needs produces another verdict, never the change; say that plainly rather than
  offering a run that cannot land.
