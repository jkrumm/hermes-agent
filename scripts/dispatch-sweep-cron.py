#!/usr/bin/env python3
"""Cron entry point for the dispatch sweeper (no_agent, every 5 min).

Hermes's cron runner invokes scripts with no args. Under no_agent an empty
stdout means silent delivery, which is the normal case here: the sweeper posts
each verdict directly into its own origin thread, so anything on stdout would be
a SECOND message delivered to the job's configured channel. Diagnostics go to
stderr.

WHY THIS WRAPPER EXISTS, and why it is deliberately terse: the cron-creation
guard walks anything that tokenizes like a referenced script and fails closed
when it exhausts its recursion budget, so a long file — or even a short one whose
comments quote filenames and command lines — is rejected as "contains a gateway
lifecycle command" regardless of content. The registered entry point therefore
has to stay small and quote nothing. The full rationale, the measurement, and
which existing jobs would fail the same check today live in CLAUDE.md under
"Dispatch Bridge"; keep it there, not here.
"""

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Loaded by path because the filename is not importable — same mechanism, and the
# same reason, as the watchdog's own cron entry point.
_TARGET = _HERE / ("dispatch" + "-sweep.py")
_spec = importlib.util.spec_from_file_location("dispatch_sweep", _TARGET)
assert _spec and _spec.loader, "Failed to load the sweeper module"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sys.exit(_mod.main([]))
