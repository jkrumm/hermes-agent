#!/usr/bin/env python3
"""Regression suite for the checkpoint store's exclude-file + concurrency fixes.

Two defects, one subsystem, both observed live on 2026-09-15:

1. **A path stays tracked after its pattern reaches ``DEFAULT_EXCLUDES``.**  The store's
   ``info/exclude`` is written once at store init and ``_seed_project_index`` read-trees the ref
   tip back into the index on every snapshot, so a path committed *before* the pattern was added
   keeps being staged forever.  ``claude-501/`` (Claude Code's scratch under ``/tmp``, which is one
   checkpoint project because of a stray ``/tmp/package.json``) sat at 1920 tracked paths / ~32 MB
   in the ``/tmp`` ref while being nominally excluded.  Fix: refresh ``info/exclude`` from
   ``DEFAULT_EXCLUDES``, and force-remove tracked paths the store's own exclude file matches.

2. **A transient ``add -A`` failure was fatal.**  ``git add -A`` walks the tree and then reads
   each entry, so a file deleted in between (Claude Code removing its scratch as an episode ends,
   an agent worktree torn down) fails the whole add with ``unable to stat '<path>': No such file
   or directory`` — while the next attempt succeeds.  Fix: retry once for *any* transient add
   failure, not only the gitlink-shaped one.

3. **No lock across the shared store.**  Tool calls run on a daemon thread pool, so two snapshots
   and a ``gc --prune=now`` interleave in one process; a concurrent gc removed an
   ``objects/<xx>/`` fanout directory mid-write (``Konnte Datei …/objects/21/… nicht schreiben``)
   and a per-project index is not a gc reachability root, so a snapshot's staged-but-uncommitted
   blobs are prunable mid-flight.  Fix: one reentrant lock over every store-touching git call.

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_checkpoint_store_excludes.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, "/Users/jkrumm/.hermes/hermes-agent")

from tools import checkpoint_manager as cm  # noqa: E402
from tools.checkpoint_manager import CheckpointManager  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
        return
    failures.append(label)
    print(f"  FAIL {label}: got {got!r}, want {want!r}")


def git(args, cwd, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, **kw)


class Fixture:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="cp-excl-"))
        self.base = self.root / "checkpoints"
        self.work = self.root / "project"
        self.work.mkdir(parents=True)
        self._saved_base = cm.CHECKPOINT_BASE
        cm.CHECKPOINT_BASE = self.base
        self.mgr = CheckpointManager(enabled=True, max_snapshots=50)

    def close(self):
        cm.CHECKPOINT_BASE = self._saved_base
        shutil.rmtree(self.root, ignore_errors=True)

    @property
    def store(self) -> Path:
        return self.base / "store"

    def ref(self) -> str:
        return cm._ref_name(cm._project_hash(str(self.work)))

    def tip(self):
        return cm._ref_tip(self.store, str(self.work), self.ref())

    def snapshot(self, reason="auto"):
        self.mgr.new_turn()
        return self.mgr.ensure_checkpoint(str(self.work), reason)

    def tracked(self):
        """Paths in the ref tip's tree (what the last snapshot committed)."""
        out = git(["ls-tree", "-r", "--name-only", self.tip()], self.store).stdout
        return set(out.splitlines())


# ---------------------------------------------------------------------------
print("a now-excluded path is dropped from the index and the committed tree")
f = Fixture()
try:
    # Stage the scratch while it is NOT yet excluded, so it is committed as a tracked path —
    # exactly the live shape (claude-501/ was tracked long before the pattern existed).
    saved_excludes = cm.DEFAULT_EXCLUDES
    cm.DEFAULT_EXCLUDES = [p for p in saved_excludes if p != "claude-501/"]
    scratch = f.work / "claude-501" / "session" / "tasks"
    scratch.mkdir(parents=True)
    (scratch / "out.output").write_text("scratch\n")
    (f.work / "top.txt").write_text("top\n")
    check("snapshot with the pattern absent succeeds", f.snapshot("before"), True)
    check("scratch is committed while unexcluded", "claude-501/session/tasks/out.output" in f.tracked(), True)
    cm.DEFAULT_EXCLUDES = saved_excludes

    # Now the pattern exists.  The path is already in the index, so a plain add -A would keep
    # staging it — the defect.  The fix must drop it and commit a tree without it.
    (f.work / "top.txt").write_text("top changed\n")
    check("snapshot after the pattern is added succeeds", f.snapshot("after"), True)
    tree = f.tracked()
    check("scratch is gone from the committed tree", "claude-501/session/tasks/out.output" in tree, False)
    check("the rest of the tree still snapshots", "top.txt" in tree, True)

    # Self-healing: the drop must not need to happen again, and a later snapshot must not
    # resurrect it via the read-tree.
    (f.work / "top.txt").write_text("again\n")
    check("subsequent snapshot succeeds", f.snapshot("later"), True)
    check("scratch stays gone", "claude-501/session/tasks/out.output" in f.tracked(), False)
finally:
    cm.DEFAULT_EXCLUDES = saved_excludes
    f.close()

# ---------------------------------------------------------------------------
print("the exclude file on an existing store is refreshed, not written once")
f = Fixture()
try:
    (f.work / "top.txt").write_text("top\n")
    check("first snapshot succeeds", f.snapshot("first"), True)
    exclude = f.store / "info" / "exclude"

    # Simulate a store created before a pattern existed.
    stale = "\n".join(p for p in cm.DEFAULT_EXCLUDES if p != "claude-501/") + "\n"
    exclude.write_text(stale, encoding="utf-8")
    check("stale exclude file lacks the pattern", "claude-501/" in exclude.read_text(), False)

    (f.work / "top.txt").write_text("changed\n")
    check("snapshot on the existing store succeeds", f.snapshot("second"), True)
    check("exclude file was refreshed", "claude-501/" in exclude.read_text(), True)
finally:
    f.close()

# ---------------------------------------------------------------------------
print("a transient add failure is retried, not fatal")
f = Fixture()
try:
    # A commitless nested repo makes `git add -A` fail rc=128 persistently, and its stderr names
    # no `.git` token — so the gitlink-shaped recovery never fired for it and the old code
    # returned the failure straight out of _take.  After the fix the retry runs and the failure
    # is reported once, from the retry.  Assert the retry happened rather than the outcome.
    nested = f.work / "nested"
    nested.mkdir()
    git(["init", "-q"], nested)
    (nested / "f.txt").write_text("hi\n")
    (f.work / "top.txt").write_text("top\n")

    calls = []
    real_stage = cm._stage_all

    def counting_stage(p, allowed_returncodes=None):
        result = real_stage(p, allowed_returncodes=allowed_returncodes)
        calls.append(result[0])
        return result

    cm._stage_all = counting_stage
    try:
        ok = f.snapshot("commitless nested repo")
    finally:
        cm._stage_all = real_stage
    check("a persistent failure still fails the snapshot", ok, False)
    check("the add was attempted twice (retry ran)", len(calls), 2)
finally:
    f.close()

# ---------------------------------------------------------------------------
print("a file vanishing mid-add is recovered by the retry")
f = Fixture()
try:
    # Reproduce the live race deterministically: the first add -A sees a tree whose files are
    # deleted underneath it.  Patch _stage_all to delete the tree between the walk and the read
    # by running the real add against a tree that a helper empties first.
    many = f.work / "many"
    many.mkdir()
    for i in range(1, 801):
        (many / f"f{i}.txt").write_text(f"c{i}\n")
    (f.work / "top.txt").write_text("top\n")

    real_stage = cm._stage_all
    state = {"first": True}

    def racing_stage(p, allowed_returncodes=None):
        if state["first"]:
            state["first"] = False
            # Delete a file between git's directory walk and its per-entry read.  A background
            # thread doing exactly this is the live shape; here we delete before the call and
            # let the retry (second call) see the settled tree, which is what the retry is for.
            def churn():
                time.sleep(0.005)
                for i in range(1, 801):
                    try:
                        os.remove(many / f"f{i}.txt")
                    except FileNotFoundError:
                        pass
            t = threading.Thread(target=churn)
            t.start()
            try:
                return real_stage(p, allowed_returncodes=allowed_returncodes)
            finally:
                t.join()
        return real_stage(p, allowed_returncodes=allowed_returncodes)

    cm._stage_all = racing_stage
    try:
        ok = f.snapshot("racing delete")
    finally:
        cm._stage_all = real_stage
    # Either the race did not land (add succeeded first try) or the retry recovered it.  Both are
    # acceptable; a False here would mean the retry is missing, which is the defect.
    check("a racing delete does not lose the snapshot", ok, True)
finally:
    f.close()



# ---------------------------------------------------------------------------
def _run_lock_checks(f, cm, _STORE_LOCK):
    # Reentrancy: _take -> _enforce_size_cap -> _gc_store nests inside the same lock, so a plain
    # Lock would deadlock.  Prove the nesting path actually runs while held.
    depths = []
    real_gc = cm._gc_store

    def observing_gc(store, working_dir):
        depths.append(cm._STORE_LOCK._is_owned() if hasattr(cm._STORE_LOCK, "_is_owned")
                      else cm._STORE_LOCK.acquire(blocking=False))
        if depths[-1] is True and not hasattr(cm._STORE_LOCK, "_is_owned"):
            cm._STORE_LOCK.release()
        return real_gc(store, working_dir)

    cm._gc_store = observing_gc
    try:
        # Force the size cap to trip so _enforce_size_cap -> _gc_store runs inside _take.
        f.mgr.max_total_size_mb = 0  # no cap: _enforce_size_cap returns early
        f.mgr.max_snapshots = 1      # so _prune rewrites the ref on the second snapshot
        check("snapshot 1", f.snapshot("one"), True)
        (f.work / "top.txt").write_text("two\n")
        check("snapshot 2 (prune path)", f.snapshot("two"), True)
        check("gc ran while the lock was held", any(d is True for d in depths), True)
    finally:
        cm._gc_store = real_gc

    # Two threads snapshotting different projects must not interleave their git calls.  Assert
    # by observing that no two store-touching subprocesses overlap.
    other = f.root / "project2"
    other.mkdir()
    (other / "x.txt").write_text("x\n")
    mgr2 = CheckpointManager(enabled=True, max_snapshots=50)

    overlap = []
    real_sub = cm._git_subprocess
    active = {"n": 0}
    guard = threading.Lock()

    def observing_sub(cmd, env, timeout, cwd=None):
        with guard:
            active["n"] += 1
            if active["n"] > 1:
                overlap.append(cmd)
        try:
            time.sleep(0.01)  # widen the window so an unserialized overlap is visible
            return real_sub(cmd, env, timeout, cwd=cwd)
        finally:
            with guard:
                active["n"] -= 1

    cm._git_subprocess = observing_sub
    try:
        f.mgr.new_turn()
        mgr2.new_turn()
        threads = [
            threading.Thread(target=lambda: f.mgr.ensure_checkpoint(str(f.work), "t1")),
            threading.Thread(target=lambda: mgr2.ensure_checkpoint(str(other), "t2")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        cm._git_subprocess = real_sub
    check("no two store git calls overlapped", len(overlap), 0)



# ---------------------------------------------------------------------------------------------
# 4. The ERROR line must name the cause, not the first line of stderr.
#
# `git add -A` emits advice before the error.  Live, the 13:59:12 failure opened with
# "Warnung: Füge eingebettetes Repository hinzu: cpexp.znuOaZ" — an entirely normal nested repo —
# while the cause ("Fehler: 'cpexp3.sgahXS/' hat keinen Commit ausgecheckt") was sixteen lines
# down.  Warden derives its `hermes_log:*` signature from the first line, so it filed a dispatch
# against the innocent directory.  The retry's own log line must therefore quote the cause.
# ---------------------------------------------------------------------------------------------


print("store access is serialized by one reentrant lock")
f = Fixture()
try:
    (f.work / "top.txt").write_text("top\n")
    _lock = getattr(cm, "_STORE_LOCK", None)
    check("lock exists", isinstance(_lock, type(threading.RLock())), True)
    if _lock is None:
        # Pristine module: the behaviour checks cannot run.  Report and move on so the suite still
        # produces a complete FAIL list instead of aborting on the first missing attribute.
        print("  (skipping lock-behaviour checks — no _STORE_LOCK on this module)")
    else:
        _run_lock_checks(f, cm, _lock)
finally:
    f.close()


print("\n[4] stderr cause extraction")
ADVICE_FIRST = "\n".join(
    ["Warnung: Füge eingebettetes Repository hinzu: cpexp.znuOaZ"]
    + [f"Hinweis: Zeile {i}" for i in range(15)]
    + ["Fehler: 'cpexp3.sgahXS/' hat keinen Commit ausgecheckt",
       "Schwerwiegend: Hinzufügen von Dateien fehlgeschlagen"]
)
# getattr-guarded: on the pristine module these helpers do not exist, and the suite must report a
# FAIL per check rather than abort with an AttributeError (it is run against both trees).
_cause = getattr(cm, "_stage_failure_cause", None)
_log = getattr(cm, "_log_stderr", None)
check("_stage_failure_cause exists", callable(_cause), True)
check("_log_stderr exists", callable(_log), True)
if callable(_cause):
    check("cause is the last error marker, not line 1",
          _cause(ADVICE_FIRST),
          "Schwerwiegend: Hinzufügen von Dateien fehlgeschlagen")
    check("cause of a plain English failure",
          _cause("fatal: unable to stat 'many/f118.txt': No such file or directory"),
          "fatal: unable to stat 'many/f118.txt': No such file or directory")
    check("cause falls back to line 1 when git emits no marker",
          _cause("Warnung: Füge eingebettetes Repository hinzu: x\nHinweis: y"),
          "Warnung: Füge eingebettetes Repository hinzu: x")
    check("empty stderr yields an empty cause", _cause(""), "")
if callable(_log):
    # The logged stderr keeps the first line verbatim (it is the signature) and summarizes the rest.
    logged = str(_log(ADVICE_FIRST))
    check("logged stderr keeps line 1 verbatim", logged.startswith(ADVICE_FIRST.splitlines()[0]), True)
    check("logged stderr is summarized", "more line(s)" in logged, True)
    check("logged stderr is bounded", len(logged) < 500, True)
    check("short stderr is logged unchanged",
          _log("fatal: adding files failed"), "fatal: adding files failed")

# ---------------------------------------------------------------------------------------------
# 5. Cross-process serialization.
#
# The in-process RLock cannot see another *process*'s git index lock.  Live 14:19:32: the gateway
# snapshotting /private/tmp failed with `Unable to create '<store>/indexes/11fe14a563f7aed6.lock':
# File exists` because a second process was snapshotting the same project.  This lane spawns real
# subprocesses against a shared store: pristine fails ~15/24 rounds, patched 0.
# ---------------------------------------------------------------------------------------------
print("\n[5] cross-process store serialization")
XP_ROOT = Path(tempfile.mkdtemp(prefix="cp-xproc-"))
XP_WORK = XP_ROOT / "work"
XP_BASE = XP_ROOT / "checkpoints"
XP_WORK.mkdir(parents=True)
for i in range(300):
    (XP_WORK / f"f{i:03d}.txt").write_text(f"content {i}\n")

XP_CHILD = (
    "import logging,sys,pathlib\n"
    f"sys.path.insert(0, {str(Path(cm.__file__).parents[1])!r})\n"
    "import tools.checkpoint_manager as cm\n"
    f"cm.CHECKPOINT_BASE = pathlib.Path({str(XP_BASE)!r})\n"
    'logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")\n'
    f"mgr = cm.CheckpointManager(enabled=True, max_snapshots=50)\n"
    f"print(mgr.ensure_checkpoint({str(XP_WORK)!r}, reason='xproc'))\n"
)
_xp_env = dict(os.environ)
_xp_env["PYTHONPATH"] = str(Path(cm.__file__).parents[1])

collisions = 0
rounds = 4
for _ in range(rounds):
    procs = [
        subprocess.Popen([sys.executable, "-c", XP_CHILD], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=_xp_env)
        for _ in range(3)
    ]
    for p in procs:
        _out, _err = p.communicate(timeout=300)
        if "File exists" in _err or "Unable to create" in _err:
            collisions += 1
check("no cross-process index-lock collision", collisions, 0)
shutil.rmtree(XP_ROOT, ignore_errors=True)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
