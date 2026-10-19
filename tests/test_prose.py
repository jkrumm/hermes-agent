"""Regression suite for scripts/prose.py — the agent-gateway `prose` job client.

Covers: the wall-clock deadline (raises with the job id), a non-object JSON body (clean
ProseError, not an AttributeError), an unwritable --out (exit 1, `prose:` line with the job id,
no partial file), atomic --out on success, GET polls retried on transient failures while the
POST submit is not, a 4xx poll failing at once, and the throttled progress line.

No network: every case replaces the module's `_request` (and `time`) with fakes.

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
from types import SimpleNamespace

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
REAL_REQUEST = pr._request
REAL_TIME = pr.time


class FakeClock:
    """Stands in for the `time` module: sleep() advances monotonic() instead of waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def install(script: list) -> tuple[list[tuple[str, dict | None]], FakeClock]:
    """Replace _request with a scripted fake: each item is a value to return or an exception to
    raise. The last item repeats once the script runs out."""
    calls: list[tuple[str, dict | None]] = []
    clock = FakeClock()

    def fake_request(url: str, body: dict | None = None) -> dict:
        calls.append((url, body))
        item = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    pr._request = fake_request
    pr.time = SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    return calls, clock


def restore() -> None:
    pr._request = REAL_REQUEST
    pr.time = REAL_TIME


def posts(calls) -> int:
    return len([c for c in calls if c[1] is not None])


def gets(calls) -> int:
    return len([c for c in calls if c[1] is None])


SUBMIT = {"ok": True, "job": {"id": "job-1", "status": "pending"}}
RUNNING = {"ok": True, "job": {"id": "job-1", "status": "running"}}
DONE = {
    "ok": True,
    "job": {"id": "job-1", "status": "done", "result": {
        "text": "final text\n", "kept": "rewrite", "usage": {"costUsd": 0.0412},
    }},
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


print("1. happy path — submit once, poll until done, return (job_id, result)")
calls, _ = install([SUBMIT, RUNNING, DONE])
job_id, result = pr.run_prose_job("http://gw", {"text": "x"}, poll_interval=3, timeout=900)
restore()
check("job id", job_id, "job-1")
check("text", result["text"], "final text\n")
check("one POST", posts(calls), 1)
check("two GETs", gets(calls), 2)
check("POST body tool", calls[0][1]["tool"], "prose")

print("\n2. deadline — a job that never finishes raises with the job id")
calls, clock = install([SUBMIT, RUNNING])
raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}, poll_interval=3, timeout=20))
restore()
check_true("raised", raised is not None)
check_true("names the job id", raised and "job-1" in raised)
check_true("names the timeout", raised and "20s" in raised)
check_true("clock stopped at the deadline", clock.now - 1000.0 <= 20.0 + 1e-9)

class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


print("\n3. non-object JSON body from the real _request — clean ProseError end to end")
real_urlopen = pr.urllib.request.urlopen
for name, payload in (("list", b"[1, 2]"), ("null", b"null"), ("string", b'"ok"')):
    pr.urllib.request.urlopen = lambda req, timeout=None, p=payload: FakeResponse(p)
    try:
        raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}))
    except Exception as err:  # noqa: BLE001 — the point is that nothing but ProseError escapes
        raised = f"UNEXPECTED {type(err).__name__}: {err}"
    check_true(f"{name} body -> ProseError", raised is not None and not raised.startswith("UNEXPECTED"))
pr.urllib.request.urlopen = real_urlopen

install([{"ok": True, "job": "nope"}])
raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}))
restore()
check_true("non-object job -> ProseError", raised is not None and "submit refused" in raised)

print("\n3b. real _request — non-object JSON is permanent, non-JSON is transient")


for payload, want in ((b"[1]", "ProseError"), (b"<html>502</html>", "TransientError")):
    pr.urllib.request.urlopen = lambda req, timeout=None, p=payload: FakeResponse(p)
    kind = None
    try:
        REAL_REQUEST("http://gw/x")
    except pr.ProseError as err:
        kind = type(err).__name__
    check(f"{payload!r} -> {want}", kind, want)
pr.urllib.request.urlopen = real_urlopen

print("\n4. GET retried on transient failures, then succeeds")
calls, clock = install([
    SUBMIT,
    pr.TransientError("gateway unreachable: reset"),
    pr.TransientError("gateway HTTP 503: restarting"),
    DONE,
])
job_id, result = pr.run_prose_job("http://gw", {"text": "x"}, poll_interval=3, timeout=900)
restore()
check("got the result", result["kept"], "rewrite")
check("three GETs (2 failed + 1 ok)", gets(calls), 3)
check("one POST", posts(calls), 1)
check("backoff grows", clock.sleeps, [3, 6, 12])

print("\n5. POST not retried — a transient submit failure raises at once")
calls, _ = install([pr.TransientError("gateway unreachable: reset"), SUBMIT, DONE])
raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}))
restore()
check_true("raised", raised is not None)
check("exactly one request made", len(calls), 1)

print("\n6. 4xx on a poll is not retried and names the job id")
calls, _ = install([SUBMIT, pr.ProseError("gateway HTTP 404: job not found")])
raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}))
restore()
check_true("raised with job id", raised is not None and "job-1" in raised)
check("submit + one poll only", len(calls), 2)

print("\n7. failed / cancelled / interrupted jobs raise with the job id and error")
for status in ("failed", "cancelled", "interrupted"):
    install([SUBMIT, {"ok": True, "job": {"id": "job-1", "status": status, "error": "boom"}}])
    raised = raised_by(lambda: pr.run_prose_job("http://gw", {"text": "x"}))
    restore()
    check_true(status, raised is not None and "job-1" in raised and "boom" in raised)

print("\n8. progress line throttled to one per 30 s")
calls, clock = install([SUBMIT] + [RUNNING] * 40 + [DONE])
err_buf = io.StringIO()
with redirect_stderr(err_buf):
    pr.run_prose_job("http://gw", {"text": "x"}, poll_interval=3, timeout=900)
restore()
lines = [ln for ln in err_buf.getvalue().splitlines() if ln.startswith("prose: job")]
check_true("some progress lines", len(lines) >= 2)
check_true("at most one per 30 s", len(lines) <= int(clock.now - 1000.0) // 30)

print("\n9. main — unwritable --out exits 1 with a `prose:` line naming the job id")
install([SUBMIT, DONE])
bad_out = TMP_ROOT / "no-such-dir" / "final.md"
rc, out, err = run_main([str(draft_file()), "--out", str(bad_out)])
restore()
check("exit 1", rc, 1)
check_true("stderr is a prose: line with the job id", err.startswith("prose: ") and "job-1" in err)
check("nothing on stdout", out, "")
check_true("no out file", not bad_out.exists())

print("\n10. main — --out writes atomically, leaves no temp file, prints the summary")
install([SUBMIT, DONE])
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

print("\n11. main — failed job leaves an existing --out untouched, exit 1")
install([SUBMIT, {"ok": True, "job": {"id": "job-1", "status": "failed", "error": "boom"}}])
keep = good_dir / "keep.md"
keep.write_text("previous\n")
rc, out, err = run_main([str(draft_file()), "--out", str(keep)])
restore()
check("exit 1", rc, 1)
check("previous content intact", keep.read_text(), "previous\n")
check_true("error names job id", "job-1" in err)

print("\n12. main — --timeout reaches the deadline; message carries the job id")
install([SUBMIT, RUNNING])
rc, out, err = run_main([str(draft_file()), "--timeout", "10"])
restore()
check("exit 1", rc, 1)
check_true("prose: line with job id and 10s", err.startswith("prose: ") and "job-1" in err and "10s" in err)

print("\n13. summary_line — cost=n/a when the gateway reports no USD figure")
check("n/a", pr.summary_line({"kept": "original", "keptReason": "lost a URL", "usage": {"costUsd": None}}),
      "prose: kept=original (lost a URL) cost=n/a")


shutil.rmtree(TMP_ROOT, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
