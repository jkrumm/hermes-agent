---
name: checkpoint-store-forensics
description: "Use when a checkpoint_manager ERROR or store alert fires."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, checkpoints, shadow-git, store, rollback, gc, triage, warden, hermes-log]
    related_skills: [hermes-log-alert-forensics, hermes-gateway, warden]
---

# Checkpoint store forensics

The shadow git store behind `write_file`/`patch`/`terminal` snapshots. Every
`tools.checkpoint_manager` ERROR and every store-size line in Hermes's logs is a
symptom of one of a small number of store states. Diagnose the state first; only
one of the causes is a data defect worth repairing.

`hermes-log-alert-forensics` owns the `hermes_log:*` alert family and the
discharge/escalate step for the Warden item; this skill owns the store itself.

## Layout

`~/.hermes/checkpoints/store` — one bare repo shared by every project, so git
dedupes blobs across them.

| Path | What |
|-|-|
| `refs/hermes/<hash16>` | one ref per project, `<hash16>` = `sha256(abs_workdir)[:16]` |
| `indexes/<hash16>` | that project's index file (passed as `GIT_INDEX_FILE`) |
| `projects/<hash16>.json` | `{workdir, created_at, last_touch, workdir_parent_dev, workdir_parent_ino}` |
| `info/exclude` | `DEFAULT_EXCLUDES`, written once at store init |
| `objects/pack/` | the shared pack — this is where the bytes are |

Every git call runs with `GIT_DIR=<store> GIT_WORK_TREE=<workdir>
GIT_INDEX_FILE=<store>/indexes/<hash16>` and the inherited `GIT_*` vars stripped.
Reproduce any store operation by exporting exactly those three.

## Procedure

1. **Slice the log at the current process start** (`hermes-gateway` Rule 0) before
   counting anything. `errors.log` and `gateway.error.log` span restarts.
2. **Read the stderr tail and classify** — see *Three causes* below. This decides
   whether you are repairing data, reporting a race, or doing nothing.
3. **Count honestly.** Each gateway-originated line is written to *both* tailed
   files, so a card's `×N` is roughly double the real event count. Grep each file.
4. **Check the store's own state**: `du -sm store`, then the cap/floor check below.
5. **Verify through the real entry point**, never a bare `add -A`:
   `CheckpointManager(enabled=True, max_snapshots=50).ensure_checkpoint(workdir, reason=…)`
   from `~/.hermes/hermes-agent` with its venv. A bare `git add -A` can pass while
   the manager still refuses (file-count guard, oversize drop, unchanged-index skip),
   and a skip logged as `working directory not found` is the workdir-teardown case,
   not a store defect.
6. **Discharge or escalate** via `hermes-cc.sh close <event-id> --why "<mechanism>"`.

## Three causes of `git add -A (rc=128)` — triage by the stderr tail

- `'<path>/.git' nicht als Git-Repository erkannt` → **dead gitlink** (data defect).
  A nested repo is recorded in the index as a mode-160000 gitlink while healthy;
  macOS's `com.apple.tmp_cleaner` (daily, `-atime/-mtime/-ctime +3`) then deletes that
  repo's `.git/HEAD`, `.git/config` and `.git/refs` while leaving `.git/objects` and
  `.git/index`. The directory still reads as a nested-repo boundary git cannot resolve,
  so `add -A` over the whole tree fails forever, one ERROR per file-mutating tool call.
  `_seed_project_index` read-trees the ref tip back in on every snapshot, so it never
  self-heals. Repair order: (1) quarantine or remove the gutted `.git` (nothing is lost
  — no HEAD, no config); (2) `update-index --force-remove <path>` the dead gitlink from
  the project's index; (3) commit a gitlink-free tree to `refs/hermes/<hash16>`
  (read-tree the ref, force-remove, `add -A`, write-tree, `commit-tree -p <old>`,
  `update-ref`) so no later read-tree resurrects it. A **gone** directory needs no
  recovery (`add -A` returns 0 and drops the gitlink itself); `--ignore-errors` does
  **not** help (still rc=128) and neither does `info/exclude` (the gitlink is already
  in the index). **Discriminate with `git -C <dir> rev-parse --verify HEAD`, never by
  looking for a `.git` directory** — a linked worktree's `.git` is a *file*
  (`gitdir: …/.git/worktrees/<name>`) and is perfectly healthy, so `add -A` returns 0
  with the gitlink still in the index (observed: five such gitlinks in the `/tmp` ref,
  all resolving). Only a `.git` that exists but cannot resolve HEAD is the dead one.
- `'<name>/' hat keinen Commit ausgecheckt` / `does not have a commit checked out`
  → **commitless nested repo** (a *healthy* `git init` with no commit yet), NOT the
  dead-gitlink case above and NOT transient. The two are easy to conflate because both
  name a nested directory; the tell is the stderr: this shape carries **no `.git`
  substring**, so `_stage_all_with_gitlink_recovery`'s recovery branch never fires and
  its single retry re-runs the identical `add -A` and fails identically — one ERROR, not
  a self-heal. `info/exclude` cannot help either: the boundary is a directory git refuses
  to descend into, not a tracked path, so an ignore rule never gets consulted. Verified
  live by reproducing it (`git init` in `$T/nested`, then `add -A` over `$T`: rc=128,
  retry rc=128). It self-limits only when the offending directory is removed — the
  observed instance was an agent's diagnostic scratch dir under `/private/tmp` (the
  `/tmp` project), which was gone minutes later, after which `add -A` over `/private/tmp`
  returned 0. **Nothing to repair and nothing to dispatch**: confirm the directory is
  gone or remove it, re-run `add -A` on the project's workdir, and close the item.
- `Konnte Datei <store>/objects/<xx>/<sha> nicht schreiben: No such file or directory`
  → **gc race**. A concurrent `git gc --prune=now` removed the loose-object fanout dir
  between git's stat and its write. Tool calls run on a daemon thread pool, so two
  snapshots and a gc interleave **in one process**, and a per-project index is not a gc
  reachability root — so a snapshot's staged-but-uncommitted blobs are also prunable
  between `add -A` and `write-tree`. **Fixed in code** (2026-09-15): one reentrant
  `_STORE_LOCK` now covers every store-touching git call and the whole `_take` sequence.
  If you see this line again, the patch is missing — check `make patch-check`, do not
  re-diagnose the mechanism.
- `Unable to create '<store>/indexes/<hash>.lock': File exists` → **cross-process
  collision**, not a stale lock. Two *processes* snapshotting the same project: git's own
  index lock is held by the other one. The in-process `_STORE_LOCK` cannot see it.
  **Fixed in code**: a cross-process file lock (`<store>/.hermes-store.lock`, holder PID,
  stale-PID reaping) held for the same span. Measured pristine 15/24 concurrent rounds
  fail, patched 0/24. Do **not** delete the `.lock` file by hand — it is either live or
  already reaped; check `find <store> -name '*.lock'` is empty and move on.
- `konnte '<path>' nicht lesen: No such file or directory` → **workdir torn down
  mid-`add -A`** (an agent worktree removed while a session was still running), or a file
  deleted mid-walk by another process. `git add -A` walks the tree and *then* reads each
  entry, so a file that disappears in between fails the whole add. **Fixed in code**: the
  staging entry point retries once on any transient failure, and the retry succeeds
  (verified by reproducing the race against a 6000-file tree). Transient and self-limiting;
  nothing to repair, nothing lost.
- `Warnung: Füge eingebettetes Repository hinzu: <dir>` → **not a failure.** That is an
  advice warning on stderr with rc=128 only because something *else* in the same add
  failed; the message names a nested repo that was added as a gitlink, which is normal.
  Read the rest of the stderr for the real cause before chasing the named directory.
  **This is the trap that cost a dispatch**: `add -A` prints advice *before* the error, and
  Warden derives its `hermes_log:*` signature from the **first** line — so the 13:59:12
  failure was filed as this warning while the cause (`Fehler: '<dir>/' hat keinen Commit
  ausgecheckt`, a commitless nested repo) sat sixteen lines down. The logger now keeps line
  1 verbatim (it is the signature) and summarizes the tail, and the retry quotes the real
  cause. When triaging this shape from an *older* log line, read the whole stderr block —
  never the first line alone.

A `tools.checkpoint_manager` ERROR names a **path, not the project**: the project is
resolved by `get_working_dir_for_path` (nearest ancestor carrying a project marker),
so one stray `/tmp/package.json` makes all of `/tmp` a single project. Apply any fix to
the project's index, never to the child path in the message.

## The size cap is unreachable — and that is the amplifier

`Checkpoint store exceeded N MB (actual M MB) — pruning oldest` repeating is **not**
pruning working. `_enforce_size_cap` runs after every snapshot and
`_shrink_store_to_cap` drops the oldest commit per ref — but `_drop_oldest_commit`
returns False once `_ref_commit_count <= 1`, so the moment every ref sits on the
1-commit floor the loop breaks immediately and the store stays over cap forever.

Check the floor:

```bash
cd ~/.hermes/checkpoints/store
git for-each-ref --format='%(refname:short) %(objectname:short)' refs/hermes
for r in $(git for-each-ref --format='%(refname)' refs/hermes); do echo "$r $(git rev-list --count $r)"; done
```

All-ones is the floor. The cost is not the size — it is that `_gc_store` then runs
`reflog expire --expire=now --all` + `gc --prune=now` on a multi-hundred-MB pack on
**every** checkpoint (13 firings in one day, ~2.5 s each), which is what made the gc
race frequent rather than rare. The race itself is now fixed by the store lock, so a
repeating `exceeded` line is **not** an incident on its own — it is a capacity finding.
**Do not "fix" it by raising `max_total_size_mb`** — the bytes are real, so a higher
cap only silences the symptom.

## Attribute the bytes before proposing cleanup

```bash
# reachable bytes per ref
for h in $(git for-each-ref --format='%(objectname:short)' refs/hermes); do :; done
REF=refs/hermes/<hash16>
git rev-list --objects $REF | awk '{print $1}' \
  | git cat-file --batch-check='%(objecttype) %(objectsize)' | awk '$1=="blob"{s+=$2}END{print s/1048576" MB"}'
# the big paths themselves
git ls-tree -r --long $REF | sort -k4 -n | tail -30
```

The recurring hog is a `/tmp` project: `DEFAULT_EXCLUDES` has no rule for browser
profile dirs (`chrome-profile/`, `component_crx_cache/`, `OnDeviceHeadSuggestModel/`)
or for multi-MB screenshots / `.db` / `.mp3`, and `_MAX_FILES` (50 000) does not trip at
~13 000 files, so the whole tree is staged. Deleting any of it drops rollback history —
report the attribution and let the owner decide; never prune a ref to hit a size cap on
your own initiative.

**`claude-501/` is excluded as of 2026-09-15** (Claude Code's session state and task
outputs; 1925 tracked paths / ~32 MB in the `/tmp` ref before the fix, and the source of
the mid-walk delete race). Two facts that made it invisible for so long, both worth
checking when a pattern seems not to apply:

- **`info/exclude` was written once, at store init.** A store created before a pattern
  existed never picked it up — the live file still carried the pre-`claude-501/` list.
  It is now rewritten from `DEFAULT_EXCLUDES` whenever it has moved on.
- **`git add -A` honours `info/exclude` only for paths that are *not yet* in the index**,
  and `_seed_project_index` read-trees the ref tip back in on every snapshot — so a path
  committed before its pattern existed stays tracked forever. Tracked paths the store's
  own exclude file matches are now force-removed after the seed. Verify with
  `git ls-files --cached -i -X <store>/info/exclude` (with `GIT_DIR`/`GIT_WORK_TREE`/
  `GIT_INDEX_FILE` set for the project) — **not** `--exclude-standard`, which would also
  apply the project's own `.gitignore`.

## Two lines from this family are usually ONE investigation

Different stderr tails, same subsystem, same repo → one dispatch. Close the sibling
item as a duplicate of the one carrying the in-flight job
(`warden close <id> --why "duplicate of <id>: same root cause…"`) instead of firing a
second dispatch: a second episode burns budget and yields two verdicts that cannot both
be acted on. Check `/items/<id>` for an existing `dispatch_job` before dispatching.

## A fix on disk is not a fix in the running gateway

`tools/checkpoint_manager.py` is imported **once** by the gateway process
(`agent/agent_init.py` → `from tools.checkpoint_manager import CheckpointManager`), so editing it
does nothing until that process restarts. Python has no hot reload here, and the module's own log
lines are the tell: after a patch lands, the next gateway snapshot should print the new markers
(`Dropped N now-excluded path(s)…`, `Retrying checkpoint staging…`). If it prints neither, the
running process is stale.

Prove it without restarting anything — make the new code's effect observable and see whether it
happens:

```bash
# Remove a line the new code is supposed to rewrite, then let the gateway snapshot.
cp ~/.hermes/checkpoints/store/info/exclude /tmp/exclude.bak
grep -v '^claude-501/$' /tmp/exclude.bak > ~/.hermes/checkpoints/store/info/exclude
# (touch a file in a checkpointed project so a snapshot fires, or wait for the next tool call)
sleep 5; grep -c '^claude-501/$' ~/.hermes/checkpoints/store/info/exclude   # 0 = stale module
cp /tmp/exclude.bak ~/.hermes/checkpoints/store/info/exclude                # always restore
```

A `0` there means the fix is inert. **Do not use `.hermes-store.lock` as the staleness tell** — the lock file is created *and unlinked* inside each critical section (`os.unlink` in the `finally`), so it is absent whenever no snapshot is in flight, on both the pre- and post-fix code. Its absence proves nothing; the exclude rewrite is the observable tell. **The restart is a human action** — `hermes gateway restart`
is guard-blocked from inside the gateway (SIGTERM would kill the command), and `ask-human.sh` is
blocked too when its arguments contain the phrase. Hand over the one command; do not look for a
way around the guard. Until the restart, the pre-fix behaviour continues (the gateway re-adds
`claude-501/` to the `/tmp` ref on its next snapshot — a CLI snapshot drops it again, so the store
oscillates rather than degrades).

## Report shape

Verdict first, one line: real-or-transient and whether anything is still broken. Then
one line per finding — what it was, the mechanism, what was done. Name the store state
(ref floor, store size vs cap, gc frequency), not just the log line. Close with the
rest-state: ERRORs since the slice point, `git fsck` result, a live `ensure_checkpoint`
verdict, Warden `/health`. Say the real occurrence count, not the card's.

**A transient failure that is now fixed in code is still worth reporting as fixed, not
as noise.** The three shapes above each have a patch; say which one fired, that the
retry/lock handled it, and that the store needs nothing. `git fsck` reporting
`dangling blob` entries is **normal** after a ref rewrite (`_prune` / `_shrink_store_to_cap`
drop commits, so their blobs dangle until the next gc) — it is not corruption and not a
finding; only a `missing`/`broken` line is.
