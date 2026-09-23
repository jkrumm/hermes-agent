# Model, context window and reasoning effort

Numbers here are **probed against the live IU endpoint**, not read off a model card — every published source disagrees with it in some direction. Re-probe rather than trust this table after an endpoint change.

| | Value | How it was established |
|-|-|-|
| Context, `deepseek-v4.1-flash` (brain) | **1,000,000** | probed 2026-09-13. `/chat/completions` 200; `/responses` **404** ("No suitable backend") despite `/models` listing Responses |
| Input cap, `gpt-5.6-luna` (fallback + title_generation until 2026-09-23; not re-probed for `gpt-6-luna`) | **922,000 tokens** | 900k accepted; 1.1M → `context_length_exceeded`, "configured limit of 922000 tokens". Matches Microsoft's Foundry note that the 1.05M window is a *combined* input+reasoning+output budget. |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k, 260k, 520k and 900k prompts all succeed. Don't configure from it. |
| Published model card (gpt-5.6-luna) | 1,050,000 in / 128,000 out | OpenAI, OpenRouter, Bedrock, Azure all agree; the gateway's own limit is lower. |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused by the endpoint although OpenAI's card lists it; `minimal` is not a gpt-5.6 value at all. |
| Efforts, `gpt-6-luna` (fallback, title_generation since 2026-09-23) | `none, low, medium, high, xhigh` | probed 2026-09-23. `max` refused; only default `temperature`. With function tools it refuses **both** a real effort and an omitted key — only an explicit `reasoning_effort: none` passes, so the transport patch sets `none` for the `gpt-6` family instead of stripping. |
| Efforts, `deepseek-v4.1-flash` | `low, high, xhigh, max` | accepts function tools **and** `reasoning_effort` in the same `/chat/completions` request — no strip needed, unlike gpt-5.x |
| Efforts, `glm-5.3-flash` (OpenAI leg, reachable via this endpoint) | `low, high, max` | `medium` refused |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by LiteLLM. |

**DeepSeek needed no Responses-API workaround — the effort-vs-tools conflict is gpt-5.x-only.**
`/v1/chat/completions` refuses any effort as soon as the request carries function tools for
gpt-5.x models — *"Function tools with reasoning_effort are not supported for gpt-5.6-luna in
/v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to
'none'"* — and Hermes always sends tools. That is what `patches/runtime-provider-iu-responses-api.patch`
and the effort-strip half of `patches/transport-iu-reasoning-effort.patch` exist for, and it's
still true for `gpt-6-luna` today (the fallback + title_generation model since 2026-09-23), which additionally needs an explicit `none` rather than an omitted key. But DeepSeek
(probed 2026-09-13) takes tools and a top-level `reasoning_effort` together with no refusal, so
the brain runs plain `api_mode: chat_completions` and gets `agent.reasoning_effort: high` on
every turn, tools included — `patches/transport-iu-reasoning-effort.patch`'s tools-strip branch
is **deny-by-default**: it keeps the effort only for a probed-safe allowlist
(Anthropic/DeepSeek/GLM) and strips it for everything else, gpt-5.x and any model id this
endpoint hasn't been probed against included — never the reverse ("assume a new id is fine").

**`patches/runtime-provider-iu-responses-api.patch` is dormant on the current config, not
retired.** It forces the IU OpenAI leg onto `codex_responses` only when a slot's `api_mode` is
*not* set explicitly; every slot here now pins `chat_completions` explicitly (brain, fallback,
compression, title_generation, vision), so the patch's forced detection never fires. It stays
applied as the safety net for the next time this endpoint runs a gpt-5.x model with no explicit
`api_mode` — dropping it would silently reopen the tools+effort 400 for that future case.
Diagnosis tell if the fallback *is* active: `Fallback activated: deepseek-v4.1-flash →
gpt-6-luna` on every turn in `~/.hermes/logs/agent.log` (expected under throttling — the
fallback then runs with **no** reasoning effort while tools are attached, the 503-avoidance
tradeoff `transport-iu-reasoning-effort.patch` makes, not a fault); one line above it,
`Ignoring persisted custom api_mode=codex_responses for non-OpenAI endpoint` means some patch
fell off, which is what a `hermes update` does.

> **This is Hermes's own blind spot, and it now has a skill.** `agent.log` is
> **not** rotated per process, so an unbounded read of it misdiagnoses a fixed
> gateway as stale (2026-08-16: Hermes reported a two-day-old burst as current
> and asked for a restart that had already happened). Any read must first be
> sliced at the current process start (`pgrep -f "hermes_cli.main gateway run"`
> → `ps -o lstart=`) — that's Rule 0 in `skills/hermes-gateway/`, whose
> `references/model-routing.md` carries the commands that prove the live
> route rather than describing the log (`_detect_api_mode_for_url`,
> `resolve_reasoning_config`). It also carries the restart boundary — Hermes
> may not restart its own gateway, `hermes-ops.sh` excludes `ai.hermes.gateway`
> for the same reason, and `claude-dispatch` is not a workaround since it has
> no lifecycle authority over launchd.

**The key is `agent.reasoning_effort`, not `model.reasoning_effort`.** `resolve_reasoning_config()` (`hermes_constants.py`) reads `agent.reasoning_overrides` then `agent.reasoning_effort`, and nothing reads the `model` section's copy. `model.reasoning_effort` has been removed from `config.yaml` entirely (2026-09-13) rather than kept as a synced-but-dead mirror — it carried `medium` for months while `resolve_reasoning_config(live config) → None` read the real, live key instead, i.e. no future reader can act on a value nothing consults. Per-model overrides go in `agent.reasoning_overrides`.

**Compaction triggers at 240,000 tokens**, set as an absolute `compression.threshold_tokens` rather than as a ratio, because the ratio alone is not readable: `auxiliary.compression.context_length` is 850,000 (kept below the brain's real 1,000,000 window — DeepSeek does prompt-cache here, 92–96% of input on live sessions (modelpick `hermes-brain.md` §2026-09-13 correction)), the configured `threshold` is upstream's 0.50, and the *lower* of the two governs. Two ratio traps worth knowing before touching those numbers — a window **under 512K** gets its threshold floored at **0.75** by `_SMALL_CTX_THRESHOLD_PERCENT` (so the old `256000` + `threshold: 0.18` pair really triggered at 192k, not the 46k the arithmetic suggests; 850,000 is comfortably above the floor either way), and the auxiliary compression model's own `context_length` **clamps the trigger down to itself** (`conversation_compression.py`, `if aux_context < threshold`) — which is why `auxiliary.compression.context_length` stays a deliberate 850,000, not the model's full window or the default 200,000. Staying under 240k also keeps prompts below the **272k mark where OpenAI bills input at 2× and output at 1.5×** for the gpt-5.x-family models still in play (fallback, title_generation).

## Auxiliary lanes are separately routed — they are not the brain

`auxiliary.<task>.{provider,model,base_url,api_key,api_mode}` picks a model per task; unset lanes fall through to `auto`, which means the flagship at `high`. Three are pinned off the brain deliberately:

| Lane | Model | Why not the brain |
|-|-|-|
| `title_generation` | `gpt-6-luna`, OpenAI leg, `reasoning_effort: low` | `title_generator.py:268` hardcodes `temperature=0.3`; gpt-5.x 503s on any non-default temperature — upstream's `_is_openai_default_temperature_only` omits it for gpt-5.x, `patches/auxiliary-client-iu-openai-leg-quirks.patch` extends that to gpt-6.x (gpt-6-luna refuses 0.3, probed 2026-09-23) |
| `approval` | `claude-haiku-4-5`, **native `/anthropic` leg** (`${ANTHROPIC_BASE_URL}`, `api_mode: anthropic_messages`) | same 503 shape (`approval_smart.py` hardcodes `temperature=0`), and this gates every risky terminal command. Measured **0.9s native vs 3.0s** for the same model through the OpenAI-compat shim. `provider` stays `custom`, never `anthropic`, so the auxiliary client never reaches for `~/.claude` OAuth |
| `vision` | `gemini-3.5-flash`, IU OpenAI leg | moved off Google AI Studio direct 2026-09-13 — no deliberate reason for the direct route was ever recorded here, and modelpick flagged it as two generations stale. See `modelpick/docs/decisions/vision-and-image.md` |

`compression` stays on the brain (`deepseek-v4.1-flash`, `reasoning_effort: high`) — it needs the
850k-token context, and DeepSeek's tools+effort behaviour is irrelevant here since compression
calls carry no tools. `auxiliary.web_extract` and `auxiliary.session_search` were removed
entirely (2026-09-13): upstream stopped reading either — `config_defaults.py` notes both "no
longer use an auxiliary LLM... [existing config] ignored" — so the blocks were dead weight, not
live config.

There is **no config key to drop `temperature` on its own** — `_fixed_temperature_for_model` only recognized Kimi/Arcee by name before this rollout; `patches/auxiliary-client-iu-openai-leg-quirks.patch` extends it with a host+model-prefix check (gpt-5.x on the IU OpenAI leg) rather than repinning yet another model. Pinning the Anthropic leg needs the `anthropic` SDK **already present** in the gateway venv — `agent/anthropic_adapter.py` lazy-*imports* it (~220 ms saved at startup) and raises `ImportError` when it is missing, which `approval_smart.py` catches and turns into `escalate`. Fail-safe, but silent apart from one WARNING nothing watches, so a venv rebuild would quietly demote the classifier to a blanket escalation. Today: `anthropic 0.87.0`.

## Subagent routing exists but is unused

`delegation.*` is configured but repo work goes to Claude Code via the dispatch bridge, and a Hermes child gets no `.claude/rules`, no `.claude/skills` and no PR artifact. Worth considering only for read-heavy fan-out (parallel log/API triage). If one is ever pinned to a cheaper model: **`delegation.api_mode` is silently dropped unless `delegation.base_url` or `delegation.provider` is set too**, so `model: claude-*` alone inherits `codex_responses` and 404s — the same trap the `fallback_providers` entry spells out `chat_completions` to avoid. A pin also costs the child its fallback chain and capability inheritance.

## Core-tool deferral is on and wanted

`tools.tool_search.enabled: auto`. 4 of 21 tools defer behind a 3-tool bridge — measured **−19.8% (~2,150 tokens) off the cached tool prefix every turn** on the real Slack toolset, not upstream's headline −49% (that is the desktop/GUI surface). It costs +1 turn when a deferred tool is actually needed. `threshold_pct: 10` in `config.yaml` is now a *listing budget*, not an activation gate. Deferral can never empty `tools`, so it does not interact with the reasoning-effort patches. Watch `cronjob_manage`: it is 69% of the deferred mass and upstream measured 16/18 discovery — if Hermes ever claims it can't schedule something, drop that one name from `tools.tool_search.defer` rather than disabling the feature.
