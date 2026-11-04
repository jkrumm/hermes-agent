#!/usr/bin/env python3
"""The local inference gateway wiring in config.yaml, read through Hermes' own resolvers.

Pins what a value check cannot see: the affinity header per route (looked up by URL, so a
leg without an entry silently sends none), the door token under every name, and context
windows that never reach a probe on the loopback address.

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_gateway_provider.py
``HERMES_SRC`` points it at another checkout.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.environ.get("HERMES_SRC", os.path.expanduser("~/.hermes/hermes-agent")))

import yaml  # noqa: E402

from agent import model_metadata  # noqa: E402
from agent.secret_sources.command import _parse_dotenv_map  # noqa: E402
from hermes_cli.config import _expand_env_vars  # noqa: E402
from hermes_cli.config_providers import (  # noqa: E402
    get_compatible_custom_providers,
    get_custom_provider_context_length,
    get_custom_provider_session_affinity_header,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
OPENAI = "http://127.0.0.1:7794/openai/v1"
ANTHROPIC = "http://127.0.0.1:7794/anthropic"
DOOR_NAMES = {
    "AUDIO_DOOR_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HERMES_CUSTOM_CUSTOM_API_KEY",
    "HERMES_CUSTOM_UNIFIED_ENDPOINT_MAIN_APP_IU_IT_ORG_API_KEY",
}

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
        return
    failures.append(label)
    print(f"  FAIL {label}: got {got!r}, want {want!r}")


def tpl_values():
    values = {}
    for line in (REPO / ".env.tpl").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


tpl = tpl_values()
raw_config = yaml.safe_load((REPO / "config.yaml").read_text())
with mock.patch.dict(os.environ, {
    "OPENAI_BASE_URL": tpl["OPENAI_BASE_URL"],
    "ANTHROPIC_BASE_URL": tpl["ANTHROPIC_BASE_URL"],
    "OPENAI_API_KEY": "door",
    "ANTHROPIC_API_KEY": "door",
}):
    config = _expand_env_vars(raw_config)

print(".env.tpl")
check("openai leg", tpl["OPENAI_BASE_URL"], OPENAI)
check("anthropic leg has no /v1", tpl["ANTHROPIC_BASE_URL"], ANTHROPIC)
check("no gateway key is an op ref", DOOR_NAMES & set(tpl), set())

print("every call lands on the gateway")
for slot, section in (
    ("model", config["model"]),
    ("fallback", config["fallback_providers"][0]),
    *((f"auxiliary.{k}", v) for k, v in config["auxiliary"].items() if v.get("provider") == "custom"),
):
    check(f"{slot} base", section["base_url"] in (OPENAI, ANTHROPIC), True)

print("affinity header, per route")
entries = get_compatible_custom_providers(config)
gateway_entries = [e for e in entries if e.get("base_url") in (OPENAI, ANTHROPIC)]
check("three gateway entries (providers.custom, legacy list, anthropic)", len(gateway_entries), 3)
check("no entry off the gateway", len(entries), len(gateway_entries))
for entry in gateway_entries:
    check(f"{entry.get('name')} declares it", entry.get("session_affinity_header"), "x-agw-session")
for url in (OPENAI, OPENAI + "/", ANTHROPIC):
    check(f"route {url}", get_custom_provider_session_affinity_header(url, config=config), "x-agw-session")
legacy_only = {"custom_providers": config["custom_providers"]}
check("the legacy list alone carries it",
      get_custom_provider_session_affinity_header(OPENAI, config=legacy_only), "x-agw-session")
dict_only = {"providers": config["providers"]}
check("the providers dict alone carries it",
      get_custom_provider_session_affinity_header(OPENAI, config=dict_only), "x-agw-session")

print("brain on the Anthropic leg, selected by provider name")
# `provider: custom` resolves to providers.custom (the OpenAI leg) and ignores model.base_url:
# the brain would silently run through the chat-completions shim, uncached by a native leg.
check("brain provider", config["model"]["provider"], "gateway-anthropic")
check("brain wire", config["model"]["api_mode"], "anthropic_messages")
check("brain base", config["model"]["base_url"], ANTHROPIC)
check("brain model", config["model"]["default"], "claude-haiku-5-5")
check("cache ttl follows the pacing of the source", config["prompt_caching"]["cache_ttl"], "auto")
check("compaction fires late, inside the 1M window with room for the summary pass", 500000 <= config["compression"]["threshold_tokens"] <= 750000, True)

print("vision and approval on the Anthropic leg")
for lane, model in (("vision", "claude-sonnet-5-5"), ("approval", "claude-haiku-5-5"),
                    ("compression", "claude-haiku-5-5"), ("title_generation", "claude-haiku-5-5")):
    section = config["auxiliary"][lane]
    check(f"{lane} model", section["model"], model)
    check(f"{lane} wire", section["api_mode"], "anthropic_messages")
    check(f"{lane} base", section["base_url"], ANTHROPIC)

print("context windows never reach a loopback probe")
# Same order get_model_context_length reads them: an explicit pin first, then the route's
# models table, so these slots cannot fall through to /models, /api/show or the catalog.
PINS = (
    ("brain", raw_config["model"], "claude-haiku-5-5", ANTHROPIC, 1000000),
    ("fallback", raw_config["fallback_providers"][0], "gpt-6-luna", OPENAI, 850000),
    ("compression", raw_config["auxiliary"]["compression"], "claude-haiku-5-5", ANTHROPIC, 1000000),
    ("title", raw_config["auxiliary"]["title_generation"], "claude-haiku-5-5", ANTHROPIC, 1000000),
    ("approval", raw_config["auxiliary"]["approval"], "claude-haiku-5-5", ANTHROPIC, 1000000),
)
for slot, section, model, url, window in PINS:
    check(f"{slot} pin", section.get("context_length"), window)
    check(f"{slot} route table", get_custom_provider_context_length(model, url, entries), window)
    probe = mock.Mock(side_effect=AssertionError("probed"))
    with mock.patch.object(model_metadata, "_query_local_context_length", probe), \
            mock.patch.object(model_metadata, "detect_local_server_type", probe), \
            mock.patch.object(model_metadata, "fetch_endpoint_model_metadata", probe):
        got = model_metadata.get_model_context_length(
            model, base_url=url, api_key="door", config_context_length=section.get("context_length"),
            provider="custom", custom_providers=entries,
        )
    check(f"{slot} resolves without a probe", got, window)

print("secrets.command")
COMMAND = raw_config["secrets"]["command"]["command"]
check("survives config expansion", _expand_env_vars(COMMAND), COMMAND)
TOKEN = "door-token-with=equals"


def run_helper(door_tokens):
    with tempfile.TemporaryDirectory() as home:
        root = pathlib.Path(home)
        shim = root / ".local/bin/secrets-run"
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/bin/sh\nprintf \"export SLACK_BOT_TOKEN='xoxb'\\n\"\n")
        shim.chmod(0o755)
        if door_tokens is not None:
            tokens = root / ".agent-workflows/data/door-tokens"
            tokens.parent.mkdir(parents=True)
            tokens.write_text(door_tokens)
        return subprocess.run(
            ["/bin/sh", "-c", COMMAND], env={"HOME": home, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True,
        )


out = run_helper(f"agw=other\nhermes={TOKEN}\noc=another\n")
parsed = _parse_dotenv_map(out.stdout)
check("exit 0", out.returncode, 0)
check("every name gets the token", {k: v for k, v in parsed.items() if k in DOOR_NAMES},
      dict.fromkeys(DOOR_NAMES, TOKEN))
check("the secrets-run half survives", parsed.get("SLACK_BOT_TOKEN"), "xoxb")
check("no other caller's token", set(parsed), DOOR_NAMES | {"SLACK_BOT_TOKEN"})

for label, tokens in (("missing file", None), ("no hermes line", "agw=other\n")):
    out = run_helper(tokens)
    parsed = _parse_dotenv_map(out.stdout)
    check(f"{label}: exit 0", out.returncode, 0)
    check(f"{label}: names stay unset, nothing empty", set(parsed), {"SLACK_BOT_TOKEN"})

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
