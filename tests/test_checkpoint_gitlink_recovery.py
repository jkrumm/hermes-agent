#!/usr/bin/env python3
"""Regression suite for the checkpoint stale-gitlink recovery.

The defect: a nested repo is recorded in a project's shadow index as a mode-160000
gitlink while it is healthy.  macOS's ``com.apple.tmp_cleaner`` later removes that
repo's ``.git/HEAD``, ``.git/config`` and ``.git/refs`` but leaves ``.git/objects``
and ``.git/index`` behind, so the directory still reads as a nested-repo boundary
that git cannot resolve.  ``git add -A`` then fails rc=128 for the whole working
tree and ``_take()`` returned ``_step_failed("git-add", err)`` with no recovery —
``_seed_project_index`` read-trees the ref tip back into the index on every
snapshot, so the stale gitlink re-wedged every future checkpoint of that project
forever, one ERROR line per attempt.  ``--ignore-errors`` does not help (still
rc=128) and neither does ``info/exclude`` (the gitlink is already in the index).

``_stage_all_with_gitlink_recovery`` drops the dead gitlinks with
``update-index --force-remove`` and retries once.  The retry is itself the repair:
the drop is a change against the ref tip, so the snapshot proceeds and
``write-tree`` commits a gitlink-free tree that no later read-tree can resurrect.

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_checkpoint_gitlink_recovery.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
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


def make_nested_repo(path: Path, commit=True):
    """A nested repo that git will record as a gitlink.  ``commit=False`` leaves it commitless
    (a valid repo that ``rev-parse --verify HEAD`` cannot answer for — the reason the health
    probe must be ``.git/HEAD`` existence, not a HEAD lookup)."""
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    if not commit:
        (path / "f.txt").write_text("hi\n")
        return
    git(["config", "user.email", "t@t"], path)
    git(["config", "user.name", "t"], path)
    (path / "f.txt").write_text("hi\n")
    git(["add", "-A"], path)
    git(["commit", "-qm", "init"], path)


def gut_dot_git(path: Path):
    """What com.apple.tmp_cleaner leaves: objects/ and index/ survive, HEAD/config/refs do not."""
    for name in ("HEAD", "config"):
        (path / ".git" / name).unlink(missing_ok=True)
    shutil.rmtree(path / ".git" / "refs", ignore_errors=True)


def tree_modes(store: Path, ref: str):
    """{path: mode} for the tree at ``ref``."""
    out = git(["ls-tree", "-r", ref], store).stdout
    return {line.split("\t", 1)[1]: line.split()[0] for line in out.splitlines() if "\t" in line}


class Fixture:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="cp-gitlink-"))
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


# ---------------------------------------------------------------------------
print("stale gitlink recovery")
f = Fixture()
try:
    make_nested_repo(f.work / "sub")
    (f.work / "top.txt").write_text("top\n")
    check("first snapshot succeeds", f.snapshot("first"), True)
    check("nested repo recorded as a gitlink", tree_modes(f.store, f.tip()).get("sub"), "160000")

    gut_dot_git(f.work / "sub")
    check("wedged snapshot recovers", f.snapshot("after tmp_cleaner"), True)
    modes = tree_modes(f.store, f.tip())
    check("gitlink is gone from the new tree", modes.get("sub"), None)
    check("nested repo's file is committed instead", modes.get("sub/f.txt"), "100644")
    check("the rest of the tree still snapshots", modes.get("top.txt"), "100644")

    # The repair is durable: the next snapshot must not re-wedge on a resurrected gitlink.
    (f.work / "top.txt").write_text("changed\n")
    check("subsequent snapshot still succeeds", f.snapshot("later"), True)
    check("gitlink stays gone", tree_modes(f.store, f.tip()).get("sub"), None)
finally:
    f.close()

# ---------------------------------------------------------------------------
print("healthy and submodule-style gitlinks are never dropped")
f = Fixture()
try:
    make_nested_repo(f.work / "sub")
    (f.work / "top.txt").write_text("top\n")
    check("first snapshot succeeds", f.snapshot("first"), True)
    check("gitlink recorded", tree_modes(f.store, f.tip()).get("sub"), "160000")

    (f.work / "top.txt").write_text("changed\n")
    check("healthy gitlink survives a later snapshot", f.snapshot("second"), True)
    check("gitlink still a gitlink", tree_modes(f.store, f.tip()).get("sub"), "160000")

    # A .git FILE is a submodule checkout: live, and must never be force-removed.
    real = f.root / "real-repo"
    make_nested_repo(real)
    shutil.rmtree(f.work / "sub" / ".git")
    (f.work / "sub" / ".git").write_text(f"gitdir: {real / '.git'}\n")
    (f.work / "top.txt").write_text("again\n")
    check("submodule-style snapshot succeeds", f.snapshot("third"), True)
    check("submodule gitlink preserved", tree_modes(f.store, f.tip()).get("sub"), "160000")
finally:
    f.close()

# ---------------------------------------------------------------------------
print("the health probe is filesystem-only and locale-independent")
f = Fixture()
try:
    commitless = f.root / "commitless"
    make_nested_repo(commitless, commit=False)
    check("commitless repo counts as live", cm._gitlink_is_live(str(f.root), "commitless"), True)

    gutted = f.root / "gutted"
    make_nested_repo(gutted)
    gut_dot_git(gutted)
    check("gutted repo counts as dead", cm._gitlink_is_live(str(f.root), "gutted"), False)

    # A git -C probe under the store env answers about the STORE, not the nested repo — the
    # reason _gitlink_is_live never shells out.  Assert the trap is real, so nobody "simplifies"
    # the probe into a rev-parse later.
    store = f.base / "store"
    cm._init_store(store, str(f.root))
    env = cm._git_env(store, str(f.root))
    probe = subprocess.run(["git", "-C", str(gutted), "rev-parse", "--git-dir"],
                           capture_output=True, text=True, env=env)
    check("git -C probe under the store env is useless (rc=0 on a dead repo)", probe.returncode, 0)
finally:
    f.close()

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
