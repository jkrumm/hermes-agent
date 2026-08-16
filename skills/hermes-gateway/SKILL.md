---
name: hermes-gateway
description: Diagnose Hermes's own gateway — "are you healthy", "why do I see so many gateway shutting down messages", model-routing failures, reasoning-effort or function-tool rejections from the IU endpoint, Slack or API-server connectivity, a config change that appears not to take effect. Separates supervisor health from request health and forbids reporting a stale log line as a current fault.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, gateway, self, health, healthy, launchd, shutdown, sigterm, restart, model, routing, api-mode, responses, chat-completions, reasoning-effort, luna, fallback, slack-connection, api-server]
    related_skills: [homelab-ops, argo-api]
---

# Hermes Gateway

This skill is about **Hermes's own process on the Mac Mini**, not the homelab or the
VPS. Infrastructure alerts, containers and Uptime Kuma belong to `homelab-ops` and
its bounded `hermes-ops.sh` verbs. `hermes-ops.sh` deliberately **excludes**
`ai.hermes.gateway` from `launchd-repair` — Hermes repairing its own supervisor is a
human action, so this skill diagnoses and escalates; it never restarts.

## Rule 0 — bound every log read to the current process

**This is the rule that exists because it was broken.** On 2026-08-16 the whole of
`~/.hermes/logs/agent.log` was read, a burst of 503s from 2026-08-14 12:25 was
reported as *"aktuelle Model-Backend-Fehler"*, and Johannes was asked to restart a
gateway that had already been restarted with the fix two days earlier. The errors
were real; they were also 48 hours dead. `agent.log` is not rotated per process — it
spans restarts, so a raw `tail`/`grep` mixes the current process with every previous
one.

Establish the boundary first, then never quote a line older than it:

```bash
GWPID=$(pgrep -f "hermes_cli.main gateway run" | head -1)
ps -o lstart=,etime= -p "$GWPID"          # when this process actually started
grep -a "Starting Hermes Gateway" ~/.hermes/logs/agent.log | tail -3
```

Then slice the log at that timestamp before counting anything:

```bash
awk '/^2026-08-14 12:44:55/,0' ~/.hermes/logs/agent.log \
  | grep -acE "^[0-9-]+ [0-9:,]+ ERROR"
```

Zero errors across two days of tool-heavy traffic is a *finding*. "The log contains
errors" is not. If the count is zero, say the gateway is healthy and stop — do not
go looking for a fault to match the user's suspicion.

Same rule for the shutdown question. `gateway-shutdown-diag.log` and
`gateway-exit-diag.log` are append-only across the machine's whole life; a wall of
`SIGTERM` entries with a newest timestamp older than the current process start is
history, not a crash loop. Read the exit, not the signal name —
`homelab-ops/references/launchd-restart-triage.md` has the table.

## A new or renamed skill needs a gateway restart

`make setup` only creates the symlink. The skills index in the system prompt is
cached **in-process** (`_SKILLS_PROMPT_CACHE`, `agent/prompt_builder.py`) under a key
built from directory paths only — no mtime, no manifest. Nothing invalidates it
except an explicit `clear_skills_system_prompt_cache()`, which only
`skill_manager_tool` calls. So a long-running gateway keeps serving a skills list
from whenever it started.

The disk snapshot below it (`~/.hermes/.skills_prompt_snapshot.json`) *is* manifest-
checked and self-heals, and `hermes skills list` runs in a fresh CLI process — both
will happily show the new skill while the running gateway still cannot see it. Do not
take either as proof. After adopting or renaming a skill, restart, then verify
against a rebuilt prompt:

```bash
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
from agent.prompt_builder import build_skills_system_prompt as b
print('<skill-name>' in b())"
```

## Health is four independent checks

A green one above does not imply a green one below. Report each separately.

| Layer | Check | Green means |
|-|-|-|
| Supervisor | `launchctl print gui/$(id -u)/ai.hermes.gateway` | launchd holds the job; `runs` climbing is not itself a fault |
| Process | `hermes gateway status`, `ps -o lstart= -p <pid>` | a PID exists and how long it has held |
| Listener | `lsof -nP -iTCP:8642 -sTCP:LISTEN` | bound — and to the **tailnet IP**, not loopback (that is deliberate) |
| Request path | log slice since process start; `/health` | requests actually reach the model |

`/health` needs no auth. `/v1/models` needs the bearer; a 401 there proves only that
the listener is reachable, never that the model route works.

## Model routing on the IU endpoint

The one failure mode worth memorising:

> Function tools with reasoning_effort are not supported for gpt-5.6-luna in
> `/v1/chat/completions`. To use function tools, use `/v1/responses` or set
> reasoning_effort to 'none'.

Hermes always sends tools, so this 503s **every** turn, burns the retry budget and
lands the conversation on the Anthropic fallback while the gateway looks perfectly
healthy from the outside. Diagnosis tell in the log:
`Fallback activated: gpt-5.6-luna → claude-sonnet-4-6-eu` on every turn.

**Do not fix this by lowering `reasoning_effort`.** The correct route is
`api_mode: codex_responses`, which is already in `config.yaml`.

**And on this endpoint that setting alone is not enough — it needs the local patch.**
`codex_responses` is a native Hermes mode, but upstream refuses to auto-detect it for
an unrecognised host and silently downgrades to `chat_completions`, logging:

```
Ignoring persisted custom api_mode=codex_responses for non-OpenAI endpoint https://…/openai/v1
```

That line is the whole diagnosis. It means `patches/runtime-provider-iu-responses-api.patch`
has fallen off — which is exactly what a `hermes update` does. Verify with:

```bash
cd ~/SourceRoot/hermes-agent && make patch-check
```

Never advise "stay on the standard Hermes path, don't patch" for this symptom: on
this machine the patch **is** the standard path, and dropping it is what caused the
outage. `~/SourceRoot/hermes-agent/CLAUDE.md` § "Local Modifications to Upstream" is
the contract; `/hermes-update` re-applies every patch in `patches/`.

Prove the route positively rather than inferring it from log prose:

```bash
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
import os; from hermes_cli.runtime_provider import _detect_api_mode_for_url as d
print(d(os.environ['OPENAI_BASE_URL']))"   # -> codex_responses
```

`reasoning_effort` lives at **`agent.reasoning_effort`**, not `model.reasoning_effort`
— only the `agent` key is read. Check it the same way:

```bash
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
from hermes_constants import resolve_reasoning_config; import yaml, os
print(resolve_reasoning_config(yaml.safe_load(open(os.path.expanduser('~/.hermes/config.yaml')))))"
```

## False positives that look like faults

- **`gpt-5.6-luna-does-not-exist`** in a fallback line is a *deliberate probe*, run to
  prove the Anthropic fallback still engages. It is documented in CLAUDE.md. Never
  report it as a broken fallback model.
- **The fallback entry uses `chat_completions`.** That is correct and intentional —
  `claude-sonnet-4-6-eu` 404s on the Responses leg. It says nothing about how the
  primary Luna route is configured.
- **`check_fn … returned False`** WARNINGs at every turn start (browser, computer-use,
  image-gen, kanban) are ordinary capability probes for tools this deployment does not
  install. Noise.
- **Curator refusals** — `Refusing background curator patch for skill '…': the skill
  lives in skills.external_dirs` — are the durability guard working, not an error.

## Restart boundary

Hermes may not restart its own gateway: a `hermes gateway restart` issued from a
terminal call inside that gateway would terminate the process running the command,
and it is blocked. That refusal is correct — do not look for a way around it.

Nor is it a `claude-dispatch` job. Dispatch hands a *repo* episode to Claude Code in
an isolated worktree; it has no lifecycle authority over this machine's launchd, and
`hermes-ops.sh` excludes `ai.hermes.gateway` for the same reason. Asking Claude Code
to run it would be improvising an infrastructure mutation through a tool built for
code changes.

**The Mac Mini is headless — "run it in a terminal" is not an escalation on its own.**
State the finding, then hand over one exact command:

```bash
hermes gateway restart
```

If nobody is at a machine, enqueue it instead of asking into the void:

```bash
~/SourceRoot/dotfiles/scripts/ask-human.sh ask 'restart the Hermes gateway' --cmd 'hermes gateway restart'
```

**Before escalating, be sure a restart is actually the fix.** A restart only helps
when the running process is genuinely stale relative to config or patched source. If
the log slice since process start is clean, the answer is "nothing to do", not "please
restart".

## Verification checklist

Do not report a fix until all of these hold:

- process start timestamp recorded, and the log read is sliced at it
- zero `ERROR` lines in that slice
- listener present on the configured tailnet address and port
- `/health` returns 200
- `make patch-check` green
- `_detect_api_mode_for_url` returns `codex_responses` for the OpenAI leg
- one real tool-using turn completes without a `Fallback activated` line

See `references/model-routing.md` for the 2026-08-14 incident in full.
