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
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "watchdog_poll", _HERE / "watchdog-poll.py",
)
assert _spec and _spec.loader, "Failed to load watchdog-poll.py"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

rc = _mod.main(["--slack-body"])

# Self-health heartbeat: ping the UptimeKuma push monitor only on a clean poll, so
# a crash, hang, or non-zero exit trips the "Watchdog last successful run" alert.
# Best-effort and stdout-silent (any output would corrupt the no_agent Slack body).
if rc == 0:
    push_url = _mod.load_env().get("UPTIME_PUSH_WATCHDOG")
    if push_url:
        # uptime.jkrumm.com sits behind Cloudflare, which 403s the default
        # Python-urllib User-Agent — send a curl-like UA so the heartbeat lands.
        req = urllib.request.Request(push_url, headers={"User-Agent": "curl/8.7.1"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception:
            pass

sys.exit(rc)
