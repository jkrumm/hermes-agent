#!/usr/bin/env python3
"""Cron entry point for alert triage (no_agent, every 10 min).

Hermes's cron runner invokes scripts with no args. Under no_agent, stdout is
delivered verbatim — triage.py's own run() never prints to stdout in
production (it posts/updates cards directly via Slack's API and logs
diagnostics to stderr), so this normally delivers nothing. This wrapper stays
thin and quotes nothing because the cron-creation guard walks anything that
tokenizes like a referenced script and fails closed once it exhausts its
recursion budget — a long entry point, or one whose comments quote filenames
and command lines, gets rejected regardless of content. See CLAUDE.md's
"Dispatch Bridge" section for the measurement.
"""

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Loaded by path because the filename is not importable — same mechanism as
# the watchdog, dispatch-sweep, agents-overview and project-narratives cron
# entry points.
_TARGET = _HERE / "triage.py"
_spec = importlib.util.spec_from_file_location("triage", _TARGET)
assert _spec and _spec.loader, "Failed to load the triage module"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sys.exit(_mod.main([]))
