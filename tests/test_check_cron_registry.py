"""Regression suite for scripts/check-cron-registry.py's pure functions.

Covers `parse_registry()` (table rows + `## Retired` bullets) and
`compare()` (every mismatch direction `make status`'s cron-registry check
asserts): a live row whose job is actually paused/disabled, a paused row
with a recorded reason (ok) vs. no reason (the CLI-cannot-record sentence),
a retired id still carrying a live job, and a live job entirely absent from
the registry (checked regardless of `enabled`).

No filesystem, no jobs.json on disk — every case builds its `jobs` dict
in-memory and calls `compare()` directly.

Run against the live tree:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_check_cron_registry.py

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "check_cron_registry", _HERE.parent / "scripts" / "check-cron-registry.py",
)
assert _spec and _spec.loader, "Failed to load check-cron-registry.py"
ccr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccr)

failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


def check_true(name: str, cond: bool) -> None:
    check(name, bool(cond), True)


def mk_job(id_: str, name: str, enabled: bool = True, state: str = "scheduled",
           paused_reason: str | None = None) -> dict:
    return {"id": id_, "name": name, "enabled": enabled, "state": state,
            "paused_reason": paused_reason}


# --- parse_registry() -------------------------------------------------------

print("1. parse_registry() — table rows and Retired bullets")
md = """\
| Job id | Name | State |
|-|-|-|
| `cc7900c424a9` | Morning briefing | live |
| `2d38c80e685c` | Evening report | paused (waiting on a fix) |

## Retired

- **`72aa2fb36307` — Agents overview** — retired 2026-09-11.
"""
rows, retired = ccr.parse_registry(md)
check("rows", rows, [("cc7900c424a9", "live"), ("2d38c80e685c", "paused (waiting on a fix)")])
check("retired", retired, ["72aa2fb36307"])

# --- compare() ---------------------------------------------------------------

print("\n2. compare() — all-live rows match live, enabled jobs")
rows = [("cc7900c424a9", "live"), ("8fe7be4985d9", "live")]
jobs = {
    "cc7900c424a9": mk_job("cc7900c424a9", "Morning briefing"),
    "8fe7be4985d9": mk_job("8fe7be4985d9", "Brain drift audit"),
}
check("no errors", ccr.compare(rows, [], jobs), [])

print("\n3. compare() — live row but the job is actually paused")
rows = [("cc7900c424a9", "live")]
jobs = {"cc7900c424a9": mk_job("cc7900c424a9", "Morning briefing", enabled=False, state="paused",
                                paused_reason="testing")}
errors = ccr.compare(rows, [], jobs)
check("one error", len(errors), 1)
check_true("names the job as paused/disabled", "paused/disabled" in errors[0])

print("\n4. compare() — paused row with a recorded reason is fine")
rows = [("cc7900c424a9", "paused (waiting on a fix)")]
jobs = {"cc7900c424a9": mk_job("cc7900c424a9", "Morning briefing", enabled=False, state="paused",
                                paused_reason="waiting on a fix")}
check("no errors", ccr.compare(rows, [], jobs), [])

print("\n5. compare() — paused row with no recorded reason is the CLI-cannot-record sentence")
rows = [("cc7900c424a9", "paused (waiting on a fix)")]
jobs = {"cc7900c424a9": mk_job("cc7900c424a9", "Morning briefing", enabled=False, state="paused",
                                paused_reason=None)}
errors = ccr.compare(rows, [], jobs)
check("one error", len(errors), 1)
check_true("cites the CLI limitation", "hermes cron pause" in errors[0] and "cannot record one" in errors[0])

print("\n6. compare() — retired id still has a live job")
jobs = {"72aa2fb36307": mk_job("72aa2fb36307", "Agents overview")}
errors = ccr.compare([], ["72aa2fb36307"], jobs)
check("one error", len(errors), 1)
check_true("names it retired but still live", "retired" in errors[0] and "still has a live job" in errors[0])

print("\n7. compare() — live job absent from the registry, enabled or not")
rows = [("cc7900c424a9", "live")]
jobs = {
    "cc7900c424a9": mk_job("cc7900c424a9", "Morning briefing"),
    "deadbeef0001": mk_job("deadbeef0001", "Undocumented enabled job"),
    "deadbeef0002": mk_job("deadbeef0002", "Undocumented disabled job", enabled=False),
}
errors = ccr.compare(rows, [], jobs)
check("two errors, one per undocumented job regardless of enabled", len(errors), 2)
check_true("enabled undocumented job flagged", any("deadbeef0001" in e for e in errors))
check_true("disabled undocumented job flagged too", any("deadbeef0002" in e for e in errors))

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all cases as expected")
