"""Pre-run script for the morning briefing cron.

Reads briefing-state.json and emits prompt context to stdout. Hermes cron
appends this output to the prompt so the agent can branch on it.

Source of truth: ~/SourceRoot/claude-local/hermes/cron/briefing-context.py
Symlink-eligible — this directory mirrors ~/.hermes/cron/ already.
"""

import datetime
import json
import sys
from pathlib import Path

STATE_FILE = Path(__file__).parent / "briefing-state.json"


def main() -> None:
    try:
        state = json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        print("BRIEFING_CITY=Munich")
        print("BRIEFING_SUPPRESSED=false")
        return
    except json.JSONDecodeError as e:
        print(f"BRIEFING_CITY=Munich", file=sys.stderr)
        print(f"WARNING: state file invalid ({e}) — falling back to defaults", file=sys.stderr)
        print("BRIEFING_CITY=Munich")
        print("BRIEFING_SUPPRESSED=false")
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


if __name__ == "__main__":
    main()
