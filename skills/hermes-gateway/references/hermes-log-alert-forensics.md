# Hermes log alert forensics

_Use when a Hermes log ERROR line shows up in `#alerts` or while reading the logs._

A Hermes ERROR line reaches you through `#alerts` or a log read. There is no poller, card or
ledger item behind it any more (warden retired 2026-10-27); this skill is the triage for the
line itself — deciding whether it is a real fault, and then reporting or filing it.

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
2. **Locate the line in `errors.log` and `gateway.error.log`** and count honestly: a
   gateway-originated line is written to both, so a naive count is roughly double.
3. **Read forward from the timestamp, ~10–60s.** Look for the retry's own
   success line (`API call #<n+1>: … latency=…`), a `Retrying API call in …s`
   warning, or a `Fallback activated` line. That window is where the verdict is.
4. **Classify.** Self-healed in one retry with no fallback and no user-visible
   loss → transient; report it as such. A repeat, an
exhausted retry (`API call failed after 3 retries`), or a fallback activation →
real; escalate.
5. **Report or escalate** (last section).

## Pitfalls

- **A gateway-originated line is written to BOTH `logs/errors.log` and
  `logs/gateway.error.log`, byte-identical**, so grepping both files roughly doubles the real
  occurrence count. Grep the line in each file and compare before quoting a number, and report
  the real count.
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
  do **not** set `cron.model_drift_guard: false`, which is the brake itself. Once the
  pin is verified the guard cannot re-fire against a pinned axis.
- **`… 404 - No suitable backend server found for model '<something>-does-not-exist'` is a
  deliberate fallback probe, and the ERROR it writes is a false positive — but you must
  recognise both of its shapes.** A post-rollout check overrides the model to a sentinel id
  ending in `-does-not-exist` so the endpoint is *guaranteed* to 404 — that 404 is the probe's
  expected result, and the fallback then serves the turn. Hermes retries `api_max_retries`
  times, so **one probe writes exactly three ERROR lines**:
  they are the probe's own retry attempts, not three incidents. Nothing filters this shape any more, so
  a line carrying it is the probe unless the model id is one that is actually configured — read
  the model id in the line before deciding; a genuine 404 for the configured model is real.
  Triage it the cheap way: `grep -a "<session-id>" agent.log` for the `Fallback activated:
  <sentinel> → <model>` line and the successful `API call #1` after it. An investigate episode
  here can only restate the probe, so do not dispatch one.
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
  `request_timeout_seconds` override in `config.yaml` — and that patch has since LANDED
  (`patches/stream-error-transient-openai-classes.patch`, `make patch-check` green), so the live
  handler already classifies both openai classes as transient. Triage consequence: an ERROR-level
  `Streaming failed before delivery` can no longer come from the running code — compare the line
  against the current process start and expect the producer to be a process that booted before the
  patch. The usual trigger is a host reboot: the network stack tears down during shutdown, outbound
  name lookups fail (`httpcore.ConnectError: [Errno 8] nodename nor servname provided`), the
  in-flight stream dies with it, and the dying process's ERROR is what the log shows. Cheap
  cross-check that the box really rebooted: `last reboot` shows a shutdown/reboot pair and
  `kern.boottime` sits minutes before the current gateway start.
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
- **The Requesty 503 family (`[Requesty-Global StatusCode: ServiceUnavailable|InternalServerError]`)
  is an UPSTREAM router blip on the IU leg, and a `Fallback activated: <brain> → gpt-6-luna`
  line after it is the ladder WORKING, not a hermes-agent defect.** Read forward:
  `API call failed (attempt 1/3)` → `Retrying API call in …s` → `(attempt 2/3)` → `Fallback
  activated` → `API call #1: model=gpt-6-luna … latency=…` — the turn was served; the only cost
  is that it ran with no reasoning effort while tools were attached (the accepted 503-avoidance
  tradeoff, see `hermes-gateway`). So "fallback activated → real" does not mean "escalate"
  here: there is no code change to dispatch (agent-gateway's dispatch policy caps `hermes-agent` at
  `investigate`, a verdict can only restate the log) and no issue worth filing. Report it naming the upstream leg.
  `ServiceUnavailable` and `InternalServerError` lines close together are ONE incident.
## Report or escalate

- **Transient, self-healed, one occurrence** → say so in the reply, with the mechanism (the
  retry that succeeded and its latency) rather than "noise". Nothing to file.
- **Recurring, or retries exhausted, or a fallback activated** → treat as real.
  Name the provider-side leg (the IU unified endpoint) and the failure class, then route
  the fix: `agw-legacy dispatch --repo hermes-agent` runs an `investigate` episode (the
  repo's ceiling), so it produces a verdict, not a change — say that plainly. For the
  `_handle_stream_error` classification gap, make the anchor a GitHub issue in
  `jkrumm/hermes-agent` (issues enabled, no label) — and then **hand-land the fix**
  rather than relaying the nag. Recipe: *Hand-landing the patch* below. Only the gateway
  restart stays the owner's.

## Hand-landing the patch

The `investigate` ceiling (agent-gateway's dispatch policy) bounds **dispatches** — unattended
episodes whose briefs are attacker-influenceable, aimed at the repo that *is* the control
plane. It is not a claim that the fix cannot be made: there is simply no episode lane
(agent-gateway refuses an `implement` on `hermes-agent`), so the
fix lands by hand. Six steps are yours, one never is.

1. **Edit the live checkout** (`~/.hermes/hermes-agent/…` — the tree the gateway
   imports from), marking the hunk `# LOCAL MODIFICATION (patches/<name>.patch)`,
   the comment every patch in the set carries.
2. **Exercise the real function before trusting it.** `venv/bin/python3 -m
   py_compile <file>`, then call the patched method with a fake `self` — this
   family's classification is reachable with no network. A compile check alone
   does not show the new type actually lands in the transient set.
3. **Generate the patch from the diff**: `git -C ~/.hermes/hermes-agent diff --
   <file> > ~/SourceRoot/hermes-agent/patches/<name>.patch` (the repo's own
   documented regeneration command). The live checkout is pristine upstream plus
   the applied patches, so a scoped `git diff -- <file>` is exactly your change.
4. **Record it in three places**: the `AGENTS.md` § *Local Modifications to
   Upstream* table (a blank line between rows breaks the table), the restart-list
   paragraph directly below it when the file is imported at startup, and the
   per-file bullet in `docs/patches.md`.
5. **Prove both directions.** `make patch-check` in `~/SourceRoot/hermes-agent`
   must count it (`N/N applied`), and forward-applicability must be shown against
   pristine upstream — `git -C ~/.hermes/hermes-agent show HEAD:<file>` into a temp
   dir, `patch -p1 --dry-run` there — or the next `hermes update` silently drops it.
6. **Commit only your three files**, never the repo's unrelated dirty state, and
   use `git commit -F <file>`: a message in a double-quoted shell string executes
   its backticks and silently loses the code fragments.
7. **Never restart the gateway.** The change is inert until the owner restarts
   it — say exactly that, and report the patch, the commit and the restart still
   outstanding.
