---
name: warden-digest-triage
description: Use when triaging Warden's daily digest or a stuck item.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, triage, digest, alerts, policy, ledger, operations, unmapped]
    related_skills: [warden, claude-dispatch, heartbeat-monitoring]
---

# Warden digest triage

Warden posts one digest per UTC day. It is a work item, not a notification.
Reading Warden's own status (`/health`, `/metrics`, `/board`, `/items/:id`) is the
`warden` skill; **this** skill is what to do with the digest itself.

Three sections, and each means something different:

- **`Unmapped triage signatures`** — `classify()` matched no rule, so the item
  sits in state `new` and never escalates. Not automatically a bug: growing
  `triage-policy.json` deliberately is what the digest exists for.
- **`Unstructured notes in #alerts`** — state `note` rows: `slack_alert` titles
  that did not look like a structured bot alert, kept visible instead of dropped.
- **`Auto-proposed triage-policy changes`** — rules `propose_mappings()` just
  appended to the policy file and committed (`proposedBy: triage-auto`).

## Procedure

1. **Get current state first.** `GET /health` and `GET /board` — the digest is a
   snapshot from when it was posted, not the item's state now. A signature in the
   digest may already be resolved, or already have a rule.
2. **Resolve each signature to its live event and item.** Read the ledger
   read-only through **warden's own venv python**, never the `sqlite3` CLI:

   ```bash
   cd ~/SourceRoot/warden && .venv/bin/python3 -c "
   import sqlite3
   c = sqlite3.connect('file:/Users/jkrumm/.warden/warden.db?mode=ro', uri=True)
   c.row_factory = sqlite3.Row
   for r in c.execute('SELECT event_id, signature, state, repo, occurrences FROM triage_items'):
       print(dict(r))
   "
   ```

   macOS's `/usr/bin/sqlite3` has no `-uri` flag, so it takes `file:…?mode=ro` as a
   literal filename and dies `unable to open database file (14)` — which reads
   exactly like a missing or locked ledger. `scripts/ledger.py` documents the same
   limitation for its own snapshot path.
3. **Check whether the signature is already covered before proposing anything.**
   Match it with `fnmatch` against **both** `ignore` and `rules` in
   `~/SourceRoot/warden/config/triage-policy.json`. Each event has two candidate
   match targets, tried in order: `source:external_id` and
   `source:normalize_title(title)`.
4. **Report a recommendation; do not write the policy file.** It is a
   control-plane input that the loop auto-commits to. Name the rule or `ignore`
   entry you would add and why, and stop there.
5. **Never dispatch to close a digest line.** A repo capped at `investigate`
   cannot be fixed by another `run` — it produces another verdict, not the change.
   Check the ceiling before suggesting a dispatch, and say plainly when the fix is
   a code change in Warden rather than a policy edit.

## Pitfalls that cost real time here

- **A signature in the digest may already have a rule, and the rule can no longer
  rescue it.** The `ignoreUnstructuredSlackProse` structural filter runs inside
  `classify()` *before* rule matching, so a `slack_alert` whose title does not
  start with a recognised bot-alert prefix is routed straight to `note` and never
  reaches the rules. `note` is terminal and `reopen_if_needed()` deliberately
  skips it, so a rule added afterwards is dead for that row. **Check the row's
  state before proposing a rule**: if it is already `note`, the fix is a code
  change (filter after matching, or make `note` reopenable for a new occurrence),
  not a policy edit — and the existing rows need a one-time reset.
- **The structural filter is a prefix test, so an un-prefixed producer's alerts
  all land in `note`.** Notifications from a watchdog that emits plain sentences
  (`HomeLab CPU above threshold`) never look like bot alerts, however real they
  are. When a whole family of signatures shows up as "unstructured prose", suspect
  the producer's message shape, not the policy file.
- **Map `uk` signatures by title, never by monitor id.** `uk:<number>` is an
  opaque UptimeKuma monitor id that changes if the monitor is recreated. The
  mappable form is the title-derived one: `normalize_title('Warden Backup - Push')`
  → `uk:warden-backup-push`. A rule written against the numeric id is a rule that
  silently stops matching.
- **A stuck item can be invisible in `/board` and `/items/:id` alike.** Count
  `operations` rows instead. A dispatch refused by policy leaves no `dispatches`
  row, writes no `note` (only a `PolicyError` writes a `deferred:` note), and
  resets the item's deadline on every tick — so it never reaches `needs_human`
  and `/health` stays `ok` while it retries forever:

  ```sql
  SELECT COUNT(*), SUM(outcome='failed'), MIN(started_at), MAX(started_at)
  FROM operations WHERE event_id=<id>
  ```

  A count that keeps climbing across ticks is a retry loop; `receipt_json` names
  the refusal. The table has no `id` column — order by `started_at`.
- **A repo rename leaves a stale `repo` on already-open rows, and the policy rule
  cannot rescue them.** `classify()` only writes `repo` on rows still in state
  `new`, so an item created before the rename keeps the dead name forever — and
  the loop then retries a dispatch that can never resolve, logging
  `dispatch failed for <old>: repo '<old>' has no git checkout under the dispatch
  root`. The policy file looks correct and the failure is in the ledger. Grep the
  ledger for the old name (`SELECT event_id,state,repo FROM triage_items WHERE
  repo='<old>'`), fix the open rows with a direct `UPDATE`, and leave terminal
  rows alone as history.
- **Two copies of the per-repo tier ceiling exist** (Warden's
  `config/dispatch-repos.json` and sideclaw's `GET /api/dispatch-policy`). When
  they disagree, the loop retries a dispatch the executor will always refuse. Read
  both before concluding a ceiling is or is not in force.
- **An auto-implemented verdict is still worth reading.** The loop acts on a
  high-confidence `nextAction: implement` on its own; the verdict's own summary is
  often the only place the real finding is stated. Relay the substance, not just
  the state name.
- **A `queued:` note survives the claim into `investigating`.** Neither
  `escalate_origin_items()`'s CAS claim nor `_dispatch_investigate_and_advance()`
  passes a `note`, so a row that waited at `MAX_OPEN_INVESTIGATIONS` keeps
  `queued: … waiting for a free slot` while its episode is already running. The
  Slack card renders the `investigating` branch and hides it; `/board` and Argo
  show it. Cosmetic, but never read that note as "not dispatched" — check
  `dispatch_job` first.
- **A card for an issue whose fix already shipped is not a finding about the
  repo.** Label-free intake ingests every open issue, so an issue that was fixed
  and commented but never closed comes back as a fresh investigate item. Verify
  against the repo (`git log -S<symbol>`, the issue's own comments) before
  relaying it, then `warden abort <event-id> --why "already shipped in <version>
  (<commit>)"` and close the issue — the abort leaves the item `closed` with the
  reason on its card.
- **An item whose repo has no checkout under the dispatch root retries forever in
  an invisible claim → reclaim loop.** `escalate_origin_items()` CAS-claims
  `new → investigating` *before* dispatching, and
  `_dispatch_investigate_and_advance()` swallows the `UsageError` (`repo '<name>'
  has no git checkout under the dispatch root`) and returns `None` — leaving the
  row `investigating` with `dispatch_job` NULL. The next tick's orphan-reclaim
  pass resets it to `new` with the **misleading** note `reclaimed: the loop
  stopped between claiming this item and dispatching it`, which blames a crash
  rather than the real cause. No `dispatches` row, no `deferred:` note, no
  `needs_human`, no card update, `/health` stays `ok`. Tell: repeated
  `reclaimed <signature> (event N)` + `dispatch failed for <repo>` pairs in
  `~/Library/Logs/warden-loop.err`, and `item_transitions` alternating
  `investigating → new → investigating` with no job. Intake covers every open
  issue under the owner, so this hits any issue on a repo not cloned under
  `~/SourceRoot` (41 of 71 repos are not). `close` refuses (`state
  'investigating'` — "'abort' is the verb for that"); `abort <event-id> --why`
  works even with `dispatch_job` NULL and lands the row `closed`. Do **not**
  "fix" it by cloning the repo — that makes Warden auto-dispatch on the issue,
  which for a third-party issue is exactly what must not happen.
- **A repo whose issues API the token cannot read is silently outside intake.**
  `search_issues()` is scoped to the token: where `GET /repos/<owner>/<repo>/issues`
  returns 403 (measured on `jkrumm/dispatch-scratch`), the repo's issues never
  appear in the search result set, nothing is ingested, and no error is raised —
  the disappearance-resolve can then retire an event for an issue that is still
  open. When intake looks short, diff `search_issues()`'s count against
  `gh search issues --owner <owner> --state open`.

## Report shape

Lead with the count and the split, then one block per real finding:

- what the signature/event actually is, and whether it is currently live;
- the mechanism, not just the symptom (which rule or filter produced this state);
- whether it is already covered by policy, and if not, the exact rule you would add;
- what you did **not** do, and why (no policy write, no dispatch past a ceiling).

Group lines that share one root cause instead of writing one block per signature —
a family of unmapped signatures from one producer is one finding, and saying so is
more useful than eleven.
