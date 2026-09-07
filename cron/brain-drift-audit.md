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

## Edit

```bash
hermes cron edit 8fe7be4985d9 --prompt "$(cat ~/SourceRoot/hermes-agent/cron/brain-drift-audit.prompt.txt)"
hermes cron edit 8fe7be4985d9 --skill claude-dispatch --skill obsidian   # replaces the set
```
