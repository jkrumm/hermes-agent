# The 2026-08-14 Luna routing outage, and the 2026-08-16 misdiagnosis of it

Two incidents, and the second one is the more instructive.

## What actually happened on 2026-08-14

`hermes update` to v0.20.1 dropped `patches/runtime-provider-iu-responses-api.patch`.
Without it, upstream refuses to honour a configured `api_mode` on an unrecognised
host and downgrades silently:

```
12:34:34 INFO hermes_cli.runtime_provider: Ignoring persisted custom
  api_mode=codex_responses for non-OpenAI endpoint https://…/openai/v1
```

Every turn then went out on `/v1/chat/completions` carrying both function tools and
`reasoning_effort: high`, which the endpoint refuses:

```
12:25:21 ERROR agent.chat_completion_helpers: Streaming failed before delivery:
  Error code: 503 … "Function tools with reasoning_effort are not supported for
  gpt-5.6-luna in /v1/chat/completions. To use function tools, use /v1/responses
  or set reasoning_effort to 'none'."
12:25:34 INFO agent.chat_completion_helpers: Fallback activated:
  gpt-5.6-luna → claude-sonnet-4-6-eu (custom)
```

Three retries per turn, then the whole conversation on the Anthropic fallback — with
`hermes gateway status`, `/health`, launchd and the Slack connection all green
throughout. **Supervisor health told you nothing about request health.**

At 12:44:09 a line reads `Fallback activated: gpt-5.6-luna-does-not-exist →
claude-sonnet-4-6-eu`. That is the deliberate probe CLAUDE.md prescribes for proving
the fallback chain still engages after touching either `api_mode`. It is evidence of
a test, not of a broken model name.

The patch was re-applied and the gateway restarted at **12:44:55**. From that
timestamp to 2026-08-16 19:15 the log carries **zero** `ERROR` lines.

## What happened on 2026-08-16

Asked *"I see soo many gateway shutting down messages. Are you healthy?"*, the agent:

1. Correctly reported the process healthy — PID, uptime since Aug 14 12:44, `/health`
   200, launchd `running`.
2. Then read the error log **without bounding it to that process start**, found the
   12:25–12:30 burst, and reported it as *"aktuelle Model-Backend-Fehler"*.
3. Inferred, with no evidence, that *"der laufende Gateway verwendet für manche Turns
   offenbar noch den alten `/v1/chat/completions`-Pfad"* and that this looked like *"ein
   alter/stale Gateway-Prozess"*.
4. Asked Johannes to run `hermes gateway restart` on a headless machine, to fix
   something that had been fixed two days earlier.
5. Stated that the fix stays *"im nativen Hermes-Pfad: `codex_responses` ist eine
   eingebaute Hermes-API-Mode, kein eigener Patch"* — and that if it did not work,
   *"bleiben wir beim Standard und behandeln es als Hermes-Bug statt lokal
   herumzupatchen"*.

Point 5 is the dangerous one. The mode is native; **reaching it on this endpoint is
not**. Acting on that sentence means removing the patch that is the actual fix. The
distinction to hold: `codex_responses` is upstream's, the *routing to it for
this endpoint's host* is ours, and upstream logs its refusal in one
line that says so.

Points 2–4 all collapse into Rule 0 of the skill: the report would have been
"everything is green, the errors you can see are from before the last restart" if the
log had been sliced at the process start before being counted.

## The evidence that settles it, in order

```bash
# 1 — process boundary
pgrep -f "hermes_cli.main gateway run"
ps -o lstart=,etime= -p <pid>

# 2 — errors since that boundary (expect 0)
awk '/^2026-08-14 12:44:55/,0' ~/.hermes/logs/agent.log | grep -cE "^[0-9-]+ [0-9:,]+ ERROR"

# 3 — the downgrade tell must be absent since the boundary
grep -a "Ignoring persisted custom api_mode" ~/.hermes/logs/agent.log | tail -3

# 4 — the patch that prevents it
cd ~/SourceRoot/hermes-agent && make patch-check

# 5 — positive proof of the resolved route
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
import os; from hermes_cli.runtime_provider import _detect_api_mode_for_url as d
base = os.environ['OPENAI_BASE_URL']                       # …/openai/v1
print(d(base), d(base.rsplit('/openai/', 1)[0] + '/anthropic'))"
# -> codex_responses anthropic_messages

# 6 — effort is read from agent.*, not model.*
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
from hermes_constants import resolve_reasoning_config; import yaml, os
print(resolve_reasoning_config(yaml.safe_load(open(os.path.expanduser('~/.hermes/config.yaml')))))"
# -> {'enabled': True, 'effort': 'high'}
```

Steps 5 and 6 are the ones worth adding to any future report: they are the only
checks that prove the live route rather than describing the log.

## Endpoint facts, so they are not re-derived

- `gpt-5.6-luna` accepts `none, low, medium, high, xhigh`. `max` is refused here
  despite the model card; `minimal` is not a value for this family.
- The Anthropic leg accepts `none, low, medium, high` — `xhigh` is refused by
  LiteLLM, which is why `patches/transport-iu-reasoning-effort.patch` clamps it.
- The fallback entry spells `api_mode: chat_completions` explicitly, and must keep
  doing so: an explicit `api_mode` on a `fallback_providers` entry beats URL
  detection, and `claude-sonnet-4-6-eu` 404s on the Responses leg.
- Reasoning effort on this endpoint exists **only** on the Responses API once tools
  are in play. There is no configuration of `chat_completions` that has both.

Never print API keys, `.env` contents or the raw `secrets-run` output when reporting
any of this. `hermes config` masks; raw file reads do not.
