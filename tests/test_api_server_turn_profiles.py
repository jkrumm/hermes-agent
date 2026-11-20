#!/usr/bin/env python3
"""The api_server turn-profile helpers (patches/api-server-turn-profiles.patch): the Iris system message
selects a profile, the iris skill is preloaded into the prompt, the preload is byte-identical across
sessions (prompt cache), and the API admission still applies both the preload and the profile's effort.

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_api_server_turn_profiles.py
"""
import pathlib
import sys

import yaml

HERMES = pathlib.Path.home() / ".hermes" / "hermes-agent"
sys.path.insert(0, str(HERMES))

from gateway.platforms.api_server import _apply_turn_profile, _match_turn_profile, _turn_profile_prompt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
config = yaml.safe_load((ROOT / "config.yaml").read_text())
IRIS = (
    "This turn comes from Iris: the message is a transcript of the owner's voice memo. "
    "Load skill_view('iris') and follow it."
)
failures = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


profile = _match_turn_profile(config, IRIS)
check(profile.get("skills") == ["iris"], "the Iris system message selects the iris profile")
check(profile.get("reasoning_effort") == "high", "the Iris profile pins an effort (bench verdict: high)")
check(_match_turn_profile(config, IRIS + "\nThe owner picked: Chat.") == profile, "a legacy hint line still matches")
check(_match_turn_profile(config, "You are a helpful assistant.") == {}, "another system message matches nothing")
check(_match_turn_profile(config, None) == {}, "no system message matches nothing")
check(_match_turn_profile({}, IRIS) == {}, "a config without profiles matches nothing")

first = _turn_profile_prompt(profile, IRIS, "session-a")
second = _turn_profile_prompt(profile, IRIS, "session-b")
check(first == second, "the preloaded prompt is byte-identical across sessions")
rewritten = first.rsplit("\n\n", 1)[-1]
check(rewritten.startswith("This turn comes from Iris"), "the caller's system message comes last")
check("Load skill_view('iris')" not in rewritten and "already loaded in your system prompt" in rewritten, "the skill_view instruction is rewritten")
check("name: iris" in first and "Decide — first match wins" in first, "the iris skill body is in the prompt")
skill_bytes = len((ROOT / "skills" / "iris" / "SKILL.md").read_bytes())
check(skill_bytes < 9000, f"the preloaded iris SKILL.md stays lean ({skill_bytes} bytes; artifacts and note filing live in references/)")
check(_turn_profile_prompt({"skills": ["no-such-skill-2517"]}, IRIS, "s") == IRIS, "a missing skill leaves the message as sent")
check(_turn_profile_prompt({}, IRIS, "s") == IRIS, "a profile without skills leaves the message as sent")

settings = {"ephemeral_system_prompt": IRIS, "model_options": None}
_apply_turn_profile(settings, config, "session-a")
check(settings["ephemeral_system_prompt"] == _turn_profile_prompt(profile, IRIS, "session-a"),
      "an admission's settings get the preloaded, rewritten system message")
check(settings["model_options"] == {"reasoning_effort": "high"}, "an admission without an effort gets the profile's")
own = {"ephemeral_system_prompt": IRIS, "model_options": {"reasoning_effort": "low", "service_tier": "x"}}
_apply_turn_profile(own, config, "session-a")
check(own["model_options"] == {"reasoning_effort": "low", "service_tier": "x"}, "a request that names its own effort keeps it")
other = {"ephemeral_system_prompt": "You are a helpful assistant.", "model_options": None}
_apply_turn_profile(other, config, "session-a")
check(other == {"ephemeral_system_prompt": "You are a helpful assistant.", "model_options": None}, "another system message is left alone")

import inspect  # noqa: E402

from gateway import session_api_turn  # noqa: E402

admit_src = inspect.getsource(session_api_turn.admit_api_steps)
check(
    0 <= admit_src.find("_apply_turn_profile(settings,") < admit_src.find("payload = json.loads("),
    "admit_api_steps applies the profile before the settings are frozen into the payload",
)

if failures:
    print("FAIL")
    sys.exit(1)
print("OK")
