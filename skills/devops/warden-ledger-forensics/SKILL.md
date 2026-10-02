---
name: warden-ledger-forensics
description: "Use when verifying a Warden item from the ledger directly."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, ledger, sqlite, forensics, triage, verification, status]
    related_skills: [warden, status-projection-verification, claude-dispatch, stalled-dispatch-forensics]
---

# Warden ledger forensics

The loopback API (`http://127.0.0.1:7735/board`, `/items/<id>`, see the `warden`
skill) is the documented read path and answers most questions. Reach for the
ledger itself only when the answer is **not in the projection**: the real reason
a terminal item ended, whether an abort/refusal reason is a pattern, counts by
state or note, or anything about items that already left the board.

## Read-only, always

```python
import sqlite3
con = sqlite3.connect("file:/Users/<user>/.warden/warden.db?mode=ro", uri=True)
```

Run it with the warden venv python (`~/SourceRoot/warden/.venv/bin/python3`, 3.11)
or the hermes venv. Two hard rules: **never the macOS `/usr/bin/sqlite3` CLI** — it
has no `-uri` and dies with `unable to open database file (14)` — and **never a
write**. The ledger belongs to Warden; opening, merging, aborting or noting is
`claude-dispatch`.

**That `mode=ro` recipe fails whenever the `-wal`/`-shm` sidecars are absent** —
the normal state, because the loop checkpoints. Read-only SQLite may not create the
`-shm`, so you get `unable to open database file` even from the right python. Two
recipes that work, in order of preference:

```python
# 1. a copy, opened read-write — the write path can never reach the live ledger
subprocess.run(["cp", os.path.expanduser("~/.warden/warden.db"), f"{os.environ['TMPDIR']}/wd.db"])
con = sqlite3.connect(f"{os.environ['TMPDIR']}/wd.db")
# 2. throwaway read: skip locking entirely — never while the loop may be writing
con = sqlite3.connect("file:~/.warden/warden.db?mode=ro&immutable=1", uri=True)
```

**`triage_items` has no `title` column** — titles live on `events`; join
`events.id = triage_items.event_id`.

## Tables that earn their keep

- `triage_items` — `event_id, signature, repo, state, note, brief,
  card_channel, card_ts, occurrences, updated_at`. `note` is the loop's own
  sentence about why the item is where it is.
- `events` — `source, external_id, title, url, resolved_at`: the original signal.
- `transitions` — `from_state, to_state, at, note`: what actually happened, in
  order, when the current `note` looks like leftover text.
- `operations` — failed rows carry their refusal in `receipt_json`; a cluster of
  the *same* failure means the loop is stuck against a wall.
- `dispatches` — one row per episode (`job_id, tier, status, artifact_url,
  validation_status`), several per item across a chain.

## Rules

1. **A terminal state is the loop's record, not the resolution.** `closed`
   means the automation stopped; its `note` says what the *automation* did
   ("aborted: dispatch never actually started (no git checkout for <repo>);
   issue closed on GitHub") and never carries the human's reason. When the note
   asserts a resolution you cannot verify from the ledger, read the source
   object itself — for an issue:
   `gh issue view <n> --repo <owner>/<repo> --json state,stateReason,comments
   --jq '.comments[] | "\(.author.login): \(.body)"'`. A hand-written closing
   comment is authoritative and invisible in every projection; report "already
   closed, by hand, because X" instead of re-offering the work.
2. **"Is this a pattern?" is a query, not an impression.** `/board` lists only
   non-terminal items, so a recurring abort or refusal reason is invisible
   there. Count it:
   `select count(*) from triage_items where note like '%<phrase>%'`. One hit is
   a one-off; a cluster is a defect in the loop worth naming.
3. **State the answer the user asked for, then stop.** A status question is
   answered from the ledger and the source object — never by re-dispatching,
   and never by offering a run that cannot land.
4. **"No git checkout for <repo>" is a bridge precondition, not a repo defect.**
   A dispatch names a repo, resolved under the single root (`~/SourceRoot`), and
   requires a real git checkout there — a repo that exists on GitHub but was
   never cloned is unreachable at every tier. The fix is a clone; a retry
   changes nothing.
5. **Say what you verified, not that you verified.** Lead with the disposition
   ("already closed, by hand"), then the evidence line, then the one-line
   "rest is green" summary. No PIDs, no SQL transcripts unless asked.
6. **A `warden_self` finding is a predicate over rows, and its predicate is
   coupled to the shape the writer currently produces — read the rows before
   believing the headline.** `self_audit_findings()` (scripts/triage.py) fires
   `review-always-blocks-<repo>` when ≥3 `tier='implement'` rows in 14 days all
   carry `validation_status='blocked'`, and that column is written from the
   review's *folded* outcome — so a switch-order change in
   `poll_validation_jobs()` silently re-scopes the audit. Since e68c43c (§115)
   `elif outcome == "needs-human"` precedes `elif code_blocking`, so a
   needs-human review that carries genuine code-blocking findings writes
   `needs_human` and is invisible to the finding. Resolve the headline against
   the rows: join each implement row to its review row
   (`dispatches.validation_job_id → dispatches.job_id` where `tier='review'`),
   read `verdict_json.outcome` and classify `verdict_json.blocking[]` with
   `_is_process_only_finding()` — a code finding under a needs-human outcome is a
   real defect the audit will not report, not a fold artifact. The same query
   counts **rows, not items**, so a revised PR contributes one row per attempt:
   check `COUNT(DISTINCT origin_event_id)` before quoting an `n` as a PR count.
