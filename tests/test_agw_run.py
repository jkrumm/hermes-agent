"""Regression suite for scripts/agw_run.py — the agw CLI transport.

Covers: `call` returning parsed JSON and raising on a non-zero exit or unparseable stdout,
`run` resuming a pending (exit 10) run with `agw run wait <runId>` until it ends, never
repeating the submit, the wall-clock timeout naming the run id, a failed run (exit 1, state
on stdout) raising with the run id and the error message, the stderr error envelope used
when stdout carries nothing, the progress line per resume, and the env every call carries
(`AGW_CALLER=hermes`, a PATH that reaches bun). No agw binary: `subprocess.run` is faked.

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_agw_run.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("agw_run", _HERE.parent / "scripts" / "agw_run.py")
assert _spec and _spec.loader, "Failed to load agw_run.py"
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


REAL_SUBPROCESS_RUN = ar.subprocess.run
REAL_TIME = ar.time


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def install(script: list) -> tuple[list[dict], FakeClock]:
    """Fake subprocess.run: each script item is (rc, stdout, stderr) or an exception to raise;
    the last item repeats. Every call advances the fake clock by 110 s (the CLI wait budget)."""
    calls: list[dict] = []
    clock = FakeClock()

    def fake_run(argv, input=None, capture_output=None, text=None, env=None):
        calls.append({"argv": argv, "input": input, "env": env})
        item = script[min(len(calls) - 1, len(script) - 1)]
        clock.now += 110
        if isinstance(item, Exception):
            raise item
        rc, out, err = item
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    ar.subprocess.run = fake_run
    ar.time = SimpleNamespace(monotonic=clock.monotonic)
    return calls, clock


def restore() -> None:
    ar.subprocess.run = REAL_SUBPROCESS_RUN
    ar.time = REAL_TIME


def j(**kw) -> str:
    return json.dumps(kw)


PENDING = (10, j(runId="run-1", workflowId="narrative", status="running"), "")
DONE = (0, j(runId="run-1", workflowId="narrative", status="done", output={"changed": True}, cost=0.1), "")
FAILED = (1, j(runId="run-1", status="failed", error={"kind": "worker", "message": "boom"}), "")


def raised_by(fn) -> "ar.AgwError | None":
    try:
        fn()
    except ar.AgwError as err:
        return err
    return None


print("1. call — parsed JSON, argv ends with --format json, caller and PATH in env")
calls, _ = install([(0, j(data={"x": 1}), "")])
out = ar.call(["agents"])
restore()
check("payload", out, {"data": {"x": 1}})
check("argv", calls[0]["argv"], ["agw", "agents", "--format", "json"])
check("caller", calls[0]["env"]["AGW_CALLER"], "hermes")
check_true("PATH reaches Homebrew bun", "/opt/homebrew/bin" in calls[0]["env"]["PATH"])

print("\n2. call — non-zero exit raises with the CLI's error message")
install([(7, "", j(error={"kind": "network", "message": "host unreachable"}))])
err = raised_by(lambda: ar.call(["agents"]))
restore()
check_true("raised", err is not None)
check_true("message from the stderr envelope", err and "host unreachable" in str(err))

print("\n3. call — exit 0 with unparseable stdout raises")
install([(0, "<html>", "")])
check_true("raised", raised_by(lambda: ar.call(["agents"])) is not None)
restore()

print("\n4. call — agw missing raises AgwError")
install([FileNotFoundError("agw")])
check_true("raised", raised_by(lambda: ar.call(["agents"])) is not None)
restore()

print("\n5. run — done inside the budget: one call, stdin passed through")
calls, _ = install([DONE])
rec = ar.run(["narrative", "--project", "p"], stdin="draft")
restore()
check("status", rec["status"], "done")
check("one call", len(calls), 1)
check("stdin", calls[0]["input"], "draft")

print("\n6. run — pending resumes with `agw run wait <runId>`; the submit is never repeated")
calls, _ = install([PENDING, PENDING, DONE])
err_buf = io.StringIO()
with redirect_stderr(err_buf):
    rec = ar.run(["narrative", "--project", "p"], label="narr")
restore()
check("output", rec["output"], {"changed": True})
check("submit once", [c["argv"][1] for c in calls].count("narrative"), 1)
check("resumes", [c["argv"][1:3] for c in calls[1:]], [["run", "wait"], ["run", "wait"]])
check("resume run id", calls[1]["argv"][3], "run-1")
lines = [ln for ln in err_buf.getvalue().splitlines() if ln.startswith("narr: run run-1")]
check("one progress line per resume", len(lines), 2)

print("\n7. run — wall-clock timeout raises with the run id and the resume command")
install([PENDING])
err = raised_by(lambda: ar.run(["prose-polish"], timeout=200))
restore()
check_true("raised", err is not None)
check("run id attached", err and err.run_id, "run-1")
check_true("names the resume command", err and "agw run wait run-1" in str(err))

print("\n8. run — a failed run raises with the run id and the error message")
install([PENDING, FAILED])
with redirect_stderr(io.StringIO()):
    err = raised_by(lambda: ar.run(["narrative"]))
restore()
check("run id", err and err.run_id, "run-1")
check_true("message", err and "boom" in str(err))

print("\n9. run — pending without a run id raises instead of looping")
calls, _ = install([(10, "", "")])
err = raised_by(lambda: ar.run(["narrative"]))
restore()
check_true("raised", err is not None)
check("no resume attempted", len(calls), 1)

print("\n10. run — exit 0 but status not done (cancelled) raises")
install([(0, j(runId="run-1", status="cancelled"), "")])
check_true("raised", raised_by(lambda: ar.run(["narrative"])) is not None)
restore()

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
