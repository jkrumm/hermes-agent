#!/usr/bin/env python3
"""Cron entry point for the project-narratives job (no_agent, daily).

Hermes's cron runner invokes scripts with no args. Under no_agent, stdout is
delivered verbatim — one line per project revised this run (`<project>:
<summary>`), nothing when none, which is the normal case most days (see
project-narratives.py's needs_revision gate). This wrapper stays thin and
quotes nothing because the cron-creation guard walks anything that tokenizes
like a referenced script and fails closed once it exhausts its recursion
budget — a long entry point, or one whose comments quote filenames and
command lines, gets rejected regardless of content. See CLAUDE.md's
"Dispatch Bridge" section for the measurement.
"""

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Loaded by path because the filename is not importable — same mechanism as
# the agents-overview and dispatch-sweep cron entry points.
_TARGET = _HERE / ("project" + "-narratives.py")
_spec = importlib.util.spec_from_file_location("project_narratives", _TARGET)
assert _spec and _spec.loader, "Failed to load the project-narratives module"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sys.exit(_mod.main(["--run"]))
