"""Cron entry for no_agent mode — emits the Slack body directly.

Hermes's cron runner invokes scripts as `python3 <path>` with no args, so this
thin wrapper imports `watchdog-poll.py`'s `main()` and calls it with the
`--slack-body` flag. Production path: mutates the real watchdog.db (events
advance to notified/reminded) and prints the Slack mrkdwn message to stdout;
empty stdout = silent delivery under `no_agent: true`.

Operator-driven dry-runs should use the underlying script instead:

    python3 ~/.hermes/scripts/watchdog-poll.py --slack-body --dry-run
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "watchdog_poll", _HERE / "watchdog-poll.py",
)
assert _spec and _spec.loader, "Failed to load watchdog-poll.py"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sys.exit(_mod.main(["--slack-body"]))
