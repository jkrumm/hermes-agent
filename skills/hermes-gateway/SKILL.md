---
name: hermes-gateway
description: Diagnose Hermes's own gateway — "are you healthy", "why do I see so many gateway shutting down messages", model-routing failures, reasoning-effort or function-tool rejections from the IU endpoint, API-server connectivity, a config change that appears not to take effect. Separates supervisor health from request health and forbids reporting a stale log line as a current fault.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes, gateway, self, health, healthy, launchd, shutdown, sigterm, restart, model, routing, api-mode, responses, chat-completions, reasoning-effort, api-server]
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

Every model call goes through the local inference gateway (`curl -s 127.0.0.1:7794/health`, LaunchAgent
`com.jkrumm.agent-workflows-gateway`) on its Anthropic leg. A gateway that is down fails every lane
at once, and a `401` means the `hermes=` door-token line is missing. Hermes is **Claude-only**: the
gateway spends the Claude credit pools first and falls back to IU's `/anthropic` itself; there is no
Hermes-side fallback model and no OpenAI leg.

The brain (`claude-haiku-5-5`) runs `api_mode: anthropic_messages` with `model.provider:
gateway-anthropic`; upstream's `_thinking_kwargs` sends `agent.reasoning_effort: high` as adaptive
thinking, with no local patch. Prove it with `HERMES_DUMP_REQUESTS=1 hermes chat -q …` →
`~/.hermes/sessions/request_dump_*.json`, and in `agent.log` by `msg_` response ids (a `chatcmpl-`
id means the chat-completions shim) and `cache=N/M` from the second call on. Every auxiliary lane
(`compression`, `title_generation`, `approval`, `vision`) calls the same `/anthropic` base URL.
`make seats-check` pins all five seats to `agw routes` `hermes.*`.

`reasoning_effort` lives at **`agent.reasoning_effort`**, not `model.reasoning_effort` (the
latter has been removed from `config.yaml` — only `agent.reasoning_effort` was ever read). Check
it the same way:

```bash
cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
from hermes_constants import resolve_reasoning_config; import yaml, os
print(resolve_reasoning_config(yaml.safe_load(open(os.path.expanduser('~/.hermes/config.yaml')))))"
```

## A burst of "Another gateway instance is already running" is a drain, not a crash loop

The tell that this is the launchd/wrapper interaction and not a broken gateway: **the PID in the
refusals is the PID of the gateway that is still draining**, and the Shutdown-context line for it
shows `parent_pid=<wrapper>` where the wrapper is `hermes_cli.stderr_timestamp`.

What happens: the generated plist hardcodes `ExitTimeOut = 25` (`hermes_cli/gateway.py`), while
`agent.restart_drain_timeout` is a separate, much larger budget (180 on this machine). launchd's
SIGTERM goes to the **wrapper**, which forwards it; when the drain outlives 25s launchd SIGKILLs
the *wrapper*, the gateway child survives, reparents to PID 1, keeps the runtime lock, and every
KeepAlive respawn (30s `ThrottleInterval`) refuses startup until the drain finally ends. The
systemd path does not have this asymmetry — it derives `TimeoutStopSec` from the drain budget via
`resolve_systemd_timeout_stop_sec`; the launchd plist derives nothing.

Confirm it before calling anything a hang:

1. `grep -a "Shutdown context" ~/.hermes/logs/agent.log` — a `parent_pid=<wrapper>` line followed
   by a `parent_pid=1` line for the same shutdown is the reparent, i.e. the wrapper was killed and
   the gateway was not.
2. Find the *real* death time of the old PID from the system log, never from the SIGKILL
   timestamp: `log show --style compact --start "<t0>" --end "<t1>" | grep <old-pid>`. Network
   activity or a `cfprefsd` connection close minutes after the SIGKILL proves it was alive and
   working.
3. `grep "drain done at" ~/.hermes/logs/agent.log` on the next clean restart. `drain took ~0.00s`
   with `active_at_start=0` proves the whole burst was a function of in-flight work, not of the
   restart itself — the same `kickstart` on an idle gateway produces zero refusals.

**Count the refusals with `grep -a "ERROR gateway.run: Another gateway instance"`.** A plain
`grep -c` on the message text also matches the *inbound-message echo* of the card that
reported it (`INFO gateway.run: inbound message: … msg='gateway.run: Another gateway instance…'`),
so the count comes out high by one per card and looks like a longer storm than it was.

**Never relay "stalled shutdown" / "suspected hang" from a triage verdict as fact.** The verdict
is written from `grep gateway.run` alone, which shows the notify phase and then silence — the
drain's own `drain done` line lands on the *next* process's boot. Check the drain budget against
the old PID's real lifetime first; a drain that finished inside its budget is not a stall, and a
py-spy dump of it would have nothing to find.

## False positives that look like faults

- **`check_fn … returned False`** WARNINGs at every turn start (browser, computer-use,
  image-gen, kanban) are ordinary capability probes for tools this deployment does not
  install. Noise.
- **Curator refusals** — `Refusing background curator patch for skill '…': the skill
  lives in skills.external_dirs` — are the durability guard working, not an error.

## Restart boundary

Hermes may not restart its own gateway: a `hermes gateway restart` issued from a
terminal call inside that gateway would terminate the process running the command,
and it is blocked. That refusal is correct — do not look for a way around it.

Nor is it a job for a Claude Code agent. A repo agent has no lifecycle authority over
this machine's launchd, and `hermes-ops.sh` excludes `ai.hermes.gateway` for the same
reason. Asking one to run it would be improvising an infrastructure mutation through a
tool built for code changes.

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
- `_resolve_plain_custom_api_mode` returns `chat_completions` for the brain's configured
  `api_mode` + the OpenAI leg's base URL
- one real tool-using turn completes with a `msg_` response id and no ERROR line

See `references/model-routing.md` for the 2026-08-14 incident in full.

## More references

Read the matching file when the situation fits:

- `references/checkpoint-store-forensics.md` — Use when a checkpointmanager ERROR or store alert fires
- `references/hermes-log-alert-forensics.md` — Use when a Hermes log ERROR line shows up in an alert or a log read
- `references/hermes-model-audit.md` — Use when auditing Hermes's own brain model performance
- `references/supervised-restart-forensics.md` — Diagnose supervised restarts: kill deadline vs drain
