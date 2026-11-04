#!/usr/bin/env python3
"""Regression suite for the IU / inference-gateway OpenAI-leg patches (the failover lane).

Every predicate covers the IU OpenAI leg directly and through the local inference
gateway (``GATEWAY`` below), which passes that leg through; the last section pins the
gateway half, since live traffic only reaches it there.

* ``patches/runtime-provider-iu-responses-api.patch`` — routes the IU
  endpoint's OpenAI leg onto the Responses API for a gpt-5.x model with no
  explicit ``api_mode`` (dormant on the current config, every live slot pins
  one explicitly).
* ``patches/transport-iu-reasoning-effort.patch`` — reconciles the effort
  upstream's ``CustomProfile`` puts on the wire with what each model family
  accepts on this gateway, for the main-loop model only (brain + fallback) —
  deny-by-default for tools+effort (only claude/deepseek/glm are probed to
  accept both; an unrecognized id gets no effort at all, not the gpt-5 ladder).
* ``patches/utils-max-completion-tokens-gpt6.patch`` — ``gpt-6`` joins
  ``model_forces_max_completion_tokens``, so the failover ``gpt-6-luna`` gets
  ``max_completion_tokens`` in ``run_agent`` and the auxiliary client (the URL-based
  run-agent / auxiliary-client patches were retired 2026-11-04).

Run:  ~/.hermes/hermes-agent/venv/bin/python3 tests/test_iu_reasoning_effort.py
``HERMES_SRC`` points it at another checkout (a scratch tree holding unreleased patches).
"""
import os
import sys

sys.path.insert(0, os.environ.get("HERMES_SRC", os.path.expanduser("~/.hermes/hermes-agent")))

from agent.transports.chat_completions import (  # noqa: E402
    ChatCompletionsTransport,
    _apply_iu_reasoning_effort,
)

IU = "https://unified-endpoint-main.app.iu-it.org/openai/v1"
LUNA = "gpt-5.6-luna"
LUNA6 = "gpt-6-luna"
GATEWAY = "http://127.0.0.1:7794/openai/v1"
GATEWAY_ANTHROPIC = "http://127.0.0.1:7794/anthropic"
CLAUDE = "claude-sonnet-4-6"
DEEPSEEK = "deepseek-v4.1-flash"
GLM = "glm-5.3-flash"
UNKNOWN = "some-future-model-v9"

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

# Anthropic ids on this leg refuse xhigh.
check("claude xhigh clamps to high", effort_for(CLAUDE, {"enabled": True, "effort": "xhigh"}), "high")
check("claude max clamps to high", effort_for(CLAUDE, {"enabled": True, "effort": "max"}), "high")
check("claude high", effort_for(CLAUDE, {"enabled": True, "effort": "high"}), "high")
check("claude medium", effort_for(CLAUDE, {"enabled": True, "effort": "medium"}), "medium")

print("deepseek + glm effort families")
for effort in ("low", "high", "xhigh", "max"):
    check(f"deepseek {effort}", effort_for(DEEPSEEK, {"enabled": True, "effort": effort}), effort)
check("glm low", effort_for(GLM, {"enabled": True, "effort": "low"}), "low")
check("glm high", effort_for(GLM, {"enabled": True, "effort": "high"}), "high")
check("glm max", effort_for(GLM, {"enabled": True, "effort": "max"}), "max")
# glm rejects 'medium' on this leg; clamp to the strongest supported level below it.
check("glm medium clamps to low", effort_for(GLM, {"enabled": True, "effort": "medium"}), "low")

print("gpt-6 family — same none..xhigh ladder as gpt-5")
for effort in ("none", "low", "medium", "high", "xhigh"):
    check(f"luna6 {effort}", effort_for(LUNA6, {"enabled": True, "effort": effort}), effort)
check("luna6 max clamps to xhigh", effort_for(LUNA6, {"enabled": True, "effort": "max"}), "xhigh")

print("unknown model family — deny-by-default, never falls through to the gpt-5 ladder")
# An id this endpoint hasn't been probed against gets no effort at all, not a guess.
check("unknown, no tools -> omitted", effort_for(UNKNOWN, {"enabled": True, "effort": "high"}), None)
check("unknown + tools -> omitted", effort_for(UNKNOWN, {"enabled": True, "effort": "high"}, tools=TOOLS), None)

print("thinking disabled")
check("enabled False -> none", effort_for(LUNA, {"enabled": False}), "none")

print("function tools present (Hermes always sends them)")
# Deny-by-default: only claude/deepseek/glm are probed to accept tools + effort together.
# "Function tools with reasoning_effort are not supported for gpt-5.6-luna in
# /v1/chat/completions" — 400s every turn into the fallback model.
check("gpt + tools -> skipped", effort_for(LUNA, {"enabled": True, "effort": "high"}, tools=TOOLS), None)
check("gpt + tools + none -> skipped", effort_for(LUNA, {"enabled": False}, tools=TOOLS), None)
# gpt-6-luna refuses tools with the key omitted too — only an explicit 'none' passes.
check("gpt-6 + tools -> none", effort_for(LUNA6, {"enabled": True, "effort": "max"}, tools=TOOLS), "none")
check("gpt-6 + tools, no config -> none", effort_for(LUNA6, None, tools=TOOLS), "none")
check("deepseek + tools -> emitted", effort_for(DEEPSEEK, {"enabled": True, "effort": "high"}, tools=TOOLS), "high")
check("glm + tools -> emitted", effort_for(GLM, {"enabled": True, "effort": "high"}, tools=TOOLS), "high")
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
check("deepseek + tools: effort on the wire", build(DEEPSEEK, TOOLS).get("reasoning_effort"), "high")
# The endpoint 400s on this key — neither upstream nor the patch may send it.
check("no extra_body.reasoning", (build(LUNA, None).get("extra_body") or {}).get("reasoning"), None)

print("max_completion_tokens for the failover — run_agent._max_tokens_param and the auxiliary client")
from run_agent import AIAgent  # noqa: E402
from agent.auxiliary_client import auxiliary_max_tokens_param  # noqa: E402


def max_tokens_param_for(model, base_url):
    agent = AIAgent.__new__(AIAgent)
    agent._base_url_lower = base_url.lower()
    agent._base_url_hostname = ""
    agent.model = model
    return agent._max_tokens_param(65536)


FAILOVER = "gpt-6-luna"
check("failover on the gateway OpenAI leg -> max_completion_tokens",
      max_tokens_param_for(FAILOVER, GATEWAY), {"max_completion_tokens": 65536})
check("gpt-6 on IU direct -> max_completion_tokens",
      max_tokens_param_for(FAILOVER, IU), {"max_completion_tokens": 65536})
check("aux client, failover model -> max_completion_tokens",
      auxiliary_max_tokens_param(16000, model=FAILOVER), {"max_completion_tokens": 16000})
check("a non-OpenAI id is unaffected -> max_tokens",
      max_tokens_param_for("claude-haiku-5-5", GATEWAY_ANTHROPIC), {"max_tokens": 65536})

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

print("the same leg through the local inference gateway")
OTHER_LOOPBACK = "http://127.0.0.1:7795/openai/v1"
LOOKALIKE = "http://127.0.0.1.evil.test:7794/openai/v1"
IU_EXPLICIT_PORT = IU.replace(".org/", ".org:443/")

check("gateway: gpt-6 + tools -> none",
      effort_for(LUNA6, {"enabled": True, "effort": "high"}, base_url=GATEWAY, tools=TOOLS), "none")
check("gateway: deepseek + tools -> emitted",
      effort_for(DEEPSEEK, {"enabled": True, "effort": "high"}, base_url=GATEWAY, tools=TOOLS), "high")
check("gateway: luna max clamps to xhigh",
      effort_for(LUNA, {"enabled": True, "effort": "max"}, base_url=GATEWAY), "xhigh")
check("gateway, trailing slash: clamp still applies",
      effort_for(LUNA, {"enabled": True, "effort": "max"}, base_url=GATEWAY + "/"), "xhigh")
check("IU with an explicit port still matches",
      effort_for(LUNA, {"enabled": True, "effort": "max"}, base_url=IU_EXPLICIT_PORT), "xhigh")
check("other loopback port untouched",
      effort_for(LUNA, {"enabled": True, "effort": "high"}, base_url=OTHER_LOOPBACK), None)
check("lookalike gateway host untouched",
      effort_for(LUNA, {"enabled": True, "effort": "high"}, base_url=LOOKALIKE), None)
check("gateway /anthropic leg untouched",
      effort_for(LUNA, {"enabled": True, "effort": "high"}, base_url=GATEWAY_ANTHROPIC), None)

check("gateway openai leg -> responses", _detect_api_mode_for_url(GATEWAY), "codex_responses")
check("gateway openai leg, trailing slash", _detect_api_mode_for_url(GATEWAY + "/"), "codex_responses")
check("gateway anthropic leg", _detect_api_mode_for_url(GATEWAY_ANTHROPIC), "anthropic_messages")
check("other loopback port not forced", _detect_api_mode_for_url(OTHER_LOOPBACK), None)

print()
if failures:
    print(f"FAILED ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
