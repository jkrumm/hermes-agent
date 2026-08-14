#!/usr/bin/env python3
"""Regression suite for the two reasoning-effort patches.

* ``patches/runtime-provider-iu-responses-api.patch`` — routes the IU
  endpoint's OpenAI leg onto the Responses API, the only surface there that
  takes function tools and a reasoning effort in the same request.
* ``patches/transport-iu-reasoning-effort.patch`` — reconciles the effort
  upstream's ``CustomProfile`` puts on the wire with what each leg of the
  gateway actually accepts, for anything still on chat_completions (the
  Anthropic fallback, the auxiliaries).

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_iu_reasoning_effort.py
"""
import sys

sys.path.insert(0, "/Users/jkrumm/.hermes/hermes-agent")

from agent.transports.chat_completions import (  # noqa: E402
    ChatCompletionsTransport,
    _apply_iu_reasoning_effort,
)

IU = "https://unified-endpoint-main.app.iu-it.org/openai/v1"
LUNA = "gpt-5.6-luna"
CLAUDE = "claude-sonnet-4-6-eu"

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
        return
    failures.append(label)
    print(f"  FAIL {label}: got {got!r}, want {want!r}")


TOOLS = [{"type": "function", "function": {"name": "t", "parameters": {}}}]


def effort_for(model, cfg, base_url=IU, tools=None):
    kwargs = {"model": model}
    if tools:
        kwargs["tools"] = tools
    out = _apply_iu_reasoning_effort(
        kwargs, model, {"base_url": base_url, "reasoning_config": cfg},
    )
    return out.get("reasoning_effort")


print("emitted effort per model family")
for effort in ("none", "low", "medium", "high", "xhigh"):
    check(f"luna {effort}", effort_for(LUNA, {"enabled": True, "effort": effort}), effort)

# 'max' is in Hermes' config enum but refused by the endpoint for gpt-5.6.
check("luna max clamps to xhigh", effort_for(LUNA, {"enabled": True, "effort": "max"}), "xhigh")

# The Anthropic fallback rides the same host and refuses xhigh.
check("claude xhigh clamps to high", effort_for(CLAUDE, {"enabled": True, "effort": "xhigh"}), "high")
check("claude max clamps to high", effort_for(CLAUDE, {"enabled": True, "effort": "max"}), "high")
check("claude high", effort_for(CLAUDE, {"enabled": True, "effort": "high"}), "high")
check("claude medium", effort_for(CLAUDE, {"enabled": True, "effort": "medium"}), "medium")

print("thinking disabled")
check("enabled False -> none", effort_for(LUNA, {"enabled": False}), "none")

print("function tools present (Hermes always sends them)")
# "Function tools with reasoning_effort are not supported for gpt-5.6-luna in
# /v1/chat/completions" — 400s every turn into the fallback model.
check("gpt + tools -> skipped", effort_for(LUNA, {"enabled": True, "effort": "high"}, tools=TOOLS), None)
check("gpt + tools + none -> skipped", effort_for(LUNA, {"enabled": False}, tools=TOOLS), None)
# The LiteLLM/Anthropic leg of the same gateway takes both together.
check("claude + tools -> emitted", effort_for(CLAUDE, {"enabled": True, "effort": "high"}, tools=TOOLS), "high")

print("no-ops")
check("no reasoning_config", effort_for(LUNA, None), None)
check("unparseable effort", effort_for(LUNA, {"enabled": True, "effort": "turbo"}), None)
check("other host untouched", effort_for(LUNA, {"enabled": True, "effort": "high"},
                                         base_url="https://openrouter.ai/api/v1"), None)
check("lookalike host untouched", effort_for(LUNA, {"enabled": True, "effort": "high"},
                                            base_url=IU.replace(".org", ".org.evil.test")), None)
check("empty base_url untouched", effort_for(LUNA, {"enabled": True, "effort": "high"},
                                             base_url=""), None)

print("value already placed by upstream's CustomProfile")
_pre = _apply_iu_reasoning_effort(
    {"model": LUNA, "reasoning_effort": "low"}, LUNA,
    {"base_url": IU, "reasoning_config": {"enabled": True, "effort": "high"}},
)
check("supported value kept as-is", _pre.get("reasoning_effort"), "low")
_pre = _apply_iu_reasoning_effort(
    {"model": CLAUDE, "reasoning_effort": "xhigh"}, CLAUDE, {"base_url": IU},
)
check("unsupported value clamped", _pre.get("reasoning_effort"), "high")
_pre = _apply_iu_reasoning_effort(
    {"model": LUNA, "reasoning_effort": "high", "tools": TOOLS}, LUNA, {"base_url": IU},
)
check("stripped when tools present", "reasoning_effort" in _pre, False)

print("end-to-end build_kwargs (provider profile path — provider: custom)")


def build(model, tools):
    from providers import get_provider_profile

    return ChatCompletionsTransport().build_kwargs(
        model,
        [{"role": "user", "content": "hi"}],
        tools,
        base_url=IU,
        reasoning_config={"enabled": True, "effort": "high"},
        supports_reasoning=False,
        provider_profile=get_provider_profile("custom"),
        provider_name="custom",
        max_tokens_param_fn=lambda n: {"max_completion_tokens": n},
    )


_k = build(LUNA, TOOLS)
check("luna + tools: no effort on the wire", _k.get("reasoning_effort"), None)
check("luna + tools: tools survive", bool(_k.get("tools")), True)
check("luna, no tools: effort on the wire", build(LUNA, None).get("reasoning_effort"), "high")
check("claude + tools: effort on the wire", build(CLAUDE, TOOLS).get("reasoning_effort"), "high")
# The endpoint 400s on this key — neither upstream nor the patch may send it.
check("no extra_body.reasoning", (build(LUNA, None).get("extra_body") or {}).get("reasoning"), None)

print("api_mode routing for the IU endpoint")
from hermes_cli.runtime_provider import (  # noqa: E402
    _detect_api_mode_for_url,
    _resolve_plain_custom_api_mode,
)

check("openai leg -> responses", _detect_api_mode_for_url(IU), "codex_responses")
check("openai leg, trailing slash", _detect_api_mode_for_url(IU + "/"), "codex_responses")
check(
    "config value is honoured",
    _resolve_plain_custom_api_mode({"api_mode": "codex_responses"}, IU),
    "codex_responses",
)
# The /anthropic leg of the same gateway speaks the Messages protocol.
check(
    "anthropic leg untouched",
    _detect_api_mode_for_url("https://unified-endpoint-main.app.iu-it.org/anthropic"),
    "anthropic_messages",
)
# Host match must not be a substring test — a lookalike host is not ours.
check(
    "lookalike host rejected",
    _detect_api_mode_for_url("https://unified-endpoint-main.app.iu-it.org.evil.test/openai/v1"),
    None,
)
check("unknown relay untouched", _detect_api_mode_for_url("https://relay.test/v1"), None)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
