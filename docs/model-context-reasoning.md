# Model, context window and reasoning effort

Numbers here are **probed against the live IU endpoint**, not read off a model card — every published source disagrees with it in some direction. Re-probe rather than trust this table after an endpoint change.

| | Value | How it was established |
|-|-|-|
| Input cap, `gpt-5.6-luna` | **922,000 tokens** | 900k accepted; 1.1M → `context_length_exceeded`, "configured limit of 922000 tokens". Matches Microsoft's Foundry note that the 1.05M window is a *combined* input+reasoning+output budget. |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k, 260k, 520k and 900k prompts all succeed. Don't configure from it. |
| Published model card | 1,050,000 in / 128,000 out | OpenAI, OpenRouter, Bedrock, Azure all agree; the gateway's own limit is lower. |
| `claude-sonnet-4-6-eu` | ≥300,000 proven | Config sits at 300,000; metadata claims 1M, untested above 300k. |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused by the endpoint although OpenAI's card lists it; `minimal` is not a gpt-5.6 value at all. |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by LiteLLM. |

**Reasoning effort only exists on the Responses API here.** `/v1/chat/completions` refuses any effort as soon as the request carries function tools — *"Function tools with reasoning_effort are not supported for gpt-5.6-luna in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'"* — and Hermes always sends tools, so the effort 400s **every** turn, burns the retry budget, and lands the whole conversation on the Anthropic fallback while looking healthy from the outside. That is why `model.api_mode` is `codex_responses` and why the runtime-provider patch above exists. Diagnosis tell: `Fallback activated: gpt-5.6-luna → claude-sonnet-4-6-eu` on every turn in `~/.hermes/logs/agent.log`, and one line above it, `Ignoring persisted custom api_mode=codex_responses for non-OpenAI endpoint` — that second line means the runtime-provider patch fell off, which is what a `hermes update` does.

> **This is Hermes's own blind spot, and it now has a skill.** `agent.log` is
> **not** rotated per process, so an unbounded read of it misdiagnoses a fixed
> gateway as stale (2026-08-16: Hermes reported a two-day-old burst as current
> and asked for a restart that had already happened). Any read must first be
> sliced at the current process start (`pgrep -f "hermes_cli.main gateway run"`
> → `ps -o lstart=`) — that's Rule 0 in `skills/hermes-gateway/`, whose
> `references/model-routing.md` carries the six commands that prove the live
> route rather than describing the log (`_detect_api_mode_for_url`,
> `resolve_reasoning_config`). It also carries the restart boundary — Hermes
> may not restart its own gateway, `hermes-ops.sh` excludes `ai.hermes.gateway`
> for the same reason, and `claude-dispatch` is not a workaround since it has
> no lifecycle authority over launchd.

**The key is `agent.reasoning_effort`, not `model.reasoning_effort`.** `resolve_reasoning_config()` (`hermes_constants.py`) reads `agent.reasoning_overrides` then `agent.reasoning_effort`, and nothing reads the `model` section's copy — the config carried `model.reasoning_effort: medium` for months with `resolve_reasoning_config(live config) → None`, i.e. no effort configured at all. Both keys are set to `high` now so a future reader can't act on a stale value; only the `agent` one is live. Per-model overrides go in `agent.reasoning_overrides`.

**Compaction triggers at 240,000 tokens**, set as an absolute `compression.threshold_tokens` rather than as a ratio, because the ratio alone is not readable: `context_length` is 850,000 (the probed cap minus headroom), the configured `threshold` is upstream's 0.50, and the *lower* of the two governs. Two ratio traps worth knowing before touching those numbers — a window **under 512K** gets its threshold floored at **0.75** by `_SMALL_CTX_THRESHOLD_PERCENT` (so the old `256000` + `threshold: 0.18` pair really triggered at 192k, not the 46k the arithmetic suggests), and the auxiliary compression model's own `context_length` **clamps the trigger down to itself** (`conversation_compression.py`, `if aux_context < threshold`) — which is why `auxiliary.compression.context_length` is 850,000 too and not the default 200,000. Staying under 240k also keeps prompts below the **272k mark where OpenAI bills input at 2× and output at 1.5×**.

## Auxiliary lanes are separately routed — they are not the brain

`auxiliary.<task>.{provider,model,base_url,api_key,api_mode}` picks a model per task; unset lanes fall through to `auto`, which means the flagship at `high`. Two are pinned off it deliberately:

| Lane | Model | Why not `gpt-5.6-luna` |
|-|-|-|
| `title_generation` | `gemini-2.5-flash-lite`, OpenAI leg | `title_generator.py` hardcodes `temperature=0.3` and gpt-5.x accepts only the default — every title 503'd then self-healed on a retry-without-temperature. ~0.7s instead of a reasoning turn |
| `approval` | `claude-haiku-4-5`, **native `/anthropic` leg** (`${ANTHROPIC_BASE_URL}`, `api_mode: anthropic_messages`) | same 503 (`approval_smart.py` hardcodes `temperature=0`), and this gates every risky terminal command. Measured **0.9s native vs 3.0s** for the same model through the OpenAI-compat shim. `provider` stays `custom`, never `anthropic`, so the auxiliary client never reaches for `~/.claude` OAuth |

There is **no config key to drop `temperature`** — `_fixed_temperature_for_model` is hardcoded to Kimi/Arcee and ignores provider profiles, so repinning the model is the only fix. Pinning the Anthropic leg needs the `anthropic` SDK **already present** in the gateway venv — `agent/anthropic_adapter.py` lazy-*imports* it (~220 ms saved at startup) and raises `ImportError` when it is missing, which `approval_smart.py` catches and turns into `escalate`. Fail-safe, but silent apart from one WARNING nothing watches, so a venv rebuild would quietly demote the classifier to a blanket escalation. Today: `anthropic 0.87.0`. `compression` and `web_extract` stay on luna: both need the 850k window.

## Subagent routing exists but is unused

`delegation.*` is configured but repo work goes to Claude Code via the dispatch bridge, and a Hermes child gets no `.claude/rules`, no `.claude/skills` and no PR artifact. Worth considering only for read-heavy fan-out (parallel log/API triage). If one is ever pinned to a cheaper model: **`delegation.api_mode` is silently dropped unless `delegation.base_url` or `delegation.provider` is set too**, so `model: claude-*` alone inherits `codex_responses` and 404s — the same trap the `fallback_providers` entry spells out `chat_completions` to avoid. A pin also costs the child its fallback chain and capability inheritance.

## Core-tool deferral is on and wanted

`tools.tool_search.enabled: auto`. 4 of 21 tools defer behind a 3-tool bridge — measured **−19.8% (~2,150 tokens) off the cached tool prefix every turn** on the real Slack toolset, not upstream's headline −49% (that is the desktop/GUI surface). It costs +1 turn when a deferred tool is actually needed. `threshold_pct: 10` in `config.yaml` is now a *listing budget*, not an activation gate. Deferral can never empty `tools`, so it does not interact with the reasoning-effort patches. Watch `cronjob_manage`: it is 69% of the deferred mass and upstream measured 16/18 discovery — if Hermes ever claims it can't schedule something, drop that one name from `tools.tool_search.defer` rather than disabling the feature.
