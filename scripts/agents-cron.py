#!/usr/bin/env python3
"""Cron entry point for the agents-overview digest (no_agent, every 30 min).

Hermes's cron runner invokes scripts with no args. Under no_agent an empty
stdout means silent delivery, which is the normal case here: nothing is
worth a ping most cycles (see agents-overview.py's render_slack). This
wrapper stays thin and quotes nothing because the cron-creation guard walks
anything that tokenizes like a referenced script and fails closed once it
exhausts its recursion budget — a long entry point, or one whose comments
quote filenames and command lines, gets rejected regardless of content. See
CLAUDE.md's "Dispatch Bridge" section for the measurement.
"""

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Loaded by path because the filename is not importable — same mechanism as
# narratives-cron.py's own load of project-narratives.py.
_TARGET = _HERE / ("agents" + "-overview.py")
_spec = importlib.util.spec_from_file_location("agents_overview", _TARGET)
assert _spec and _spec.loader, "Failed to load the agents-overview module"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sys.exit(_mod.main(["--slack-body"]))
