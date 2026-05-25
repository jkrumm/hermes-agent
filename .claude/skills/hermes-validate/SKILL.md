---
name: hermes-validate
description: Test, observe, and improve Hermes Agent behavior — send test messages, read session traces, identify routing failures, and fix SOUL.md/SKILL.md
---

# hermes-validate

Iterative workflow for validating and improving Hermes skill routing and response quality.
Run this when adding a new skill, after changing SOUL.md/SKILL.md, or when Hermes gives a bad response.

---

## Send a Test Message

Messages sent via the homelab Slack API arrive as the HomeLab bot (`allow_bots: all` + `SLACK_ALLOW_ALL_USERS=true`).

```bash
HOMELAB_API_KEY=$(grep HOMELAB_API_KEY ~/.hermes/.env | cut -d= -f2)
CHANNEL=$(grep SLACK_CHANNEL_HERMES ~/.hermes/.env | cut -d= -f2)

curl -s -X POST \
  -H "Authorization: Bearer $HOMELAB_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"your test prompt here"}' \
  "https://argo.jkrumm.com/api/slack/channels/$CHANNEL/messages"
```

Wait for a response:
```bash
until tail -1 ~/.hermes/logs/agent.log | grep -q "response ready"; do sleep 5; done
tail -3 ~/.hermes/logs/agent.log
```

---

## Read the Session Trace

Every conversation is stored as a JSONL session file:

```bash
# Find the latest session
ls -t ~/.hermes/sessions/*.jsonl | head -3

# Read the full tool call trace
python3 << 'EOF'
import json, glob
latest = sorted(glob.glob('/Users/jkrumm/.hermes/sessions/*.jsonl'))[-1]
print('Session:', latest)
for i, line in enumerate(open(latest).readlines()):
    o = json.loads(line)
    role, content = o.get('role',''), o.get('content','')
    reasoning = o.get('reasoning','')
    if reasoning: print(f'[{i}] THINK: {reasoning[:150]}')
    if isinstance(content, str) and content:
        print(f'[{i}] {role}: {content[:250]}')
EOF
```

---

## What to Look For

**From `agent.log` response line:**
```
response ready: platform=slack chat=... time=51.7s api_calls=3 response=751 chars
```
| Metric | Good | Investigate |
|-|-|-|
| `api_calls` | ≤5 | >8 |
| `time` | <90s | >150s |

**From session JSONL — healthy pattern:**
```
[1] user: question
[2] THINK: knows to use skill_view('argo-api')...
[3] tool: {"success": true, "name": "argo-api", ...}   ← skill_view hit directly
[4] THINK: read the endpoints, forming curl command
[5] tool: {"status": "success", "output": "..."}          ← terminal/curl result
[6] assistant: clean answer
```

**Red flags in the trace:**
- `skills_list` appearing twice before `skill_view` → skill not mentioned in SOUL.md by name
- `execute_code` with Python requests → SOUL.md needs to say "use terminal, not execute_code"
- `find skills/argo-api/reference.md` → dead file path in SOUL.md (rename to skill name)
- 404 on guessed API paths → skill SKILL.md missing or not loaded
- `gpt-4o-mini not found` → session summarization auxiliary failure, non-blocking

---

## Common Failures and Fixes

### Hermes searches filesystem instead of using skill
**Symptom:** session shows `search_files`, `read_file` with a path like `skills/argo-api/reference.md`
**Cause:** SOUL.md had a dead file path reference
**Fix:** Replace file paths in SOUL.md with skill names: `skill_view('argo-api')`

### Hermes uses `execute_code` instead of `terminal` for curl
**Symptom:** session shows Python `requests` code, often with import errors
**Fix:** Add explicit instruction to SOUL.md:
> "use `terminal` with curl — never `execute_code`"

### Skill not found on first try (2 `skills_list` calls)
**Symptom:** `skills_list` appears twice in trace before `skill_view`
**Cause:** the model lists all skills to verify, rather than calling `skill_view` directly
**Fix:** In SOUL.md name the exact skill and tool call: `call skill_view('argo-api')`

### Wrong interpretation of API response values
**Symptom:** Hermes reports wrong status (e.g., UptimeKuma `status: 1` called "down")
**Fix:** Add field semantics to the relevant SKILL.md. Example:
> "`status: 1` = UP, `status: 0` = DOWN"

### 33+ API calls, looping behavior
**Symptom:** `api_calls` very high, session reasoning repeats the same question
**Cause:** Usually a dead reference in SOUL.md causing the model to search and give up repeatedly
**Fix:** Find and remove the dead reference, point to skill name instead

---

## After Fixing SOUL.md or a SKILL.md

Skills are symlinked so SKILL.md changes are live immediately.
SOUL.md changes require a gateway restart:

```bash
hermes gateway stop && hermes gateway start
# Wait for connection
until grep -q "Bolt app is running" ~/.hermes/logs/agent.log; do sleep 2; done
```

Then re-send the same test message and compare `api_calls` and `time` in `agent.log`.

---

## Validated Capabilities (as of Phase 0)

| Query type | Skill used | Calls | Time | Status |
|-|-|-|-|-|
| Infra status (all services + containers) | `infrastructure` | 3 | ~132s | Working — uses /summary, concise |
| Weather forecast (weekend) | `weather` | 2 | ~66s | Working |
| Weather UV query (sunscreen) | `weather` | 2 | ~60s | Working |
| TickTick overdue/due tasks | `tasks` | 3 | ~152s | Working — uses /summary .ticktick, grouped by project |
| Calendar + unread emails | `schedule` | 3 | ~77s | Working — parallel calendar + emails in one pass |
| Slack unreads | `slack` | 3 | ~31s | Working — uses /slack/unreads, very fast |
| Cross-domain (meetings + tasks + weather) | `schedule` + `tasks` + `weather` | 4 | ~121s | Working — loads 3 skills, 3 curl calls, clean combined response |
| Capture: clear GitHub repo (slack patch → dotfiles) | `capture` | 2 | ~12s | Working — 95% confidence, correct title + body shape |
| Capture: TickTick Personal (water plants tomorrow) | `capture` | 2 | ~11s | Working — date math correct, project ID resolved |
| Capture: IU/Work override (EP-1234 engineering task) | `capture` | 2 | ~9s | Working — hard rule applied, no GitHub even for code work |
| Capture: Shopping (buy oat milk and bananas) | `capture` | 2 | ~9s | Working — split into 2 tasks per multi-item rule |
| Capture: GitHub repo by name (jkrumm.dev OG tags) | `capture` | 2 | ~13s | Working — 99% confidence, correct repo ID |
| Capture: Ambiguous (look into morning briefing) | `capture` | 2 | ~9s | Working — asks clarifying question, no write |
| Capture: Multi-item (Tailscale cert + watchdog issue) | `capture` | 2 | ~10s | Working — TickTick Personal + GitHub dotfiles in one response |
| Capture: Cache miss + refresh (snow-finder) | `capture` | 6 | ~27s | Working — read empty cache, ran `gh repo list jkrumm`, confirmed repo, routed |

Update this table after each validation run.

---

## Key Files

| File | Purpose |
|-|-|
| `hermes/SOUL.md` | System prompt — skill routing table lives here |
| `hermes/skills/argo-api/SKILL.md` | Full endpoint reference (fallback when no domain skill matches) |
| `hermes/skills/infrastructure/SKILL.md` | UptimeKuma + Docker behavioral guidance |
| `hermes/skills/tasks/SKILL.md` | TickTick task management behavioral guidance |
| `hermes/skills/schedule/SKILL.md` | Calendar + Gmail behavioral guidance |
| `hermes/skills/weather/SKILL.md` | Weather forecast behavioral guidance |
| `hermes/skills/slack/SKILL.md` | Slack messages, search, unreads behavioral guidance |
| `~/.hermes/logs/agent.log` | Structured run log (api_calls, time, inbound messages) |
| `~/.hermes/sessions/*.jsonl` | Full turn-by-turn session traces |
| `~/.hermes/logs/gateway.log` | Gateway stdout (startup, tool progress bars) |
