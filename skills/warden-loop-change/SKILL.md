---
name: warden-loop-change
description: Use when changing Warden's live loop (scripts/triage.py).
version: 1.0.0
metadata:
  hermes:
    tags: [warden, control-plane, triage, state-log, tests, live-checkout]
    related_skills: [warden-hand-fixes, warden-blocked-items, agent-work-completion]
---

# Changing the live loop (`scripts/triage.py`)

A change to the loop is not a PR: the file runs from the warden working tree, so a
saved edit *is* the next tick's behaviour. Read-only warden lanes are unaffected;
this is about changing it. The delivery is code + test + § + `STATE.md` in one local
commit, and the evidence is a count — not a green suite.

## Procedure

1. **Read `STATE.md` and grep `docs/history/state-log.md` for the symptom first.** The
   loop's own memory usually already holds the analysis; the missing piece is the call,
   not the diagnosis.
2. **Write the failing test first.** Hand-rolled runners, no pytest:
   `.venv/bin/python3 tests/test_triage.py` prints `N/N passed`; `make test` runs every
   suite. Watch the new case fail for the stated reason before touching the code. The
   test count is a fact to report, never a number to edit.
   - **Give every seeded item its own job ids.** The seed helpers default the
     investigate job to one fixed string, so a second item in the same environment
     collides on `dispatches.job_id` and fails as an insert error rather than as the
     assertion you were writing.
   - **One item per repo is revised per pass.** The loop's per-repo lock defers the
     second same-repo item, so a test that observes two rounds opens two environments.
   - **History is the transition *into* the parked state.** A selector reading earlier
     rounds filters `item_transitions` on `to_state=<parked state>`; inserting the
     reverse direction leaves the history invisible and the test then passes for the
     wrong reason. The row's own `note` only ever holds the latest round, and it is
     capped (~600 chars), so never assert on the tail of a long findings list.
3. **Measure the change against the corpus it decides over.** `VACUUM INTO` a copy of
   the live ledger (never a bare `cp` of an open WAL database) and run the *shipped*
   module against it through the repo's venv python:

   ```python
   import sqlite3, sys
   sys.path.insert(0, str(Path.home() / "SourceRoot/warden/scripts"))
   import triage
   live = sqlite3.connect("file:/Users/jkrumm/.warden/warden.db?mode=ro", uri=True)
   live.execute("VACUUM INTO ?", (str(copy_path),)); live.close()
   ```

   For a classifier or routing predicate the number to report is precision over the
   whole corpus (`N of M classified X, and X is the incident's own row`) plus the live
   row that must *not* fire still taking the old path. A predicate that also catches a
   neighbour, or that never fires on real rows, has not been narrowed.
4. **Land it as one commit, locally.** Code + test + the new § appended to
   `docs/history/state-log.md` + `STATE.md`. Take the § number from the log's tail:
   numbers are allocated in order and the free-looking one is usually already spent on
   an unrelated bullet. **A new § is three edits in `STATE.md`** — the `Last updated`
   table row, the topical bullet, and an entry in the §-index list at the end. The
   commit's job is this working tree's history; check `git status -sb` before assuming a
   push belongs to the ritual.
5. **Touch nothing in the supervision tree** — no restart, no reload, never the
   LaunchAgents or the gateway. The saved file is the behaviour.
6. **Confirm the tick, then re-confirm the effect.** The cadence is 600s; the next run
   must be after the edit, stay `ok`, and show no traceback in
   `~/Library/Logs/warden-loop.err` (that file opens with an older crash, so match a
   traceback to its position instead of counting matches). A change that has not
   survived a tick is not landed, and "the tests pass" is not "the loop now behaves
   differently".

## Rules that keep the change honest

- **Only a demand an episode can act on may spend its budget.** A loop that sends an
  implementer a finding no episode can satisfy — a request to edit a previously opened
  pull request's body, an instruction about a wrapper rather than the diff — spends an
  attempt and then parks the item. Route that class to a human instead.
- **A rule the ask prescribes is a hypothesis — measure it against the incident's own
  rounds before landing it.** A "park when this matches" rule, run over the item that
  produced the report, can park a *legitimate* round. Land the narrow provable part, put
  the explanation on the surface a human reads, and report what you deliberately did not
  land with the measurement that ruled it out and the one-line place it would go.
- **A finding that names the wrong mechanism is worse than a vague one — it is read as
  evidence.** When a card's reason is derived from state, derive it from that state (the
  item's own note and transitions), never from a hardcoded story about what usually
  fails.
- **Do not write the loop's inputs.** The policy file and the ledger rows belong to the
  control plane: change code, state and docs, not rules or rows a human owns — and do not
  "unstick" rows an older behaviour left behind.
- **Keep a record of the deviation.** When the delivered change is narrower than the
  ask, say so in the commit body, the § entry and the reply: the narrower scope plus its
  measurement is the deliverable.
