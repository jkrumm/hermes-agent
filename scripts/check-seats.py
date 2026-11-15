#!/usr/bin/env python3
"""Assert config.yaml's model seats against agent-workflows' route table.

The five Hermes seats live in agw's route table (`agw routes`, ids `hermes.*`); config.yaml
carries them as literals because Hermes reads it at startup and nothing renders it. This is
the drift check: a tier change in agw fails here until config.yaml follows and the gateway
restarts. The routes' own `fallback` field is ignored on purpose — Hermes is Claude-only, the
gateway does the fallback.

Run with the Hermes venv (it has PyYAML):  scripts/check-seats.py [config.yaml]
Exit 0 = every seat matches (or agw is absent: skipped, said so), 1 = drift or unreadable.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ANTHROPIC_BASE = "${ANTHROPIC_BASE_URL}"

# route id -> (where the seat lives in config.yaml, description)
SEATS = {
    "hermes.brain": "model",
    "hermes.compress": "auxiliary.compression",
    "hermes.title": "auxiliary.title_generation",
    "hermes.approval": "auxiliary.approval",
    "hermes.vision": "auxiliary.vision",
}


def _get(config: dict, path: str) -> dict:
    node = config
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def compare(routes: dict, config: dict) -> list[str]:
    """One sentence per mismatch; empty means every seat agrees with the route table."""
    errors: list[str] = []
    for route_id, path in SEATS.items():
        route = routes.get(route_id)
        if not route:
            errors.append(f"{route_id}: not in `agw routes`")
            continue
        if route.get("wire") != "anthropic":
            errors.append(f"{route_id}: wire is {route.get('wire')!r}, Hermes is Claude-only (anthropic)")
            continue
        section = _get(config, path)
        label = f"{route_id} ({path})"
        model = section.get("default") if path == "model" else section.get("model")
        if model != route["model"]:
            errors.append(f"{label}: model {model!r}, route says {route['model']!r}")
        effort = _get(config, "agent").get("reasoning_effort") if path == "model" else section.get("reasoning_effort")
        if effort != route.get("effort"):
            errors.append(f"{label}: effort {effort!r}, route says {route.get('effort')!r}")
        if section.get("api_mode") != "anthropic_messages":
            errors.append(f"{label}: api_mode {section.get('api_mode')!r}, want 'anthropic_messages'")
        if section.get("base_url") != ANTHROPIC_BASE:
            errors.append(f"{label}: base_url {section.get('base_url')!r}, want {ANTHROPIC_BASE!r}")
    return errors


def main(argv: list[str]) -> int:
    import yaml

    config_path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "config.yaml"
    if shutil.which("agw") is None:
        print("    ✓ model seats [skipped: agw not on PATH]")
        return 0
    run = subprocess.run(["agw", "routes", "--format", "json"], capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        print(f"    ✗ model seats [agw routes exited {run.returncode}: {run.stderr.strip()[:200]}]")
        return 1
    try:
        routes = json.loads(run.stdout)["routes"]
        config = yaml.safe_load(config_path.read_text())
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"    ✗ model seats [unreadable: {exc}]")
        return 1
    errors = compare(routes, config)
    for error in errors:
        print(f"    ✗ model seats: {error}")
    if errors:
        print("      fix config.yaml to the route table (or the other way round in agw), then restart the gateway")
        return 1
    print(f"    ✓ model seats ({len(SEATS)} hermes.* routes match config.yaml)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
