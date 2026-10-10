# Common repo → domain hints

Map a capture to a GitHub repo (`jkrumm/<repo>`). This list is a hint, not exhaustive. The
live cache (`state-cache.md`) is the source of truth.

| Repo | Owns |
|-|-|
| `homelab` | Docker stack, 25+ containers, infra services on home network |
| `homelab-private` | Private homelab services (homelab API, secrets) |
| `vps` | VPS Docker stack, Traefik, RollHook, Postgres, Valkey |
| `dotfiles` | Claude Code config (skills, rules, hooks), statusline, shell/dotfiles. **Not** Hermes — that moved to `hermes-agent` |
| `hermes-agent` | Hermes skills, cron prompts (`cron/*.prompt.txt`), SOUL.md, scripts, config, upstream patches (`~/SourceRoot/hermes-agent`) |
| `warden` | Control plane: signal ingest, dispatch of Claude Code episodes, the item ledger (`~/SourceRoot/warden`) |
| `basalt-ui` | NPM-published Tailwind v4 design system |
| `basalt-ui-playground` | TanStack Start boilerplate using basalt-ui |
| `rollhook` / `rollhook-action` | Zero-downtime Docker rolling deploys + GitHub Action |
| `agent-gateway` | MCP tooling used by skills |
| `jkrumm.dev` | Personal site |
| `home` | Home dashboard |

## Service/domain → repo examples

- "the watchdog cron" / "the watchdog poll" / "triage" → `warden`.
- "the slack patch" / "the morning briefing prompt" / "a Hermes skill" / "SOUL.md" → `hermes-agent`.
- "rollhook deploy logs" → `rollhook`.
