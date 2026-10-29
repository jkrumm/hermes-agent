"""Regression suite for scripts/prose.py — the `agw prose-polish` client.

Covers: the happy path (argv, stdin draft, run id + output returned), a failed or timed-out
run raising ProseError with the run id, a done run without a text result, the agw argv built
from the CLI flags, an unwritable --out (exit 1, `prose:` line with the run id, no partial
file), atomic --out on success, a failed run leaving an existing --out untouched, and the
summary line mapping agw's `reason`/`cost`.

No agw binary: every case replaces `agw_run.run` with a fake.

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_prose.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("prose", _HERE.parent / "scripts" / "prose.py")
assert _spec and _spec.loader, "Failed to load prose.py"
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


TMP_ROOT = Path(tempfile.mkdtemp(prefix="prose-test-"))
REAL_RUN = pr.agw_run.run
AgwError = pr.agw_run.AgwError


def install(result) -> list[dict]:
    """Replace agw_run.run with a fake returning `result` (or raising it when an exception)."""
    calls: list[dict] = []

    def fake_run(args, *, stdin=None, timeout=None, label="agw"):
        calls.append({"args": args, "stdin": stdin, "timeout": timeout})
        if isinstance(result, Exception):
            raise result
        return result

    pr.agw_run.run = fake_run
    return calls


def restore() -> None:
    pr.agw_run.run = REAL_RUN


DONE = {
    "runId": "run-1", "workflowId": "prose-polish", "status": "done", "cost": 0.0412,
    "output": {"text": "final text\n", "kept": "rewrite", "cost": 0.0412, "lint": {"before": 1, "after": 0, "findings": []}},
}


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = pr.main(argv)
    return rc, out.getvalue(), err.getvalue()


def draft_file() -> Path:
    path = TMP_ROOT / "draft.md"
    path.write_text("A draft paragraph.\n")
    return path


def raised_by(fn) -> str | None:
    try:
        fn()
    except pr.ProseError as err:
        return str(err)
    return None


print("1. happy path — one agw call, draft on stdin, (run_id, output) returned")
calls = install(DONE)
run_id, result = pr.run_prose(["--medium", "vault"], "the draft", timeout=900)
restore()
check("run id", run_id, "run-1")
check("text", result["text"], "final text\n")
check("one call", len(calls), 1)
check("workflow + args", calls[0]["args"], ["prose-polish", "--medium", "vault"])
check("draft on stdin, not argv", calls[0]["stdin"], "the draft")
check("timeout reaches the transport", calls[0]["timeout"], 900)

print("\n2. AgwError becomes ProseError and carries the run id")
install(AgwError("run run-1 not finished after 20s", run_id="run-1"))
raised = raised_by(lambda: pr.run_prose([], "x", timeout=20))
restore()
check_true("raised", raised is not None)
check_true("names the run id", raised and "run-1" in raised)
check_true("names the timeout", raised and "20s" in raised)

print("\n3. AgwError without a run id (agw unreachable) still raises ProseError")
install(AgwError("agw not runnable: boom"))
raised = raised_by(lambda: pr.run_prose([], "x"))
restore()
check_true("raised", raised is not None and "boom" in raised)

print("\n4. a done run without a text result raises with the run id")
for bad in ({"runId": "run-1", "status": "done", "output": None},
            {"runId": "run-1", "status": "done", "output": {"kept": "rewrite"}}):
    install(bad)
    raised = raised_by(lambda: pr.run_prose([], "x"))
    restore()
    check_true("raised with run id", raised is not None and "run-1" in raised)

print("\n5. main — flags map onto the agw argv")
calls = install(DONE)
ctx = TMP_ROOT / "ctx.md"
ctx.write_text("outline\n")
rc, out, err = run_main([str(draft_file()), "--medium", "docs", "--language", "de",
                         "--context", str(ctx), "--no-verdict-first"])
restore()
check("exit 0", rc, 0)
check("argv", calls[0]["args"], ["prose-polish", "--medium", "docs", "--no-verdict-first",
                                 "--language", "de", "--context", "outline\n"])
check("stdin is the draft", calls[0]["stdin"], "A draft paragraph.\n")
check("text to stdout", out, "final text\n")

print("\n6. main — default medium vault, no optional flags")
calls = install(DONE)
run_main([str(draft_file())])
restore()
check("argv", calls[0]["args"], ["prose-polish", "--medium", "vault"])

print("\n7. main — unwritable --out exits 1 with a `prose:` line naming the run id")
install(DONE)
bad_out = TMP_ROOT / "no-such-dir" / "final.md"
rc, out, err = run_main([str(draft_file()), "--out", str(bad_out)])
restore()
check("exit 1", rc, 1)
check_true("stderr is a prose: line with the run id", err.startswith("prose: ") and "run-1" in err)
check("nothing on stdout", out, "")
check_true("no out file", not bad_out.exists())

print("\n8. main — --out writes atomically, leaves no temp file, prints the summary")
install(DONE)
good_dir = TMP_ROOT / "good"
good_dir.mkdir()
good_out = good_dir / "final.md"
rc, out, err = run_main([str(draft_file()), "--out", str(good_out), "--medium", "chat"])
restore()
check("exit 0", rc, 0)
check("file content", good_out.read_text(), "final text\n")
check("only the out file in the directory", [p.name for p in good_dir.iterdir()], ["final.md"])
check("summary line", err.strip(), "prose: kept=rewrite cost=$0.041")
check("stdout empty with --out", out, "")

print("\n9. main — failed run leaves an existing --out untouched, exit 1")
install(AgwError("agw prose-polish exit 1: boom", run_id="run-1"))
keep = good_dir / "keep.md"
keep.write_text("previous\n")
rc, out, err = run_main([str(draft_file()), "--out", str(keep)])
restore()
check("exit 1", rc, 1)
check("previous content intact", keep.read_text(), "previous\n")
check_true("error names run id", "run-1" in err)

print("\n10. main — empty input exits 1 without calling agw")
calls = install(DONE)
empty = TMP_ROOT / "empty.md"
empty.write_text("  \n")
rc, out, err = run_main([str(empty)])
restore()
check("exit 1", rc, 1)
check("agw never called", calls, [])

print("\n11. summary_line — agw's `reason` and `cost` keys; cost=n/a when unpriced")
check("n/a", pr.summary_line({"kept": "original", "reason": "lost a URL", "cost": None}),
      "prose: kept=original (lost a URL) cost=n/a")
check("priced rewrite", pr.summary_line({"kept": "rewrite", "cost": 0.0352}), "prose: kept=rewrite cost=$0.035")


shutil.rmtree(TMP_ROOT, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
