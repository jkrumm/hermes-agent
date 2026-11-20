# Model, context window and reasoning effort

> **2026-11-15 — Hermes is Claude-only.** The `gpt-6-luna` failover, the gateway's OpenAI leg
> (`providers.custom`, `custom_providers`, `fallback_providers`) and the three patches that existed
> for GPT on IU (`runtime-provider-iu-responses-api`, `transport-iu-reasoning-effort`,
> `utils-max-completion-tokens-gpt6`) are gone (`docs/patches.md`). IU's OpenAI and Anthropic paths
> share one personal key and cap, so the failover added no budget; the gateway already falls back from
> the Claude credit pools to IU's `/anthropic` (`agent-workflows/docs/gateway.md` §Picking a pool).
> The five seats follow `agw routes` `hermes.*`, pinned by `make seats-check`. **Every GPT, DeepSeek
> and OpenAI-leg row below is history**, kept for the probe numbers.
>
> **2026-11-04 — the brain is Claude Haiku 5.5 (`high`) on the inference gateway's Anthropic leg, and
> every auxiliary lane moved with it.** The gateway spends the
> Claude credit pools first. Compaction is 650,000 tokens since 2026-11-04 (owner decision; briefly 90,000, a cost guess for Haiku's 5x-above-100k line), the cache TTL is
> `auto` (1h for human-paced sources), and `model.provider` is `gateway-anthropic`.

Numbers here are **probed against the live IU endpoint**, not read off a model card — every published source disagrees with it in some direction. Re-probe rather than trust this table after an endpoint change.

| | Value | How it was established |
|-|-|-|
| Former brain, Haiku 5.5 EU (2026-10-08 → 10-20) | Bedrock **eu-west-1**, native `/anthropic` leg, `anthropic_messages` | modelpick 2026-10-08. The lanes that still run Haiku 5.5 use `claude-haiku-5-5` on the gateway since it replaced IU's EU route. Adaptive thinking, `output_config.effort` honoured at every level; `high` 15/15 at ~1.6 s median, `medium` 14/15, `xhigh`/`max` think 50–100 s+ on long outputs. Output cap 128k (thinking counts toward `max_tokens`). Input price doubles+ above 100k tokens ($0.10/$0.50 → $0.50/$2.50 per MTok) |
| Context, `deepseek-v4.1-flash` (former brain and compression; no longer routed) | **1,000,000** | probed 2026-09-13. `/chat/completions` 200; `/responses` **404** ("No suitable backend") despite `/models` listing Responses |
| Input cap, `gpt-5.6-luna` (fallback + title_generation until 2026-09-23; not re-probed for `gpt-6-luna`) | **922,000 tokens** | 900k accepted; 1.1M → `context_length_exceeded`, "configured limit of 922000 tokens". Matches Microsoft's Foundry note that the 1.05M window is a *combined* input+reasoning+output budget. |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k, 260k, 520k and 900k prompts all succeed. Don't configure from it. |
| Published model card (gpt-5.6-luna) | 1,050,000 in / 128,000 out | OpenAI, OpenRouter, Bedrock, Azure all agree; the gateway's own limit is lower. |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused by the endpoint although OpenAI's card lists it; `minimal` is not a gpt-5.6 value at all. |
| Efforts, `gpt-6-luna` (fallback, title_generation since 2026-09-23) | `none, low, medium, high, xhigh` | probed 2026-09-23. `max` refused; only default `temperature`. With function tools it refuses **both** a real effort and an omitted key — only an explicit `reasoning_effort: none` passes, so the transport patch sets `none` for the `gpt-6` family instead of stripping. |
| Efforts, `deepseek-v4.1-flash` (no longer routed) | `low, high, xhigh, max` | accepts function tools **and** `reasoning_effort` in the same `/chat/completions` request — no strip needed, unlike gpt-5.x |
| Efforts, `glm-5.3-flash` (OpenAI leg, reachable via this endpoint) | `low, high, max` | `medium` refused |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by LiteLLM. |

**History (GPT/DeepSeek era):** `/v1/chat/completions` refused any effort alongside function tools for
gpt-5.x (an explicit `none` for gpt-6), which is what the three retired patches papered over;
DeepSeek took tools and effort together. None of it applies to `anthropic_messages`, where
upstream's `_thinking_kwargs` carries the effort. There is no Hermes-side fallback now: a gateway
402/5xx is a turn error.

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
> for the same reason, and handing it to a repo agent is not a workaround since it has
> no lifecycle authority over launchd.

**The key is `agent.reasoning_effort`, not `model.reasoning_effort`.** `resolve_reasoning_config()` (`hermes_constants.py`) reads `agent.reasoning_overrides` then `agent.reasoning_effort`, and nothing reads the `model` section's copy. `model.reasoning_effort` has been removed from `config.yaml` entirely (2026-09-13) rather than kept as a synced-but-dead mirror — it carried `medium` for months while `resolve_reasoning_config(live config) → None` read the real, live key instead, i.e. no future reader can act on a value nothing consults. Per-model overrides go in `agent.reasoning_overrides`.

**Compaction triggered at 240,000 tokens until 2026-11-04 (now 650,000, see the note at the top)**, set as an absolute `compression.threshold_tokens` rather than as a ratio, because the ratio alone is not readable: `auxiliary.compression.context_length` is 850,000 (kept below the brain's real 1,000,000 window — DeepSeek does prompt-cache here, 92–96% of input on live sessions (modelpick `hermes-brain.md` §2026-09-13 correction)), the configured `threshold` is upstream's 0.50, and the *lower* of the two governs. Two ratio traps worth knowing before touching those numbers — a window **under 512K** gets its threshold floored at **0.75** by `_SMALL_CTX_THRESHOLD_PERCENT` (so the old `256000` + `threshold: 0.18` pair really triggered at 192k, not the 46k the arithmetic suggests; 850,000 is comfortably above the floor either way), and the auxiliary compression model's own `context_length` **clamps the trigger down to itself** (`conversation_compression.py`, `if aux_context < threshold`) — which is why `auxiliary.compression.context_length` stays a deliberate 850,000, not the model's full window or the default 200,000. Staying under 240k also keeps prompts below the **272k mark where OpenAI bills input at 2× and output at 1.5×** for the gpt-5.x-family models still in play (fallback, title_generation).

## Iris turns: effort bench, medium against high (2026-11-20)

Question: does `reasoning_effort: medium` cut the 12–18 s of thinking on an Iris note turn without changing what Hermes does? Method: the live gateway, real Iris `system_message`, one session per case, `model_options.reasoning_effort` per request (no config change), the arms run side by side, 6 note memos, 3 chat turns, 2 follow-ups, n = 1 per cell. Every turn was a dry run: an extra system line told the model to state the command and target path instead of writing, committing or creating tasks, so the bench left the vault and TickTick alone (the actions are compared by tool calls and the stated command). Seconds are wall clock per turn with six turns in flight at once, so only the ratios mean anything.

| Case | high s | medium s | Both blocks valid | Action |
|-|-|-|-|-|
| N1 (note) | 12.4 | 9.2 | yes | dial-in-log entry (both) |
| N2 (note) | 30.9 | 10.4 | yes | high: new vault note; medium: GitHub issue on the repo |
| N3 (note) | 24.4 | 7.0 | yes | Inbox script (both) |
| N4 (note) | 13.1 | 19.5 | yes | new wiki/engineering note (both); medium also fired a stray no-op browser call |
| N5 (note) | 33.3 | 7.6 | yes | high: searched the vault, then TickTick task + page entry; medium: same split but loaded neither `capture` nor `obsidian` and ran no vault search (home guessed) |
| N6 (note) | 6.5 | 7.2 | yes | TickTick task, same payload (both) |
| C1 (chat) | 4.2 | 4.6 | yes | chat, no tools (both) |
| C2 (chat) | 5.5 | 5.6 | yes | answer (both) |
| C3 (chat) | 4.7 | 4.3 | yes | chat (both) |
| F1 (follow-up) | 6.4 | 2.8 | yes | dial-in correction, same entry (both) |
| F2 (follow-up) | 2.4 | 2.4 | yes | answer (both) |

Verdict: **keep `high` for Iris.** Medium is faster on notes (mean 10.1 s against 20.1 s over the six note memos) and every closing `iris` block was valid at both levels, but medium changed the action on N2 (a GitHub issue where high filed a vault note) and chose the N5 homes without loading `obsidian` or searching the vault. That is the same shape as the 2026-10-08 bench ("medium dropped a task"), so the rule stands: no regression is worth the seconds. Chat turns and follow-ups made the same choices at both levels and took about the same time (F1 aside), so there is little to win there. The lever is `api_server_turn_profiles[].reasoning_effort` in `config.yaml` (Iris only; `agent.reasoning_effort` stays `high`). A re-bench needs n above 1 per cell and the real side effects, in a sandboxed vault.

## Auxiliary lanes are separately routed — they are not the brain

`auxiliary.<task>.{provider,model,base_url,api_key,api_mode}` picks a model per task; unset lanes fall through to `auto`, which means the flagship at `high`. Three are pinned off the brain deliberately:

| Lane | Model | Why not the brain |
|-|-|-|
| `title_generation` (until 2026-11-04; now Haiku 5.5 `none`, Anthropic leg) | `gpt-6-luna`, OpenAI leg, `reasoning_effort: low` | `title_generator.py:268` hardcodes `temperature=0.3`; gpt-5.x 503s on any non-default temperature — upstream's `_is_openai_default_temperature_only` omits it for gpt-5.x, `patches/auxiliary-client-iu-openai-leg-quirks.patch` extends that to gpt-6.x (gpt-6-luna refuses 0.3, probed 2026-09-23) |
| `approval` | `claude-haiku-5-5` (was `claude-haiku-4-5` until 2026-10-08, which approved `rm -rf ~/SourceRoot` in a probe), **native `/anthropic` leg** (`${ANTHROPIC_BASE_URL}`, `api_mode: anthropic_messages`) | same 503 shape (`approval_smart.py` hardcodes `temperature=0`), and this gates every risky terminal command. Measured **0.9s native vs 3.0s** for the same model through the OpenAI-compat shim. `provider` stays `custom`, never `anthropic`, so the auxiliary client never reaches for `~/.claude` OAuth |
| `vision` | `claude-haiku-5-5`, effort `none` (Sonnet 5.5 `medium` until 2026-11-16), **native `/anthropic` leg** (`${ANTHROPIC_BASE_URL}`, `api_mode: anthropic_messages`) | on the leg that spends Claude credit first, not through the OpenAI-compat shim. Needs no context pin: nothing on the vision path resolves a window |

`compression` was `gpt-6-luna` (`reasoning_effort: high`, OpenAI leg) from 2026-10-09 to 2026-11-04 (now Haiku 5.5 `high`, Anthropic leg), replacing DeepSeek — the last DeepSeek slot. It needs the
850k-token context; the gpt-6 tools+effort refusal is irrelevant since compression calls carry no tools. Probed: a 279k-token prompt at `high` returned in 6.2 s. `auxiliary.web_extract` and `auxiliary.session_search` were removed
entirely (2026-09-13): upstream stopped reading either — `config_defaults.py` notes both "no
longer use an auxiliary LLM... [existing config] ignored" — so the blocks were dead weight, not
live config.

There is **no config key to drop `temperature` on its own** — `_fixed_temperature_for_model` only recognized Kimi/Arcee by name before this rollout; `patches/auxiliary-client-iu-openai-leg-quirks.patch` extends it with a host+model-prefix check (gpt-5.x on the IU OpenAI leg) rather than repinning yet another model. Pinning the Anthropic leg needs the `anthropic` SDK **already present** in the gateway venv — `agent/anthropic_adapter.py` lazy-*imports* it (~220 ms saved at startup) and raises `ImportError` when it is missing, which `approval_smart.py` catches and turns into `escalate`. Fail-safe, but silent apart from one WARNING nothing watches, so a venv rebuild would quietly demote the classifier to a blanket escalation. Today: `anthropic 0.87.0`.

## Subagent routing exists but is unused

`delegation.*` is configured but repo work is filed as a GitHub issue, and a Hermes child gets no `.claude/rules`, no `.claude/skills` and no PR artifact. Worth considering only for read-heavy fan-out (parallel log/API triage). If one is ever pinned to a cheaper model: **`delegation.api_mode` is silently dropped unless `delegation.base_url` or `delegation.provider` is set too**, so `model: claude-*` alone inherits `codex_responses` and 404s — the same trap the `fallback_providers` entry spells out `chat_completions` to avoid. A pin also costs the child its fallback chain and capability inheritance.

## Core-tool deferral is on and wanted

`tools.tool_search.enabled: auto`. 4 of 21 tools defer behind a 3-tool bridge — measured **−19.8% (~2,150 tokens) off the cached tool prefix every turn** on the real gateway toolset, not upstream's headline −49% (that is the desktop/GUI surface). It costs +1 turn when a deferred tool is actually needed. `threshold_pct: 10` in `config.yaml` is now a *listing budget*, not an activation gate. Deferral can never empty `tools`, so it does not interact with the reasoning-effort patches. Watch `cronjob_manage`: it is 69% of the deferred mass and upstream measured 16/18 discovery — if Hermes ever claims it can't schedule something, drop that one name from `tools.tool_search.defer` rather than disabling the feature.

## Brain on Haiku 5.5 EU — the 100k price cliff vs the 240k compaction trigger (accepted)

Input is $0.10/MTok (output $0.50) up to 100k tokens and $0.50/$2.50 above it — 5×. Compaction
triggers at 240k, so every API call between 100k and 240k is billed at the high tier; sessions
that live there (long chat threads, briefings with tool dumps — the 2026-10-08 06:30 briefing
ran 46k → 124k) pay 5× on the whole prompt. Prompt caching is working (live: `cache=26214/38953`,
then 100% on later calls), which discounts reads but not the tier. **Owner decision 2026-10-09: accept the cliff** —
the 240k trigger stays; the extra cost of long threads is fine.

The startup warning `model.context_length pins … 1,000,000 but provider advertises 200,000` is
stale metadata, not a real limit: a direct probe on 2026-10-08 sent Haiku 5.5 EU 599,017
and 749,017 input tokens on the IU Anthropic route and both returned 200. The 1M pin is correct,
and the 240k trigger fires well inside the window.

## What `127.0.0.1` changes

The gateway's loopback address makes `is_local_endpoint` true, which Hermes reads as "a local
model server". Read on v0.22.2, and exercised against the live gateway through a scratch tree:

| Site | On the gateway | Effect |
|-|-|-|
| Context length (`model_metadata.py:2010,2075,2334`) | never reached | Every lane that uses a window has a pin: `model.context_length`, `auxiliary.{compression,title_generation,approval}.context_length`, and the `models:` tables on the route entries. `tests/test_gateway_provider.py` fails if a slot reaches a probe |
| `query_ollama_num_ctx` (`agent_init.py:2165`) | runs once per process and TTL | `detect_local_server_type` walks the LM Studio, Ollama, llama.cpp and vLLM paths, none answers 200, so the server type stays unknown and no `num_ctx` is sent. `/openai/v1/props` falls into the gateway's passthrough and comes back 501, which writes a zero-token `outcome: error` row: noise on the hermes lane, not a failed turn |
| Non-stream stale timeout (`run_agent.py:589`, `chat_completion_helpers.py:846`) | not tighter | `inf` for a model without a reasoning floor. `deepseek-v4.1-flash` keeps its 600 s floor, the same path as on IU. `HERMES_API_TIMEOUT` (1800 s) stays the request timeout |
| Codex-only floors (`chat_completion_helpers.py:846,1190`) | not reached | Every slot pins `chat_completions` or `anthropic_messages` |
| Stream timeouts (`chat_completion_helpers.py:2911,3903`) | more patient | Read 120 s → 1800 s, stale detector → 900 s (`agent.local_stream_stale_timeout`), so a stalled stream takes longer to give up |
| Auxiliary first-token window (`auxiliary_stream_watchdog.py:150`) | gone | A silent auxiliary stream waits out the task's `timeout` instead of the cloud patience |
| Reasoning replay (`message_sanitization.py:723`) | unchanged | `provider: custom` already selects the local carriers before the host is read |
| Managed llama.cpp (`conversation_loop.py:459`, `chat_completion_local.py`) | unchanged | Guarded by `is_managed_endpoint`, which is false |
| Unexplained context rejection (`turn_overflow.py:413`) | **changed** | A "too large" error with no 4+ digit number, on a request under the window's rejection fraction, now fails the turn as retryable instead of compressing. Hermes assumes a busy local slot. Upstream errors normally quote the token count, which skips this branch |

<!-- MOVED-MODEL: moved verbatim from the root AGENTS.md (Model, context window and reasoning effort, 5524 bytes) -->

## Model, context window and reasoning effort

Numbers are **probed against the live IU endpoint**, not read off a model card — every
published source disagrees in some direction. Re-probe after an endpoint change.

| | Value | How established |
|-|-|-|
| Brain, `claude-haiku-5-5` (2026-11-04) | gateway `/anthropic` leg, `anthropic_messages`, `high`; `model.provider: gateway-anthropic` | modelpick bench: `high` 15/15 ~1.6 s (route tier EASY); `xhigh`/`max` think 50–100 s+. The gateway spends the Claude subscription credit pools first, IU's `/anthropic` only when none has credit. Revert to DeepSeek: the `chat_completions` block in 27c79af |
| Seats | `agw routes` `hermes.{brain,compress,title,approval,vision}` | config.yaml carries them as literals; **`make seats-check`** (in `make check` and `make status`) fails when model, effort, `api_mode` or base URL drift from the route table. A tier change in agw = edit config.yaml + restart. The routes' GPT `fallback` field is ignored on purpose |
| Former brains | Haiku 5.5 EU on IU direct (2026-10-08 → 10-20); `deepseek-v4.1-flash` (2026-10-20 → 11-04) | DeepSeek: 15/15 at every effort, 1.0 M window, `/responses` 404s — `chat_completions` is its only wire |
| Pricing line | **100k input tokens** | Haiku 5.5 bills the *whole request* at 5x above it (`agw routes`, `longPromptTokens`). **Accepted by the owner (2026-11-04)**: long threads cost more and that is fine, so compaction is late (650k), not under the line |
| Context, Haiku 5.5 | 1,000,000 (pinned) | the gateway's `/models` advertises 200k; the pin wins, `agent.context_pin` logs a harmless warning per run |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by the IU LiteLLM gateway |

**Every model call goes through the local inference gateway** (`127.0.0.1:7794`, agent-workflows):
`ANTHROPIC_BASE_URL` is its `/anthropic`, the key is the door token. Spec:
`agent-workflows/docs/gateway.md`. **Hermes is Claude-only (owner decision 2026-11-15):** the brain,
`compression` (agw's `cheap.summarize`), `title_generation` (`cheap.title`, effort `none`), `approval`
and `vision` (Haiku 5.5, `none`) all run on the Anthropic leg, so the credit pools pay, and the gateway
itself falls back to IU's `/anthropic` when no pool has credit (agent-workflows `docs/gateway.md`
§Picking a pool). There is no GPT failover: IU's OpenAI and Anthropic paths share one personal key
and cap, so it added no budget, only coverage of "IU Claude down, IU GPT up". The leg needs a
`session_affinity_header: x-agw-session` entry (`providers.gateway-anthropic`): the
lookup is by route URL, so a leg without an entry would send no session — the gateway binds a
session to one credit org, and **prompt caches are per org**, so no session means no cache.
Byte-exact passthrough: the `cache_control` markers Hermes sets are the cache. `prompt_caching.cache_ttl: auto` =
1h for human-paced sources (Iris, CLI, desktop), 5m for cron/api. Verify in `agent.log`:
`cache=N/M (100%)` from the second call on. **Select the leg by `model.provider`
(`gateway-anthropic`), not `model.base_url`**; the native leg returns `msg_` ids (`chatcmpl-` ids
would mean the chat-completions shim).

**`model.api_mode: anthropic_messages` carries the effort** through upstream's `_thinking_kwargs`
(Haiku 5.5+ is adaptive; `_is_pre_thinking_haiku` is false) — no local patch. There is no
Hermes-side fallback: a 402/5xx from the gateway is a turn error, not a failover.
- **`agent.log` is not rotated per process** — slice every read at the current process start
  (`pgrep -f "hermes_cli.main gateway run"` → `ps -o lstart=`). `skills/hermes-gateway/` owns
  this. **Hermes may not restart its own gateway.**
- **The live key is `agent.reasoning_effort`, not `model.reasoning_effort`** (the latter was a
  dead, never-read mirror and has been removed from `config.yaml`).
- **Compaction triggers at 650,000 tokens** (absolute, ratio 0.65 of the 1M pin agrees; the *lower* of the two governs). Owner decision 2026-11-04 — an earlier 90k guess to stay under Haiku's 100k 5x line cut threads short and was reverted. Above 100k each request bills at 5x; prompt caching (reads at 0.1x of the base rate) keeps that bounded. Compaction invalidates the cached prefix once per compaction.

**Auxiliary lanes are separately routed, not the brain** — all on the Anthropic leg, `provider`
`custom` so the auxiliary client never reaches for `~/.claude` OAuth: `compression` (Haiku 5.5
`high`), `title_generation` (Haiku 5.5 `none`; the CLI exits before the async title lands, the
gateway does not), `approval` (Haiku 5.5; 0.9 s native vs 3.0 s through the OpenAI shim; Haiku 4.5
approved `rm -rf ~/SourceRoot` in a probe, 5.5 denied it) and `vision` (Haiku 5.5 `none`; Sonnet 5.5 `medium` until 2026-11-16).
`auxiliary.web_extract` and `auxiliary.session_search` are gone — upstream stopped reading them
(`config_defaults.py`: "no longer use an auxiliary LLM... ignored"), so the blocks were dead
weight. **`delegation.*` (subagent routing) exists but is unused** — a Hermes child gets no
`.claude/rules`/`skills`/PR artifact, so repo work stays filed as issues. **Core-tool
deferral is on** (`tools.tool_search.enabled: auto`) — measured −19.8% off the cached tool prefix
every turn; if Hermes ever claims it can't schedule something, check `cronjob_manage` isn't
wrongly deferred rather than disabling the feature.

Full numbers, lane rationale, deferral measurement: **`docs/model-context-reasoning.md`**.
