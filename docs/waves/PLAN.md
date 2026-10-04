# Hermes — a quiet, sharp front door

**Goal:** Hermes matches `~/SourceRoot/dotfiles/docs/agent-platform.md` §Hermes:
answers, narrates in one line per item, files work through `warden run` or an
issue, opens herdr tabs on request — ~20 curated skills, no self-authored skill
churn, no replies to warden's own posts.

**Gate:** `make patch-check` + `/hermes-validate` smoke (send 3 test messages, read the traces) + `/review` on each wave's diff.

**Spec:** `~/SourceRoot/dotfiles/docs/agent-platform.md` — read it first.

**Live system:** the gateway runs from this checkout and `~/.hermes`. Restarting the gateway is the orchestrator's — a wave stops before it and says so in **Left behind**.

**Dirty tree at start:** ~84 untracked/modified skill dirs written by Hermes itself. Wave 2 decides their fate; Wave 1 must not commit them (path-limited commits only).

## Wave 1 — stop the loop, one voice            <!-- status: done -->
- [x] Stop autonomous skill creation: `skills.creation_nudge_interval: 0` and point `skills.create_dir` outside `external_dirs` (quarantine dir under `~/.hermes/skills-quarantine`). Delete the `curator-write-probe*` skills.
- [x] #agents: Hermes replies only when mentioned (`require_mention_channels`) and never to warden's bot posts; stop appending raw Block Kit JSON to inbound bot messages if config allows. Turn off `display.interim_assistant_messages`, the `kawaii` personality; fix the `zle` shell-init noise (`terminal.auto_source_bashrc`).
- [x] SOUL.md + AGENTS.md agree on one role: narrate, answer, route. Routes: `warden run` / GitHub issue for unattended work, `rd wave` / herdr tab only when the owner asks, `capture` for later. Delete the `warden:go` label instruction (warden picks up every owner issue).
- [x] One reporting contract in SOUL.md (spec §Hermes format, max three lines + `Rest: …`, no ids/PIDs/mechanism unless asked). Remove every per-skill "Report shape" section that contradicts it.
**Left behind:**
- **Gateway restart pending (orchestrator's):** `config.yaml` (creation nudge, quarantine dir, #agents mention-only, kawaii/interim off, `auto_source_bashrc`) and `SOUL.md` are not live until `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`. `/hermes-validate` 3-message smoke therefore **not run** — do it after the restart.
- **Block Kit JSON append not configurable:** `_append_block_text` in the Slack adapter always appends `_serialize_slack_blocks_for_agent`; no config key. Moot in #agents now (mention-gated); a patch is needed only if it still bites elsewhere.
- **`zle` noise:** set `terminal.auto_source_bashrc: false`; confirm after restart.
- **Review:** sideclaw `/review` synthesis failed (OAuth session expired on its Max leg) — diff read by hand instead; re-run `/review` on `d888f9c..01e3767` if wanted.
- `skills/work/iu-epos-ops/SKILL.md` is gitignored — its `warden:go` mention was edited on disk only.
- Per-skill "Report shape" sections removed from 51 skills plus three contradicting "Reporting" sections; other benign "Reporting" sections left for Wave 2's fold/delete.
- Commits: `d888f9c` (behaviour), `01e3767` (skill report-format removal). `make patch-check` 15/15 green.


## Wave 2 — 126 skills → ~20            <!-- status: active -->
- [ ] Target set: capture, argo-api, work, karakeep, obsidian, reading, wildrift, research-gateway, image-delivery, podcast, briefing-tts, hyperdx, homelab, homelab-ops, hermes-gateway, human-queue, `dispatch` (filing work), `warden` (read-only via its HTTP API, never sqlite), `herdr` (tabs + `rd`), `verify` (one checklist). Fold useful facts from the duplicates into these as reference files; delete the rest. Delete the "Hermes lands PRs by hand" cluster outright (blocked-agent-pr-handfix, warden-hand-fixes, carrier-*, …).
- [ ] Update `HERMES_SKILLS` in the Makefile to the target set; commit the decision for every untracked Hermes-authored dir (fold or delete) so the tree is clean.
- [ ] One door per verb: `hermes-cc.sh run` (drop direct `warden` script calls and `gh pr merge`), `rd` for panes (drop raw `claude --bg` / `claude -p`). Disable the kanban and delegation toolsets.
- [ ] Remove `plugins/dispatch-approval` **only if** warden Wave 1 is done (check `~/SourceRoot/warden/docs/waves/PLAN.md`); otherwise leave a note in Left behind.
**Left behind:**

## Wave 3 — repo contract and cleanup            <!-- status: pending -->
- [ ] Make targets `check`, `deploy` (restart gateway, health check, roll back to the previous commit on failure), `verify`, `logs`; AGENTS.md sections `## Validate`, `## Deploy`, `## Verify & Monitor`, `## Gotchas`.
- [ ] Remove `scripts/warden-live-sync.sh` and its cron **only if** warden Wave 4 is done (warden deploys itself via `make deploy`); otherwise note it.
- [ ] Replace ad-hoc watcher crons / `/tmp/watch-*.sh` patterns in skills with `herdr agent wait --until done` (single blocking call) or warden item status.
**Left behind:**
