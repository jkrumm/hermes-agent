# Hermes skills audit — agent-platform Round 4, Wave 9 (2026-10-10)

Evidence: `~/.hermes/skills/.usage.json` (per-skill `use_count`, `last_used_at`; 234 records) plus a read of each
skill's description and, for ours, its body. **No skill was deleted.** "Retire" means `skills.disabled` in
`config.yaml` (reversible, survives `hermes update` re-seeding); git history is the archive for ours.

## What the 73 / 24 numbers actually are

- **20** skills are ours (`HERMES_SKILLS`, symlinks from this repo). `make skills-set-check` (part of `make status`) now asserts
  repo dirs, live symlinks and the declared list are the same set.
- **73** `SKILL.md` files under `~/.hermes/skills` are *upstream-bundled* categories (re-seeded by `hermes update`, listed in
  `.bundled_manifest`) plus nested ones; **24** dirs in `~/.hermes/skills/.archive` are curator archives of those.
- `.usage.json` still carries ~100 records for agent-authored skills (`warden-*`, `homelab-watchdog` 365 uses,
  `heartbeat-monitoring` 194, `engineering-harness`, …). They were retired by Wave 2 (126 → 20) and live on as
  `references/*.md` (`homelab-ops`, `verify`, `warden`, `argo-api`, `hermes-gateway`, `capture`); last use ≤ 2026-10-02.
  Nothing to do; the high counts are the evidence those references were worth keeping.
- A bundled skill with 5–7 uses all dated 2026-07-06 is one curator pass, not real use.

## Ours (20) — verdict: all keep in Hermes

| Skill | Uses (last) | Verdict | Wiring action taken |
|-|-|-|-|
| argo-api | 2107 (10-09) | keep | — |
| homelab-ops | 791 (10-02) | keep | VPN-down trigger corrected: overnight host reboot, not Watchtower |
| warden | 295 (10-04) | keep; learn-from → agent-platform | — |
| hyperdx | 280 (10-02) | keep | — |
| work | 217 (10-09) | keep, split | 618 lines → lean core + `references/`; per-skill report formats dropped (SOUL.md owns it) |
| research-gateway | 81 (09-23) | keep; adapt-port | "VPS" wording → mini; `partial/grounding` ported to dotfiles `research` |
| hermes-gateway | 75 (10-01) | keep | — |
| homelab | 74 (09-29) | keep | VPN recovery text corrected |
| human-queue | 62 (10-01) | keep | — |
| briefing-tts | 56 (09-20) | keep | — |
| obsidian | 46 (10-10) | keep | — |
| capture | 44 (10-02) | keep, split | stale repo hints fixed, examples/state moved to `references/` |
| herdr | 41 (10-01) | keep (Hermes-specific: outside a pane, 180 s cap) | `wait` on idle/done/blocked, rd verbs completed, delivery check, version pin dropped |
| podcast | 13 (09-28) | keep | model roster removed from prose |
| wildrift | 11 (08-26) | keep, split | data-reality / vault-writing / workflows → `references/`; dead Argo group paragraph cut |
| reading | 6 (09-05) | keep, split | taste/API shapes → `references/`; routes web research to `research-gateway`; one question max |
| karakeep | 5 (07-28) | keep, split | endpoints/qualifiers/workflows → `references/`; Kobo claim corrected |
| dispatch | 5 (10-10) | keep | tier sentence reworded |
| image-delivery | 2 (08-02) | keep, trimmed | policy kept; duplicated JSON-shape prose removed. Hermes cannot load dotfiles' `img`, so the verb table stays |
| verify | 3 (10-06) | keep | — |

`work/iu-epos-ops` (gitignored, employer-internal, 1 use, agent-created 09-14) — **flagged, not changed**: it references the retired
approval layer and tells Hermes to read repo files and run `make`, which SOUL.md forbids. It is not in git, so the fix is
local-only; see Left behind in the plan.

## Upstream-bundled (73) — verdicts

| Group | Evidence | Verdict |
|-|-|-|
| `autonomous-ai-agents/{coding-agents,hermes-agent}` | 17 / 40 uses | keep |
| `software-development/{systematic-debugging,requesting-code-review,writing-plans,github,…}` | 3–16 uses | keep; learn-from reviewed — covered by `/wave`, `implement`, `review` skills |
| `github/*`, `productivity/{ocr-and-documents,docx,pdf,xlsx}`, `web/blocked-page-recovery`, `devops/webhook-subscriptions`, `creative/{ascii-art,comfyui,excalidraw,…}` | used or plausibly useful | keep |
| `mlops/*` (14 skills with **no** usage record), `gaming/{minecraft-modpack-server,pokemon-player}`, `creative/{creative-ideation (frontmatter name `ideation`),pixel-art}`, `productivity/{box,linear,petdex}`, `devops/sdlc-review` | no `.usage.json` record or 0 loads since creation; no stack fit (no GPU/ML work, Desktop mascots dormant, Kanban already disabled, no Box/Linear) | **retire = disable** |
| `mlops/{huggingface-hub,llama-cpp,obliteratus}`, `red-teaming/godmode` | single curator-pass loads | keep (not disabled: evidence is not "dead") |
| `email/email-inbox-triage`, `productivity/{meeting-action-items,weekly-review-planning,…}`, `research/{rss-feeds,competitor-news-monitor}`, `social-media/reddit-reading` | 0 uses, but each is a task Hermes could be asked | keep; re-audit after 90 days of data |

## Wiring map: Hermes ↔ global setup

| Fact | Hermes-specific | Shared (one home) |
|-|-|-|
| herdr CLI semantics, status meanings, safety rules | no `--current`, workspace by repo label, launchers typed into the pane, 180 s cap, draft-in-input-line, branch restore | dotfiles `herdr` + `remote-dev` own the CLI; Hermes keeps a deliberate copy because it cannot load them. Differing facts reconciled this wave; draft/branch/integration rules ported *to* dotfiles |
| podcast API | raw curl with bearer `hermes`, poll in 6×20 s chunks, Slack announce, no `MEDIA:` for long audio | request fields / series / pipeline live in dotfiles `podcast` and `audio-gateway`; model roster lives in its config only |
| research | REST + bash poll, German Slack presentation | `research-gateway` README; dotfiles `research` is the MCP view |
| homelab / homelab-ops | the whole tier A/B verb model | stack facts live in `homelab-private` (self-contained: not referenced from here) |
| dispatch / warden | `hermes-cc.sh run` is an exec shim to `warden run` — same command | `~/SourceRoot/warden/AGENTS.md`, `dotfiles/docs/agent-platform.md` |

## Retired terms

`agent-dispatch`, `rd bg`: no occurrences. `claude --bg` appears only as a prohibition (`herdr`, `homelab-ops/restart-window-prep`).
`colleague` in `capture` is a routing *keyword* (work signal), not the retired lane. Nothing to remove.
