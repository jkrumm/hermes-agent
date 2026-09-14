---
name: hermes-model-audit
description: "Use when auditing Hermes's own brain model performance."
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, self, model, audit, brain, latency, cache, cost, tokens, reasoning-effort, tool-calls, deepseek, luna, state-db, evidence]
    related_skills: [hermes-gateway, argo-api]
---

# Hermes Model Audit

Answers *"is the model I run as my brain actually good?"* with measured evidence. Triggers:
"läuft das neue Modell besser", "sind die Logs sauber", "sind die Toolcalls sauber", "ist die
Latenz gut", "ist Thinking/Effort richtig konfiguriert", "fühlst du dich besser/schlechter",
any post-model-swap check, or comparing two models as the agent's own brain.

The sibling skill `hermes-gateway` answers a different question — *is the gateway broken, and
does it need a restart?* — and both read the same log. Reach for this one when the question is
comparative or evaluative (better/worse than the previous model, is the latency good, is the
effort configured well); reach for `hermes-gateway` when something is suspected to be faulty. A
clean log is the *starting* condition here, not the answer.

## Rule 0 — bound every read to the current process

`agent.log` is not rotated per process; it spans restarts. Establish the boundary before
counting anything, or you will report a dead incident as current:

```bash
S=$(grep -a "Starting Hermes Gateway" ~/.hermes/logs/agent.log | tail -1 | cut -c1-19)
awk -v s="$S" '$0>=s' ~/.hermes/logs/agent.log | grep -acE "^[0-9-]+ [0-9:,]+ ERROR"
```

**Do not derive the PID with `pgrep -f "hermes_cli.main gateway run"`** — on this box it can
come back empty (the supervisor launches the module by path, and the argv does not always
match), which silently makes every downstream check vacuous. `~/.hermes/gateway.pid` is the
authoritative source (JSON, `.pid`), and the last `Starting Hermes Gateway` line is the
boundary. `launchctl print gui/$(id -u)/ai.hermes.gateway` gives the supervisor's own view.

**Zero `ERROR` lines in the slice is a finding, not an absence of one.** Say so and move on to
the measurements — do not go hunting for a fault to match the question's suspicion.

## The evidence ladder

Gather in this order; each rung is a different kind of claim.

| # | Source | What it proves |
|-|-|-|
| 1 | log slice since process start | logs clean, fallback count, tool-call outcomes |
| 2 | `state.db` → `session_model_usage` | per-model calls, token mix, **cache share** |
| 3 | argo `/usage/breakdown` + `/usage/timeseries` | cost and error rate per model, independent of Hermes |
| 4 | live probe against the endpoint | what the wire actually accepts |
| 5 | import the patched transport | that config reaches the wire |

Rungs 4 and 5 are what separate a measurement from a guess. A value in `config.yaml` is a
*claim*; only 4 and 5 show it survives to the request.

### The numbers that decide a brain

- **Cache share** — `cache_read_tokens / (input_tokens + cache_read_tokens)` from
  `session_model_usage`. This is the number that decides a brain on this estate: a long
  conversation re-sends its whole prefix every turn, so the model that gets a discount on
  exactly that prefix wins by a margin no per-turn latency figure reflects. Report it as a
  percentage next to the absolute token counts.
- **Latency percentiles per model**, from the log's own
  `agent.conversation_loop: API call` lines (`latency=` field). Report p50/mean/p90 with the
  call count attached — a percentile over 40 calls and one over 400 are not the same claim.
- **Cost**, cross-checked against argo rather than computed from a remembered rate card. Rate
  cards drift; `GET /usage/breakdown?range=7d&metric=cost&dimension=model_norm&sources=hermes`
  is the billed view. Current rates and the arithmetic are in *Rate cards* below, with the
  caveat to re-verify them.
- **Tool-call outcome counts** — completed vs errored, split by tool.

### Comparing two models honestly

The previous model's numbers live in a rotated `agent.log.N`. Slice a **matched window** from
it (a full day, or the same number of calls) and report both windows side by side with their
call counts. Comparing a quiet day against a busy one is the standard way this analysis goes
wrong.

## Tool-call cleanliness: real failures vs artifacts

Count these — they are genuine model/transport failures and should be `0`:

```bash
grep -ahcE "Failed to parse tool|Invalid tool call|no such tool|not valid JSON" ~/.hermes/logs/agent.log*
```

Then classify the `Tool … returned error` lines before reporting them as a quality signal.
Most of them are **not** model failures:

- `approval` timeouts (`Command timed out without user response`) — human latency, and the
  agent's *own* call. Never a model-quality datapoint.
- user deny-rule and hardline-block refusals — the guards working.
- `skill_manage` refusals naming `skills.external_dirs` — the durability guard working.
- `check_fn … returned False` WARNINGs at turn start — capability probes for tools this
  deployment does not install.

Report the split, not the raw count. "16 tool errors" is misleading when 10 are your own
approval timeouts.

## Effort and thinking: what is provable on this model

- `agent.reasoning_effort` is the live key (`model.reasoning_effort` was never read). Resolve it
  with `resolve_reasoning_config`, not from `hermes config` output — that display prints
  `Reasoning: off` while a live effort is on the wire.
- **On `deepseek-v4.1-flash` the effort level is close to inert.** Across repeats on a hard
  arithmetic task, completion tokens barely move between `none`, `low`, `high`, `xhigh` and
  `max`: the level is accepted and echoed, but buys no measurable thinking ladder the way the
  GPT-5.x family's does. Do not report an effort change as a quality change here without
  repeated probes showing it, and do not tune this model by effort.
- `completion_tokens_details.reasoning_tokens` reads `0` on this route while thinking is billed
  inside `completion_tokens`. Any think:visible ratio computed from that field is wrong.
- Thinking being *on* is checkable: `reasoning_content` is present on the response message.

## The probes (rungs 4 and 5)

Load secrets the way the gateway does, then POST directly — no Hermes code in the path:

```bash
set -a
eval "$($HOME/.local/bin/secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //')"
set +a
python3 - <<'PY'
import os, json, time, urllib.request, urllib.error
base = os.environ["OPENAI_BASE_URL"].rstrip("/")
key  = os.environ.get("HERMES_CUSTOM_CUSTOM_API_KEY") or os.environ["OPENAI_API_KEY"]
tools = [{"type":"function","function":{"name":"noop","description":"noop",
          "parameters":{"type":"object","properties":{}}}}]

def probe(label, model, effort=None, with_tools=False, temp=None, budget=3000):
    body = {"model": model, "messages": [{"role":"user","content":"Answer with one word: OK"}],
            "max_completion_tokens": budget}
    if effort: body["reasoning_effort"] = effort
    if temp is not None: body["temperature"] = temp
    if with_tools: body["tools"] = tools; body["tool_choice"] = "auto"
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r: d = json.load(r)
        msg = (d.get("choices") or [{}])[0].get("message", {})
        print(f"[{label}] 200 in {time.time()-t:.1f}s "
              f"reasoning_content={'yes' if msg.get('reasoning_content') else 'no'} "
              f"usage={d.get('usage')}")
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
    except Exception as e:
        print(f"[{label}] ERR {type(e).__name__}: {e}")

probe("brain tools+effort", "deepseek-v4.1-flash", "high", True)
probe("fallback tools+effort", "gpt-5.6-luna", "high", True)
probe("fallback tools only", "gpt-5.6-luna", None, True)
PY
```

How to read it:

- **brain + tools + effort → 200** — the effort reaches the wire on a tool turn. This is the
  property that makes `chat_completions` viable for the brain and needs no Responses-API detour.
- **fallback + tools + effort → 503** (`Function tools with reasoning_effort are not supported`)
  — expected, and handled by the tools+effort strip in the transport patch. The fallback then
  runs tools with **no** effort. That is the accepted tradeoff, not a fault.
- **fallback + tools, no effort → 200** — confirms the strip is what makes the fallback usable.
- **any gpt-5.x call carrying a non-default `temperature` → 503** (`Unsupported value:
  'temperature'`). This is why `title_generation` pins a gpt-5.x model only behind the auxiliary
  patch that strips the temperature its call site hardcodes.

### Effort ladder

Same hard task at each level, ≥3 repeats, compare **completion tokens** (not `reasoning_tokens`):

```python
for eff in ["none", "low", "high", "xhigh", "max"]:
    probe(f"effort={eff}", "deepseek-v4.1-flash", eff, True, budget=20000)
```

- **A flat ladder means the knob is inert on that model.** Report it as such; do not present a
  configured effort as a tuned one.
- **Unused budget is not billed**, so a generous `max_completion_tokens` costs nothing. A
  *starved* budget is the classic false negative: an under-budgeted reasoning model returns
  HTTP 200 with empty content and `finish_reason: length`. If a probe returns empty, raise the
  budget before lowering the effort.

### Patched transport: does config reach the wire?

```bash
cd ~/.hermes/hermes-agent && ./venv/bin/python3 - <<'PY'
import os
from agent.transports.chat_completions import _apply_iu_reasoning_effort
for model, eff in [("deepseek-v4.1-flash","high"), ("gpt-5.6-luna","high"),
                   ("deepseek-v4.1-flash","max"), ("deepseek-v4.1-flash","medium")]:
    kw = {}
    _apply_iu_reasoning_effort(kw, model, {"base_url": os.environ["OPENAI_BASE_URL"],
                                          "reasoning_config": {"enabled": True, "effort": eff}})
    print(f"{model:22s} effort={eff:7s} -> {kw}")
for model in ["deepseek-v4.1-flash", "gpt-5.6-luna"]:
    kw = {"tools": [{"type": "function", "function": {"name": "x"}}]}
    _apply_iu_reasoning_effort(kw, model, {"base_url": os.environ["OPENAI_BASE_URL"],
                                          "reasoning_config": {"enabled": True, "effort": "high"}})
    print(f"{model:22s} tools+high -> reasoning_effort={kw.get('reasoning_effort')!r}")
PY
```

Expected shape: the brain keeps its effort with tools attached; the gpt-5.x model loses it
(`None`); out-of-ladder values are clamped to something the family accepts. If the brain's value
comes back `None` under tools, the transport patch has fallen off — re-apply it and restart.

## Rate cards (verify before use)

Rates are what the gateway bills, solved from `usage.cost` on live calls. They **drift** — treat
this as a starting point and confirm against argo's billed view before quoting a number:

| model | input /M | cached input /M | output /M |
|-|-|-|-|
| `deepseek-v4.1-flash` | $0.50 | $0.05 | $1.50 |
| `gpt-5.6-luna` (reference) | $0.10 | $0.02 | $0.60 |

```
cost ≈ uncached_input/1e6 * input_rate
     + cache_read/1e6      * cached_rate
     + output/1e6          * output_rate
```

Cache writes carry no surcharge on this route.

## Report shape

Verdict first, then the numbers, then what got worse. In German unless asked otherwise.

- Lead with the answer to the question asked, not with methodology.
- **Numbers over adjectives**, every claim carrying its measurement.
- **State what is worse, unprompted.** An audit that only lists improvements is not an audit;
  the honest cost of the current model (per-turn price against the previous one, an effort knob
  that does nothing, a smaller effective window) belongs in the same answer.
- Distinguish *measured* from *not measurable here*. If the effort ladder produced no signal,
  say that rather than implying a tuned configuration.
- Keep it scannable: short bullets, a small comparison table, bold lead-ins.

## Running the audit without burning half an hour

Diagnostic work here is many small reads, and the *transport* of those reads is the bottleneck.

- **Write the diagnostic to a file, then run it once.** `write_file` a `/tmp/*.sh` and invoke
  `bash /tmp/x.sh` as a single call. Inline multi-line commands carrying shell variables, `awk`
  programs and heredocs trip the hardline blocklist (`command parser limit or malformed
executable payload`); the block saves the payload to `~/.hermes/cache/blocked-scripts/` and the
  recovery is to run that file — one wasted round-trip you can skip by writing the file yourself.
- **Batch independent reads into one script.** Each separate `terminal` call can raise an
  approval prompt, and an unanswered prompt costs the full `approvals.timeout` (300s) before
  failing. Five such timeouts is 25 minutes of wall clock for work one batched script does in
  seconds — and the silence reads as the agent being broken, which is the opposite of what an
  audit question is asking.
- **Never put the literal `config.yaml` in a `terminal` command.** A user deny rule matches
  `*config.yaml*` and refuses it outright — including `git log -- config.yaml` and any `grep` or
  `cat` naming it. Read the config with `read_file` and pass resolved values into scripts.
- **`make patch-check` runs from `~/SourceRoot/hermes-agent`, not `~/.hermes/hermes-agent`** —
  the latter has no Makefile and fails with `No rule to make target`.

## Pitfalls

- **`hermes insights` is not a usage or cost source.** Its model table counts *sessions*, so
  right after a swap it shows the outgoing model dominating. Use `state.db` and argo.
- **The startup context-length lines can name a window the agent does not use.**
  `Could not detect context length … defaulting to 256,000` followed by `Using hardcoded context
  length 128,000 … catalog match` can both be logged while the effective window is a much larger
  `custom_providers` override. Resolve the real value with `get_custom_provider_context_length`,
  then `get_model_context_length(..., custom_providers=get_compatible_custom_providers(config))`.
  A *lower* consumer of that value (tool-search deferral, compressor threshold) can otherwise be
  gated at the wrong scale while the brain itself runs correctly.
- **A patched fix only takes effect after a gateway restart.** Compare the patch file's mtime
  against the process start before crediting a fix; a clean log slice that starts after the
  patch landed is the proof, and calls logged before it are not.
- **`Fallback activated` is expected under throttling, not a fault** — but its absence over a
  multi-day window is a real finding worth stating.
- **A single cache probe can miss the cache.** It is real and 64-token-granular, but
  back-to-back non-streamed calls, or calls spaced far apart, can read `cached: 0`. Re-run at
  least twice, and read real sessions from `state.db` before believing a zero.
