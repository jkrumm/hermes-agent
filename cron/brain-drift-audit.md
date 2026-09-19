# Brain drift audit — Hermes Cron Job

Source-of-truth for the weekly vault drift audit. **This file is documentation, not
auto-loaded.** The live job carries its own copy of the prompt in `~/.hermes/cron/jobs.json`
(gitignored); `brain-drift-audit.prompt.txt` is the tracked copy — push edits through
`hermes cron edit`, never by hand-editing `jobs.json` (see `docs/scheduled-jobs.md`).

## Job Spec

| Field | Value |
|-|-|
| Job id | `8fe7be4985d9` (registered 2026-08-16) |
| Schedule | `0 9 * * 6` (Saturday 09:00, Europe/Berlin) |
| Skills | `claude-dispatch`, `obsidian` |
| Pre-run script | none — the agent runs the whole turn |
| Deliver | `slack:C0ASRULFTSS` (#watchdog) |
| Name | `Brain drift audit` |
| Model | pinned `custom` / `deepseek-v4.1-flash` (2026-09-19) |

## What it does

1. Reads its own previous verdict from `~/.hermes/cron/output/8fe7be4985d9/` (the most recent
   file's `## Response` section) so it can diff instead of restating standing findings.
2. Opens an **investigate**-tier dispatch into the `brain` repo (read-only, worktree-isolated —
   `brain` is `investigate`-only in `config/dispatch-repos.json`, the one path that loads the
   vault's own rule hierarchy). The episode runs `node .scripts/vault-lint.mjs --drift` and
   judges the curated surface (`Areas/`, `Projects/`) against `voice.md` and the
   "rewritten, not appended" rule in `AGENTS.md`.
3. Reports NEW findings first (file:line, drift type), then one line of still-open / resolved
   counts. A quiet week is a single "held steady" line.

**Propose only.** It never edits or commits — every rewrite of a curated page stays human.

## Model pin (2026-09-19)

`cron.model_drift_guard` (on unless `cron.model_drift_guard: false`) refuses to fire any
**unpinned** job whose creation snapshot no longer matches the resolved global provider/model,
so a global switch can never silently change what a job spends. This job was created 2026-08-16
under `custom`/`gpt-5.6-luna`; the brain moved to `deepseek-v4.1-flash` on 2026-09-13, and the
2026-09-19 09:00 run was skipped (`[drift_skip]`, alerted once) with no inference call made.

It is now **pinned** to the current brain — `hermes cron edit 8fe7be4985d9 --provider custom
--model deepseek-v4.1-flash` — which clears both snapshots and drops the authority to the pin:
the job no longer follows a later global model change. Re-pin deliberately if the brain moves
again; leaving it unpinned means it stops and asks rather than re-routing.

## Edit

```bash
hermes cron edit 8fe7be4985d9 --prompt "$(cat ~/SourceRoot/hermes-agent/cron/brain-drift-audit.prompt.txt)"
hermes cron edit 8fe7be4985d9 --skill claude-dispatch --skill obsidian   # replaces the set
hermes cron edit 8fe7be4985d9 --provider custom --model deepseek-v4.1-flash   # re-pin if the brain moves
```
