"""Pre-run script for the morning briefing cron.

Reads briefing-state.json and emits prompt context to stdout. Hermes cron
appends this output to the prompt so the agent can branch on it.

Source of truth: ~/SourceRoot/dotfiles/hermes/cron/briefing-context.py
Symlink-eligible — this directory mirrors ~/.hermes/cron/ already.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent / "briefing-state.json"
WATCHDOG_SUMMARY = Path(__file__).parent / "watchdog-summary.py"
COVERAGE_SCRIPT = Path(__file__).parent / "briefing-coverage.py"


def _run_subscript(path: Path, timeout: int) -> None:
    """Best-effort: run a sub-script and append its stdout to context output."""
    if not path.exists():
        return
    try:
        res = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if res.returncode == 0 and res.stdout.strip():
            print()
            print(res.stdout.rstrip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def emit_watchdog() -> None:
    _run_subscript(WATCHDOG_SUMMARY, timeout=10)


def emit_coverage() -> None:
    """Append full TickTick + GitHub backlog snapshot."""
    _run_subscript(COVERAGE_SCRIPT, timeout=30)


def main() -> None:
    try:
        state = json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        print("BRIEFING_CITY=Munich")
        print("BRIEFING_SUPPRESSED=false")
        emit_watchdog()
        emit_coverage()
        return
    except json.JSONDecodeError as e:
        print(f"BRIEFING_CITY=Munich", file=sys.stderr)
        print(f"WARNING: state file invalid ({e}) — falling back to defaults", file=sys.stderr)
        print("BRIEFING_CITY=Munich")
        print("BRIEFING_SUPPRESSED=false")
        emit_watchdog()
        emit_coverage()
        return

    city = state.get("city") or "Munich"
    vacation_until = state.get("vacation_until")
    today = datetime.date.today()

    if vacation_until:
        vu = datetime.date.fromisoformat(vacation_until)
        if today <= vu:
            print("BRIEFING_SUPPRESSED=true")
            print(f"BRIEFING_REASON=vacation until {vacation_until}")
            return

    print(f"BRIEFING_CITY={city}")
    print("BRIEFING_SUPPRESSED=false")
    emit_watchdog()
    emit_coverage()


if __name__ == "__main__":
    main()
