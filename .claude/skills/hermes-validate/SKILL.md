---
name: hermes-validate
description: Test, observe, and improve Hermes Agent behavior — send test messages, read session traces, identify routing failures, and fix SOUL.md/SKILL.md
---

# hermes-validate

Iterative workflow for validating and improving Hermes skill routing and response quality.
Run this when adding a new skill, after changing SOUL.md/SKILL.md, or when Hermes gives a bad response.

---

## Send a Test Message

Two ways to drive Hermes. Pick by **what you're testing**:

| Testing | Use | Why |
|-|-|-|
| Routing, skills, SOUL, answer quality, Iris' real path | **A — API server (:8642)** | Synchronous, the same surface Iris calls, no side effects outside the response |
| A quick one-shot from the mini, tool behaviour, no HTTP plumbing | **B — CLI** | `hermes chat -q` runs one turn in-process |

There is no Slack path any more. Verify routing from the response content plus
`gateway.log`/`agent.log` and the session in `state.db` (see "Read the Session Trace").

> **Where secrets come from (v0.19.0+):** there is **no `~/.hermes/.env`** any more — it was
> retired when Hermes moved to native `secrets.command` resolution. Read values directly from
> the cache with `secrets-run read op://…` (the drop-in `op` shim; works headless on the mini).
> This also sidesteps the old `cut -d= -f2-` footgun, since nothing is being parsed out of a
> dotenv line: `secrets-run read` returns the raw value, `=` chars and all.

### A. API server (what Iris calls)

```bash
HOST=$(secrets-run read op://hermes/gateway/host)
KEY=$(secrets-run read op://hermes/gateway/api-server-key)
curl -s -X POST "http://$HOST:8642/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" --max-time 180 \
  -d '{"model":"hermes","messages":[{"role":"user","content":"your test prompt here"}]}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

`model` is the name advertised on `/v1/models` (`API_SERVER_MODEL_NAME=hermes`). To test
*continuation*, send the earlier turns in `messages`; a request with only the new message is a
fresh context window.

### B. CLI

```bash
hermes chat -q "your test prompt here" -Q     # one turn, quiet output (see `hermes chat --help`)
```

---

## Read the Session Trace

Traces live in **`~/.hermes/state.db`** (`messages` joined to `sessions`).

> **`~/.hermes/sessions/*.jsonl` is dead — do not read it.** It stopped being written on
> **2026-06-02** and the 155 files there are frozen history. Sorting that directory and
> taking the newest file silently hands you a seven-week-old conversation that looks
> current. Verify with `ls -t ~/.hermes/sessions/*.jsonl | head -1` before ever trusting it.

By thread (pass a fragment of the session key):

```bash
sqlite3 ~/.hermes/state.db "
SELECT m.role, COALESCE(m.tool_name,''), substr(REPLACE(COALESCE(m.content,''),char(10),' '),1,150)
FROM messages m JOIN sessions s ON s.id = m.session_id
WHERE s.session_key LIKE '%<session-key-fragment>%'
ORDER BY m.timestamp;"
```

Most recent turn regardless of thread:

```bash
sqlite3 ~/.hermes/state.db "
SELECT m.role, COALESCE(m.tool_name,''), substr(REPLACE(COALESCE(m.content,''),char(10),' '),1,150)
FROM messages m
WHERE m.session_id = (SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1)
ORDER BY m.timestamp;"
```

Reasoning is in the `reasoning` / `reasoning_content` columns; tool arguments in
`tool_calls`. 

---

## What to Look For

**From `agent.log` response line:**
```
response ready: platform=api_server chat=... time=51.7s api_calls=3 response=751 chars
```
| Metric | Good | Investigate |
|-|-|-|
| `api_calls` | ≤5 | >8 |
| `time` | <90s | >150s |

**Healthy trace pattern** (verified 2026-07-24, 3 api_calls, 21.3s):
```
user       |            | wie viele offene Watchdog-Items …
assistant  |            |
tool       | skill_view | {"success": true, "name": "argo-api", …}          ← skill hit directly
tool       | skill_view | {"file": "references/infrastructure.md", …}       ← drilled to the reference
tool       | terminal   | {"output": "{\"generatedAt\":…}"}                 ← one curl, not many
assistant  |            | Es gibt aktuell 12 offene Watchdog-Items …        ← clean answer
```

Two `skill_view` calls in a row is **normal now**, not a red flag: `argo-api` is a hub
skill and the second call opens the right `references/*.md`. What matters is that neither
is a `skills_list`.

**Red flags in the trace:**
- `skills_list` appearing twice before `skill_view` → skill not mentioned in SOUL.md by name
- `execute_code` with Python requests → SOUL.md needs to say "use terminal, not execute_code"
- `find skills/argo-api/reference.md` → dead file path in SOUL.md (rename to skill name)
- 404 on guessed API paths → skill SKILL.md missing or not loaded
- An auxiliary model 404/`not found` (title generation, compression) → non-blocking, but
  check the model name in `config.yaml` still exists on the endpoint. Auxiliaries are split
  by task, not all one model: `compression` is `gpt-6-luna` (like the fallback),
  `title_generation` is `gpt-6-luna`, `vision` is `claude-sonnet-5-5`, `approval` is
  `claude-haiku-5-5`. A log line naming any other id (e.g. a retired `gemini-2.5-flash*` or
  `claude-sonnet-4-6`) is stale config, not a bug in the current model.

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
**SOUL.md, `config.yaml`, and any patched Python module** require a gateway restart —
Python modules are imported once at startup, so an edited patched file is inert in the
running process until you restart, no matter what a direct in-process test reports.

```bash
hermes gateway restart          # launchd-supervised; drains in-flight runs (up to 180s)
# Wait for the API server platform to reconnect — poll the state file, not the log
until [[ "$(jq -r '.platforms.api_server.state' ~/.hermes/gateway_state.json)" == "connected" ]]; do sleep 2; done
jq -r '"pid=\(.pid) gateway=\(.gateway_state) api_server=\(.platforms.api_server.state)"' ~/.hermes/gateway_state.json
```

> Poll `gateway_state.json`, not the log: the log is append-only, so a grep matches a
> *previous* startup instantly and the loop exits before the new process is up.

A restart drops in-flight Iris requests (the drain waits for running turns first), so batch restarts.

Then re-send the same test message and compare `api_calls` and `time` in `agent.log`.

---

## Validated Capabilities

| Query type | Skill used | Calls | Time | Status |
|-|-|-|-|-|
| Infra status (all services + containers) | `infrastructure` | 3 | ~132s | Working — uses /summary, concise |
| Weather forecast (weekend) | `weather` | 2 | ~66s | Working |
| Weather UV query (sunscreen) | `weather` | 2 | ~60s | Working |
| TickTick overdue/due tasks | `tasks` | 3 | ~152s | Working — uses /summary .ticktick, grouped by project |
| Calendar + unread emails | `schedule` | 3 | ~77s | Working — parallel calendar + emails in one pass |
| Cross-domain (meetings + tasks + weather) | `schedule` + `tasks` + `weather` | 4 | ~121s | Working — loads 3 skills, 3 curl calls, clean combined response |
| Capture: clear GitHub repo (patch → dotfiles) | `capture` | 2 | ~12s | Working — 95% confidence, correct title + body shape |
| Capture: TickTick Personal (water plants tomorrow) | `capture` | 2 | ~11s | Working — date math correct, project ID resolved |
| Capture: IU/Work override (EP-1234 engineering task) | `capture` | 2 | ~9s | Working — hard rule applied, no GitHub even for code work |
| Capture: Shopping (buy oat milk and bananas) | `capture` | 2 | ~9s | Working — split into 2 tasks per multi-item rule |
| Capture: GitHub repo by name (jkrumm.dev OG tags) | `capture` | 2 | ~13s | Working — 99% confidence, correct repo ID |
| Capture: Ambiguous (look into morning briefing) | `capture` | 2 | ~9s | Working — asks clarifying question, no write |
| Capture: Multi-item (Tailscale cert + watchdog issue) | `capture` | 2 | ~10s | Working — TickTick Personal + GitHub dotfiles in one response |
| Capture: Cache miss + refresh (snow-finder) | `capture` | 6 | ~27s | Working — read empty cache, ran `gh repo list jkrumm`, confirmed repo, routed |
| KaraKeep: keep a link (karakeep repo) | `karakeep` | ~2 | — | Working — POST /bookmarks, returns ID, flags async crawl/AI-tag (verified: tags applied) |
| Obsidian: search vault (north-star) | `obsidian` | ~2 | — | Working — `obsidian` CLI search+read, summarised the real note content |
| Reading: "was soll ich lesen" | `reading` | — | ~34s | Working — pulled `/api/reading` shelf, German rec grounded in the real shelf (Tress / Bad Karma / Iron Flame) |
| WalkingPad: weekly distance | `argo-api` (walking-pad) | — | ~26s | Working — `/walking-pad/sessions/summary` + heroes; 33.7 km / 12 sessions / streak / +30.5% wk, all correct |
| Usage: monthly AI spend | `argo-api` (usage) | — | ~64s | Working — `/usage/headline` + breakdown, per-source + per-model, honest about fixed 7/30/90d windows |
| Post-update (v0.16.0→v0.18.2) TickTick overdue check | `tasks` (method A) | 4 | ~26s | Working — general agent loop intact after platform-plugin rewrite |
| Post-update infra status (homelab+vps) | `infrastructure` (method A) | 4 | ~16s | Working — 2× terminal/curl tool calls, clean routing after the platform-plugin rewrite |
| Post-audit infra status (method A) | `argo-api` (infrastructure) | 3 | 15.4s | Working — Homelab 36/36 + VPS 29/29, zero approval gates (argo allowlist intact after the tirith rewrite) |
| Post-audit download-guard block (method A) | `tirith_security` hardening | — | — | Working — `wget -qO /tmp/f URL && chmod +x … && /tmp/f` **blocked** end-to-end, no file created. This shape was a *bypass* before the restart, so it proves the running process carries the hardened guard, not just the file on disk |
| v0.19.1 STT round-trip (in-process) | `stt.openai` | — | — | Working — fed the TTS mp3 back to `transcribe_audio()`: `gpt-4o-transcribe` returned accurate German with umlauts intact ("Prüfe Gateway und Dienste… keine Fehler in der Gateway-Logdatei"). Closes the loop Gemini Charon → gpt-4o-transcribe |
| v0.22.7 + Haiku 5.5 gateway Anthropic leg, compaction 650k (2026-11-04) | routing, audio route ids, patches | 1–3 | 1.2–12s | Working — method A: infra (homelab 36/36, VPS gap known), tasks, `pong` on `claude-haiku-5-5`, 3 calls/~11s, cache 93–100% (new sessions already read the shared 23k prefix). Method B: `text_to_speech` → titled mp3 delivered in-thread via `audio.tts.gemini-flash-lite`, `/reply` reused the session (mc 7) and recalled `4711`. `format_message('* eins\n  * zwei')` → `- eins\n  - zwei`; `make patch-check` 12/12; no fallback, no errors after the deploy |

Rows for the retired Slack path (threading, `format_message()`, Slack media delivery) were dropped with the Slack gateway.

Update this table after each validation run. **Rows are historical, not current spec** —
they record what was true on the day. The `Skill used` column on pre-2026-06 rows names
domain skills (`infrastructure`, `tasks`, `schedule`, `weather`) that no longer
exist as directories; those endpoints now live in `argo-api/references/*.md` and route
through the `argo-api` skill. Don't "fix" an old row to match today — add a new one.

> **Verifying a security control needs a shape that only the NEW code catches.** A block
> that the old code also blocked proves nothing about which version is loaded. Pick a case
> from the regression suite's fix list, and confirm the side effect too (here: the
> downloaded file must not exist). Python modules are imported once at gateway start — an
> in-process test result says nothing about the running process.


---

## Key Files

All paths are relative to `~/SourceRoot/hermes-agent/` unless noted. The skill set is
whatever `HERMES_SKILLS` in the `Makefile` lists — check there rather than trusting this
table, which has gone stale before.

| File | Purpose |
|-|-|
| `SOUL.md` | System prompt — skill routing table lives here |
| `config.yaml` | Model, platform toolsets, secrets, approvals |
| `skills/capture/SKILL.md` | Router: KaraKeep vs Obsidian vs TickTick vs GitHub |
| `skills/work/SKILL.md` | IU surface — M365, Jira, Confluence, GitLab |
| `skills/karakeep/SKILL.md` · `skills/obsidian/SKILL.md` | Read-later bucket · second brain |
| `skills/reading/SKILL.md` · `skills/agw-research/SKILL.md` | Book shelf · deep cited research |
| `skills/image-delivery/SKILL.md` | `imgcli private`/`upload` — private by default |
| `~/.hermes/logs/agent.log` | Structured run log (api_calls, time, inbound messages) |
| `~/.hermes/logs/gateway.log` | Gateway stdout (startup, tool progress bars) |
| `~/.hermes/state.db` | `sessions` table — session keys, thread ids, message counts |
