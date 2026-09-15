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
print("store access is serialized by one reentrant lock")
f = Fixture()
try:
    (f.work / "top.txt").write_text("top\n")
    check("lock exists", isinstance(cm._STORE_LOCK, type(threading.RLock())), True)

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
finally:
    f.close()

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
