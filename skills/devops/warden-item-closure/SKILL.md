---
name: warden-item-closure
description: Use when a Warden card's blocker is gone; close it by hand.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, lifecycle, needs_human, merge_blocked, closure, slack-card, ledger]
    related_skills: [warden, warden-lifecycle-gates, warden-digest-triage, claude-dispatch]
---

# Closing a Warden item by hand

A `needs_human` or `merge_blocked` row is **terminal until its own 168h
deadline** — `reopen_if_needed()` covers `fixed`/`quiet`/`closed`/`dismissed`
only, and `poll_implement_jobs()` has no retry path once a row lands there. So a
card whose cause has since evaporated keeps sitting on the board and keeps being
re-sent by `remind_needs_human()` while the work behind it is already done.

The map from a `note` to the gate that wrote it is `warden-lifecycle-gates`; this
skill is the three-step move that ends such a card: **verify the blocker is gone,
close the row, verify the close landed.** Reading status is `warden`.

## 1. Verify the blocker is gone — never close on "looks old"

A stale `note` is the normal case, not the exception. Check the live condition:

- **Schema-pin note** (`sideclaw implement result schemaVersion N, warden expects M`)
  → `make check-schemas` in `~/SourceRoot/warden` prints the pin-vs-endpoint truth;
  `curl -s http://127.0.0.1:7705/api/dispatch-schema` is the live answer. The
  constant in sideclaw's *source tree* is not the running server.
- **The stored job result still validates** →
  `curl -s http://127.0.0.1:7705/api/jobs/<job_id>` and read `result.outcome`,
  `result.artifactUrl`, `result.summary`. A `done` job with an `artifactUrl` is
  the episode having succeeded, whatever the card says.
- **The artifact exists** → `gh pr list --state open` / `gh pr view <n>` in the repo.
- **The branch itself is sound** → fetch by full refspec into a throwaway worktree
  and run the repo's own targets:

  ```bash
  cd ~/SourceRoot/<repo>
  git fetch origin 'refs/heads/<branch>:refs/remotes/origin/<tmp>'
  git worktree add --detach /tmp/<repo>-v origin/<tmp>
  cd /tmp/<repo>-v && ln -sfn ~/SourceRoot/<repo>/node_modules node_modules
  bun test && bun run typecheck && fallow audit
  ```

  Remove the worktree before finishing — a detached worktree left in `/tmp` keeps
  the repo's `git worktree list` dirty for the next session.

## 2. Close the row

```bash
cd ~/SourceRoot/warden && ./scripts/warden close <event-id> --why "<what the blocker was, why it is gone, what shipped, where it is>"
```

- **`close` writes the `closed by hand: ` prefix itself.** Never put that phrase in
  `--why`, or the stored note reads `closed by hand: closed by hand: …`.
- **`--why` is required and is the durable record.** The card's own `note` was
  usually a *symptom*; put the real defect in `--why` (e.g. "the poller has no
  retry path once a row lands in `needs_human`, so the card never learned the PR
  existed").
- **It refuses from `investigating`** — `abort <event-id> --why` is the verb there,
  and it works even when `dispatch_job` is NULL. `close` accepts
  `needs_human` / `merge_blocked`.
- `abort` is also the right verb for an in-flight episode whose *brief* was wrong:
  it cancels the job and closes the item in one move, which is cheaper than
  letting it produce a verdict for work you are about to re-brief.

## 3. Verify the close landed — and that the card caught up

- `curl -s http://127.0.0.1:7735/items/<id>` → `state: closed` plus the new
  `item_transitions` row. That is the ledger truth.
- **The Slack card is re-rendered on the loop's next tick (600s).** A card still
  showing the old state minutes after the close is expected, not a second finding.
- **To tell whether Slack is current without a read scope**, re-render the card and
  compare hashes against `triage_items.card_hash`:

  ```python
  import sys; sys.path.insert(0, 'scripts'); import triage
  rows = conn.execute("SELECT * FROM triage_items WHERE event_id=?", (n,)).fetchall()
  ev   = conn.execute("SELECT * FROM events WHERE id=?", (n,)).fetchall()
  fresh = triage._card_hash(triage.render_card_blocks(rows, ev, conn))
  # fresh == rows[0]['card_hash'] → Slack already shows the current state
  ```

  `events` has **no `event_id` column** — the join key is `events.id = triage_items.event_id`.
- **The loop's Slack token is post/update-only.** `chat.postMessage` and
  `chat.update` work; `conversations.history` / `conversations.replies` return
  `missing_scope`. A reminder reply already threaded under a card therefore cannot
  be read back or removed: the card is corrected in place and the reply stays as
  history. Say that plainly instead of promising a cleanup.

## 4. Hand the artifact over in a reviewable state

- **Implement episodes open their PR as a draft.** A draft cannot be merged and
  CodeRabbit skips it (`Review skipped: draft pull request`), so `gh pr ready <n>`
  is part of finishing — it is what turns the branch into the owner's review.
- **A merge refusal is the correct outcome, not an obstacle.** Repos with no
  `autoMergePaths` declared, and repos listed in `~/.claude/pr-required-repos.json`,
  are the owner's review by design. Report the gate; never merge on github.com.

## Pitfalls

- **A reminder that arrives around a close describes the state from *before* it.**
  `remind_needs_human()` fires on a 24h/72h schedule and renders `note` +
  `state_deadline` straight from the row, and the card is only re-rendered on the
  next tick. "24h reminder → close → card still shows the old state" is one
  sequence, not two findings. Say the reminder is already stale.
- **`reminder_count` is a lifetime cap, not per episode.** A closed row is never
  re-selected, so no second reminder follows the close — do not go looking for one.
- **Never re-dispatch to unstick an item.** Every gate reproduces the same refusal
  against the same wall and spends another episode.
- **Do not rewrite or delete ledger history to tidy a card.** `item_transitions`
  is append-only and the close note is the record; correctness lives in the note,
  not in a clean-looking table.
- **The ledger will not open `mode=ro` when its `-wal`/`-shm` sidecars are absent**
  (the normal state — the loop checkpoints). `sqlite3.connect('file:…?mode=ro',
  uri=True)` then dies `unable to open database file` even from warden's venv python,
  because read-only SQLite may not create the `-shm`. Works, in order of preference:
  `cp ~/.warden/warden.db "$TMPDIR/wd.db"` and open the copy read-write (safe, and the
  write path can never touch the live ledger), or `?mode=ro&immutable=1` for a
  throwaway read (skips locking — never while the loop may be mid-write). The
  `sqlite3` CLI has no `-uri` at all on macOS, so `file:…?mode=ro` is read as a
  filename there and fails the same way.
- **`triage_items` has no `title` column** — the title lives on `events`; join
  `events.id = triage_items.event_id`.

## Report shape

Verdict first: *item N is closed — the blocker was gone and the work shipped as
PR #M, now ready for review.* Then the mechanism in one line (which gate wrote the
note and why it no longer applies), then the verification numbers (tests /
typecheck / lint), then what is still the owner's. Name what you did **not** do —
no merge past a missing scope, no re-dispatch, no cleanup of the reminder reply —
and stop there.
