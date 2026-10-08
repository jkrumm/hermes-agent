# Hermes brain → Claude Haiku 5.5 EU on the native Anthropic leg

**Goal:** the live Hermes gateway runs its brain (and, by inheritance, delegation) on
`claude-haiku-5-5-eu` through the IU **Anthropic Messages** route at `reasoning_effort: high`,
with the effort provably reaching the wire, prompt caching working, and a multi-turn tool loop
verified — without updating upstream Hermes (stay on `d3b25b52ad` / v0.21.4; fix via a local patch).
**Gate:** `make patch-check` + `make status` green, plus the live verification in Wave 1's last steps.

## Evidence this rests on (measured in modelpick 2026-10-08 — do not re-derive)

- `claude-haiku-5-5-eu` → AWS Bedrock **eu-west-1** (gateway header `x-middleware-forwarded-server`).
  Callable on `/anthropic/v1/messages` but **not listed in `/v1/models`** — probe by name.
  `claude-haiku-5-5` (no suffix) is Bedrock **us-east-1** — never use it here.
- Anthropic leg vs OpenAI-compat leg for Haiku 5.5: OpenAI leg is ~3× worse TTFT and ignores
  `reasoning_effort: none`. Native leg honours every effort level.
- Effort ladder (modelpick `bench-fast`, 5 graded tasks × 3 repeats, EU id): `high` 15/15 at
  ~1.6 s median; `medium` 14/15; `xhigh` passes but long outputs think 50–100 s (and Anthropic
  documents an xhigh multi-turn empty-reply bug); `max` exceeds 120 s on long outputs. → **high**.
- Thinking counts toward `max_tokens`: below ~16k output budget, high-effort calls can starve
  (HTTP 200, empty text, `stop_reason: max_tokens`). Haiku 5.5 output cap is 128k.
- Haiku 5.5 API: adaptive thinking on by default, `output_config.effort` low|medium|high|xhigh|max
  (default **medium**), `budget_tokens` → 400, non-default temperature → 400, assistant prefill → 400.
  Pricing doubles+ above 100k input tokens ($0.10/$0.50 → $0.50/$2.50 per MTok).

## Wave 1 — patch, switch, verify            <!-- status: active -->

- [ ] **Patch the haiku guard.** `~/.hermes/hermes-agent/agent/anthropic_adapter.py` `_thinking_kwargs()`
      has `if "haiku" in model.lower(): return {}` — Haiku 5.5 would get NO effort and silently run at
      `medium`. Narrow it to legacy Haikus (3.x / 4.x) so `claude-haiku-5-5*` reaches the adaptive branch
      (`thinking: {type: adaptive, display: summarized}` + `output_config.effort`). Also check in the same
      file: `_supports_adaptive_thinking`, `_accepts_thinking_disable`, `_MANDATORY_THINKING_CLAUDE_SUBSTRINGS`,
      and that `_get_anthropic_max_output()` resolves `claude-haiku-5-5-eu` to ≥16k (ideally 64k–128k),
      not an 8k/4k legacy substring match. Capture as a new `patches/anthropic-adapter-haiku-5.patch`
      (one patch file per upstream file — see `docs/patches.md`), `# LOCAL MODIFICATION` marker, and a
      `docs/patches.md` entry. `make patch-check` must list it applied.
- [ ] **Check the third-party-endpoint path.** The adapter strips thinking signatures for third-party
      `base_url`s. Confirm what that does to replayed thinking blocks in a tool loop on this gateway
      (dropped cleanly vs 400 vs silently degrading). Fix in the same patch only if it breaks.
- [ ] **Switch config.yaml.** Brain → `claude-haiku-5-5-eu`, `api_mode: anthropic_messages`, base URL =
      the IU Anthropic route (same `${ANTHROPIC_BASE_URL}` / `${ANTHROPIC_API_KEY}` the `auxiliary.approval`
      slot already uses — keep `provider: custom` so nothing reaches for ~/.claude OAuth),
      `agent.reasoning_effort: high` (already high — confirm it maps), `context_length: 1000000`.
      Remember the load-bearing gotcha from the DeepSeek switch: `resolve_runtime_provider()` reads
      `api_mode` from the **named-provider block**, not top-level `model.api_mode` — set it where it is
      actually read. Delegation inherits the brain (`model: ''`) — confirm. Leave `fallback_providers`
      (gpt-6-luna), compression, title and approval slots unchanged.
- [ ] **Restart and verify live** (`launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`, then
      `make status`). Prove, from gateway logs or a request trace — not from config — that a real brain
      turn: (1) hits `/anthropic/v1/messages` with model `claude-haiku-5-5-eu`, (2) carries
      `output_config.effort: "high"`, (3) runs a multi-turn tool loop (≥2 tool calls) end to end,
      (4) shows `cache_read_input_tokens > 0` on a later turn, and (5) did NOT silently fail over to
      gpt-6-luna. Any one missing = not done.
- [ ] **Record and report.** Update AGENTS.md / `docs/model-context-reasoning.md` where they name the
      brain model. Report the 100k-input price cliff against the current compression trigger
      (240k) as a number for the owner to decide — do not change the threshold.
**Left behind:**

## Scope limits

- Do NOT run `hermes update` / pull upstream. Do NOT touch modelpick (the orchestrator updates
  `src/db/deployments.ts` after this wave). Do NOT commit `skills/verify/references/agent-claim-verification.md`
  — it was already dirty before this wave and is someone else's.
- Do not spawn a next wave — the orchestrator tab reviews the close-out.
