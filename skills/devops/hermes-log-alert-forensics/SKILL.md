---
name: hermes-log-alert-forensics
description: Use when a Hermes log ERROR line reaches Warden or #alerts.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, logs, alerts, warden, triage, streaming, gateway, errors-log, hermes-log]
    related_skills: [hermes-gateway, alert-liveness-forensics, warden-digest-triage, warden, claude-dispatch]
---

# Hermes log alert forensics

Warden's poller tails Hermes's own error logs and turns each distinct ERROR
signature into a `hermes_log:*` event, a Slack card and a triage item. This skill
is the triage for that family — deciding whether the line is a real fault, and
then discharging or escalating the item.

`alert-liveness-forensics` owns producer-side liveness for Beszel / UptimeKuma /
HyperDX; it does not cover this family. `hermes-gateway` owns gateway health and
Rule 0 (slice every log read at the current process start) — obey that first, then
come here.

## The one mental model

> **An ERROR line in Hermes's logs is a record of an ATTEMPT, not of a failure.**

Hermes logs the stream error *before* its own retry loop runs. A blip that
self-heals on the next attempt and a genuine outage produce the byte-identical
line, so the line alone cannot answer "is this real". Only reading forward from it
can.

## Procedure

1. **Slice at the current process start** (`hermes-gateway` Rule 0). `errors.log`
   and `gateway.error.log` span restarts, so an unsliced grep mixes a dead
   incarnation's errors with the live one. If the only occurrence predates the
   running PID, the answer is "history", not "incident" — stop there.
2. **Locate the line in both tailed files** and read the count honestly
   (see the first pitfall — the card's `×N` is not a count of distinct events).
3. **Read forward from the timestamp, ~10–60s.** Look for the retry's own
   success line (`API call #<n+1>: … latency=…`), a `Retrying API call in …s`
   warning, or a `Fallback activated` line. That window is where the verdict is.
4. **Classify.** Self-healed in one retry with no fallback and no user-visible
   loss → transient; report it as such and discharge the item. A repeat, an
exhausted retry (`API call failed after 3 retries`), or a fallback activation →
real; escalate.
5. **Discharge or escalate** (last section). Do not leave a verdict-only item
   sitting on its deadline.

## Pitfalls

- **The `×N` on a gateway-sourced card is roughly DOUBLE the real occurrence
  count.** The poller tails **both** `logs/errors.log` and
  `logs/gateway.error.log` (`HERMES_LOG_FILES` in warden's `watchdog-poll.py`),
  and every gateway-originated line is written to both — byte-identical. Both
  reads increment the same signature, so `batch_count` counts files, not events.
  Verify before quoting a number: grep the line in each file and compare. The
  consequence is worse than a cosmetic wrong number — the escalation threshold
  is `minOccurrences: 3`, so for this family it is really **2**, and a genuinely
  one-off blip can trip it. Report the real count and say the card's is inflated.
- **`cron.scheduler: Job '<name>' failed: RuntimeError: [drift_skip] …` is a spend
  guard working, not a fault — and its fix is host-side, never a repo dispatch.**
  The scheduler refuses to fire an **unpinned** job whose creation snapshot
  (`<axis>_snapshot`, written at create/edit time) no longer equals the resolved
  global provider/model: no inference call, one alert (the `drift_alerted` bit; later
  ticks carry the `:silent` marker), and the job stays skipped every tick until the
  axis is pinned. Remediation is one command on the host running Hermes —
  `hermes cron edit <job_id> --provider <p> --model <m>`; a pin clears both snapshots
  and hands authority to the pin, so the job deliberately stops following later global
  switches. Pick the *current* brain when the drift is the estate's own deliberate
  rollout (check `model.default` in `config.yaml`), not the old snapshot. Cheap proof
  either way, with `~/.hermes/hermes-agent/venv/bin/python3` (system `python3` is too
  old for `hermes_cli`): `cron_model_drift_axes(job, current_provider=…,
  current_model=…, config=…)` → `[]`, plus `build_cron_model_impact(...)` to see the
  whole fleet (0 = nobody else blocked). Do **not** dispatch a repo episode for this —
  the cause is config state, so an investigate verdict can only restate the pin — and
  do **not** set `cron.model_drift_guard: false`, which is the brake itself. The
  resulting Warden item is discharged with `close` once the pin is verified: the
  guard cannot re-fire against a pinned axis.
- **`Streaming failed before delivery: Request timed out.` is logged BEFORE the
  retry, not after the failure.** A retry that succeeds seconds later still
  leaves this ERROR with a full traceback. Never relay it as an outage without
  reading forward — the truthful sentence is usually "one connect timeout, retry
  succeeded N seconds later".
- **A transient connect timeout lands at ERROR with a traceback because of an
  exception-classification gap, not because it was fatal.**
  `_handle_stream_error` (`agent/chat_completion_helpers.py`) tests only the raw
  httpx types — `httpx.ReadTimeout`/`ConnectTimeout`/`PoolTimeout` — so the
  wrapping `openai.APITimeoutError` (MRO: `APITimeoutError → APIConnectionError
  → APIError`) and `openai.APIConnectionError` miss the transient set, fall to
  the `logger.exception` branch, and log at ERROR while the outer loop still
  retries them. `_is_sse_connection_error` does not rescue it either: it returns
  False for anything with a `status_code` and for the phrase "Request timed
  out". **Treat the traceback as noise, not as severity** — read the retry, not
  the log level. A fix belongs as a `patches/*.patch` entry in hermes-agent
  (add the two openai classes to the transient set), never as a
  `request_timeout_seconds` override in `config.yaml`.
- **`tools.checkpoint_manager: Git command failed: git add -A (rc=128)` is a data defect
  in the shadow store, not a code-only bug — repair the data first, then the code.**
  The store is `~/.hermes/checkpoints/store` (one bare repo, per-project index at
  `indexes/<sha256(abs_workdir)[:16]>`, project metadata at `projects/<hash>.json`).
  A nested git repo gets recorded in a project's index as a mode-160000 **gitlink**
  while it is healthy; macOS's `com.apple.tmp_cleaner` (daily, `-atime/-mtime/-ctime
  +3`) then deletes that repo's `.git/HEAD`, `.git/config` and `.git/refs` while
  leaving `.git/objects` and `.git/index` — the directory still reads as a nested-repo
  boundary git cannot resolve, so `git add -A` over the whole working tree fails
  rc=128 forever, one ERROR per file-mutating tool call. `_seed_project_index`
  read-trees the ref tip back in on every snapshot, so it never self-heals.
  Repair order: (1) quarantine or remove the gutted `.git` (nothing is lost — it has
  no HEAD and no config); (2) `update-index --force-remove <path>` the dead gitlink
  from the project's index under `GIT_DIR=<store> GIT_WORK_TREE=<workdir>
  GIT_INDEX_FILE=<store>/indexes/<hash>`; (3) commit a gitlink-free tree to
  `refs/hermes/<hash>` (read-tree the ref, force-remove, add -A, write-tree,
  `commit-tree -p <old>`, `update-ref`) so no later read-tree resurrects it. Then
  verify with a real `CheckpointManager.ensure_checkpoint(workdir, …)`, not a bare
  `add -A`. A **gone** directory needs no recovery (`add -A` returns 0 and drops the
  gitlink itself); `--ignore-errors` does **not** help (still rc=128) and neither does
  `info/exclude` (the gitlink is already in the index).
- **A `tools.checkpoint_manager` ERROR names a path, not the project.** The shadow
  project is resolved by `get_working_dir_for_path` (nearest ancestor carrying a
  project marker), so one stray `/tmp/package.json` makes **all** of `/tmp` a single
  project — the failing path in the message is a child of the wedged workdir, and the
  fix has to be applied to the project's index, not to that child.
- **Do not reach for the restart host verb.** Of the `hostVerbs` in warden's
  `triage-policy.json`, only `hermes_log:*session-is-closed*` maps to
  `restart-hermes-gateway`; the other two are UptimeKuma `uk:` signatures. A
  provider-side timeout is not that signature, and restarting the gateway is a
  human action regardless.
- **A `hermes_log` signature re-fires on a 24h cooldown, not per occurrence.**
  `upsert_grouped` is called with `flap_threshold=1` and
  `cooldown_hours=REM_HOURS["hermes_log"]` (24). So one card does not mean one
  event, and a quiet week does not mean the signature is gone — check
  `events.last_reminder_at` / `resolved_at` before calling it fixed.
- **A verdict-only item still needs discharging.** `nextAction: issue` lands the
  item in state `verdict`, which carries a 24h deadline to `needs_human`
  (`STATE_DEADLINES`). Left alone it manufactures a "needs a human" card for work
  nobody intends to do. `warden close <event-id> --why "<reason>"` resolves it —
  and closing is not a one-way door: the loop's `reopen_if_needed()` compares an
  occurrence mark rather than `resolved_at`, and `closed` sits in that
  reopen-eligible set, so a genuinely new occurrence reopens the row. Closing a
  self-healed blip is the correct move; leaving it open is the mistake.
- **`~/.hermes/scripts/hermes-cc.sh help` is the authoritative verb list — read
  it rather than trusting a remembered table.** `close <event-id> --why` exists
  and is the verb for step 5; a verb table that omits it will leave items
  stranded on their deadline.

## Discharge or escalate

- **Transient, self-healed, one occurrence** → close it, with the mechanism in
  `--why` (the retry that succeeded and its latency), so the audit log carries
  the reasoning rather than "noise".
- **Recurring, or retries exhausted, or a fallback activated** → treat as real.
  Name the provider-side leg (the IU unified endpoint) and the failure class,
  then route the fix: a code change in `hermes-agent`/`warden` is a dispatch at
  their `investigate` ceiling, so it produces a verdict, not a change — say that
  plainly instead of offering a `run` that cannot land.
- **A defect in Warden's own poller** (the double-count above) is not fixable by
  a dispatch either: `warden` is capped at `investigate` and has no GitHub remote.
  Report it as a finding with the mechanism, and let the owner decide.

## Report shape

Verdict first, one line. Then, per finding, one line each: what it was, why it
looked worse than it was (the mechanism), and what was done about it. Close with
the rest-state (ERRORs since process start, warden `/health`, poller ages) in one
line. Say the real occurrence count, not the card's.
