# Where the former root AGENTS.md went

The root `AGENTS.md` was 45,819 bytes against a 12,000-byte budget (`rules/writing-for-agents.md`). It was split, not shortened by deletion: every section below was moved verbatim into the doc named in the table, behind a trigger row in the root's "Before you change it, read the doc" table. Each moved block starts with an HTML comment `<!-- MOVED-…: moved verbatim from the root AGENTS.md … -->`, which is the marker used to prove the block is still reached. The pre-split text is in git history (`git show e0cc553:AGENTS.md`).

| Former section (lines) | Bytes | Marker | Now in | Root keeps |
|-|-|-|-|-|
| What This Repo Is, audio paragraph (13–27) | 1768 | `MOVED-AUDIO` | `docs/audio-door.md` | one pointer row |
| Symlink Map, skill audit, host scripts, scheduled jobs, per-repo skills (35–79) | 4533 | `MOVED-SYMLINK-MAP` | `docs/symlinks-and-agents.md` | `make setup`, `HERMES_SKILLS`, skill durability, cron-not-crontab |
| Cron pre-run scripts, `--script` limit (104–111) | 502 | `MOVED-CRON-PRERUN` | `docs/scheduled-jobs.md` | the thin-entry-point rule |
| Herdr steering (113–122) | 852 | `MOVED-HERDR` | `docs/agent-routing.md` | the `hc` safety list |
| Secrets (123–169) | 3395 | `MOVED-SECRETS` | `docs/secrets-command.md` | `hermes model` ban, `$t` rule, rotation restarts |
| Gateway HTTP exposure, Iris turns (170–194) | 2080 | `MOVED-GATEWAY-HTTP` | `docs/gateway-http-api.md` | key rotation restart |
| Hermes Desktop (195–216) | 1580 | `MOVED-DESKTOP` | `docs/hermes-serve.md` | serve restart after `hermes update` |
| Homelab API integration (217–236) | 1632 | `MOVED-ARGO` | `docs/argo-surface.md` | `work` skill scope, briefing work signals |
| Research, web, WeatherOrb, hyperdx, podcast, agw transport (237–314) | 5544 | `MOVED-AGW-DOORS` | `docs/agw-doors.md` | `AGW_CALLER`, exit 10 resume |
| Project narratives (315–327) | 963 | `MOVED-NARRATIVES` | `docs/project-narratives.md` | one pointer row |
| Second Brain, Wild Rift (328–367) | 2527 | `MOVED-SECOND-BRAIN` | `docs/second-brain.md` | one pointer row |
| Local Modifications to Upstream (368–416) | 5583 | `MOVED-PATCHES` | `docs/patches.md` | re-apply command, restart list, no-approvals decision |
| Model, context window, reasoning effort (417–472) | 5524 | `MOVED-MODEL` | `docs/model-context-reasoning.md` | `seats-check`, Claude-only, effort key, 650k compaction |
| Shell script conventions (473–481) | 569 | `MOVED-SHELL` | `docs/shell-conventions.md` | the SIGPIPE line |
| Editing Rules (493–515) | 1425 | `MOVED-EDITING` | `docs/editing-and-deploy.md` | skill add/rename, `cron/jobs.json` copy |
| Deploy, Verify & Monitor (524–559) | 2740 | `MOVED-DEPLOY-VERIFY` | `docs/editing-and-deploy.md` | one-line deploy and verify summary |

Sections rewritten in the root rather than moved: What This Repo Is (role, public-repo warning), Repo work is filed, the factory routing table, Setup, Validate, Gotchas.
