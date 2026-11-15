#!/usr/bin/env python3
"""scripts/check-seats.py `compare()`: config.yaml seats against agw's hermes.* routes.

In-memory fixtures, no agw call. Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_check_seats.py
"""
import copy
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_seats", REPO / "scripts" / "check-seats.py")
check_seats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_seats)

BASE = "${ANTHROPIC_BASE_URL}"


def route(model, effort):
    return {"wire": "anthropic", "model": model, "effort": effort,
            "fallback": {"wire": "iu-openai", "model": "gpt-6-luna", "effort": "low"}}


def aux(model, effort):
    return {"model": model, "reasoning_effort": effort, "api_mode": "anthropic_messages", "base_url": BASE}


ROUTES = {
    "hermes.brain": route("claude-haiku-5-5", "high"),
    "hermes.compress": route("claude-haiku-5-5", "high"),
    "hermes.title": route("claude-haiku-5-5", "none"),
    "hermes.approval": route("claude-haiku-5-5", "none"),
    "hermes.vision": route("claude-sonnet-5-5", "medium"),
}
CONFIG = {
    "model": {"default": "claude-haiku-5-5", "api_mode": "anthropic_messages", "base_url": BASE},
    "agent": {"reasoning_effort": "high"},
    "auxiliary": {
        "compression": aux("claude-haiku-5-5", "high"),
        "title_generation": aux("claude-haiku-5-5", "none"),
        "approval": aux("claude-haiku-5-5", "none"),
        "vision": aux("claude-sonnet-5-5", "medium"),
    },
}

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
        return
    failures.append(label)
    print(f"  FAIL {label}: got {got!r}, want {want!r}")


def mutated(fn):
    config = copy.deepcopy(CONFIG)
    fn(config)
    return check_seats.compare(ROUTES, config)


check("matching config has no errors (the route's GPT fallback is ignored)", check_seats.compare(ROUTES, CONFIG), [])
check("brain effort drift", len(mutated(lambda c: c["agent"].update(reasoning_effort="medium"))), 1)
check("tier change on a route is caught",
      len(check_seats.compare({**ROUTES, "hermes.compress": route("claude-sonnet-5-5", "high")}, CONFIG)), 1)
check("approval model drift", len(mutated(lambda c: c["auxiliary"]["approval"].update(model="claude-sonnet-5-5"))), 1)
check("vision effort missing", len(mutated(lambda c: c["auxiliary"]["vision"].pop("reasoning_effort"))), 1)
check("lane off the Anthropic leg", len(mutated(lambda c: c["auxiliary"]["title_generation"].update(
    api_mode="chat_completions", base_url="${OPENAI_BASE_URL}"))), 2)
check("missing route", len(check_seats.compare({}, CONFIG)), 5)
check("a non-Anthropic route is refused",
      len(check_seats.compare({**ROUTES, "hermes.brain": {**ROUTES["hermes.brain"], "wire": "iu-openai"}}, CONFIG)), 1)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
