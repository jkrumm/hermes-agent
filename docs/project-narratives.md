# Project narratives — daily vault pages per project, written by Hermes

`scripts/project-narratives.py` keeps one narrative page per active repo at
`~/SourceRoot/brain/wiki/engineering/projects/<project>.md`: what the project
is, where it stands, how it got there. Driven by sideclaw's `narrative` job
(same daemon `agents-overview.py` and the dispatch bridge use,
`http://localhost:7705`) — see `docs/agents-overview.md` for the sibling
job-submission pattern this one mirrors.

## Less is more

A project with no substantive change since its last revision gets **no
model call, no revision, and no mention** — silence is the normal case, not
a degraded one. The gate is `needs_revision()`, pure and cheap:

- HEAD moved since the last recorded `lastCommit`, **or**
- a Claude Code transcript under `~/.claude/projects/<encoded cwd>/` (encode:
  every non-alphanumeric char in the absolute cwd path → `-`, the same
  scheme Claude Code itself uses) is newer than `lastSessionMtime`.

Neither condition firing means the project is skipped entirely — zero cost,
every run, for an idle repo. Even when the job *does* run, sideclaw itself
can report `changed: false` (no substantive narrative-worthy delta despite
the commit/session activity); that also produces no page write, only a
state-timestamp advance so the gate settles and doesn't re-fire on the same
input next run.

## Project discovery

Every git repo directly under `~/SourceRoot` (basename = project name),
minus a deny list — `dotfiles-private`, `homelab-private` (private-secrets
repos), `dispatch-scratch` (disposable), `brain` (the vault itself — a
narrative page about the vault,
written into the vault, is a confusing loop) — minus anything listed in
`HERMES_NARRATIVE_SKIP` (comma-separated). `--projects a,b` restricts
discovery to exactly that set, in any CLI mode.

## Per-project pipeline (`--run`)

Sequential, oldest-revised first (never-revised projects first), capped at
`HERMES_NARRATIVE_MAX_PER_RUN` (default 5) per invocation so a backlog of
stale projects drains gradually rather than in one giant run:

1. Read the existing page (`previousPage`) if one exists; `since` = the
   project's `lastRevisedAt` or `null` on a first revision.
2. `POST /api/jobs {"tool":"narrative","params":{cwd, project, previousPage,
   since}}`, poll `GET /api/jobs/<id>` until `done`/`failed` (bounded 5 min).
3. `changed: false` → advance `lastCommit`/`lastSessionMtime` in state,
   write nothing.
4. `changed: true` → write `result.page` verbatim (full markdown incl.
   frontmatter — this script never authors project-page frontmatter itself),
   regenerate `wiki/engineering/projects/index.md` from every page currently
   on disk, ensure `wiki/engineering/index.md` links it, then
   `node ~/SourceRoot/brain/.scripts/vault-lint.mjs` (exit 0 required).
   - **Lint fails** → print the errors to stderr, revert the page (`git
     checkout` if it existed before, delete if new), regenerate the index
     from what's left, and skip — no commit, state left untouched so the
     same input retries next run.
   - **Lint passes** → commit, always naming the vault (`git -C
     ~/SourceRoot/brain add wiki/engineering/projects
     wiki/engineering/index.md` + `git -C ~/SourceRoot/brain commit -m
     "narrative(<project>): <summary>"`) — the repo-write guard's one
     exemption is narrow and requires the command to *name* the vault (see
     `docs/guards.md`'s `raw_repo_write` section); a bare `git commit` is
     still refused. Update state (`lastRevisedAt`, `lastCommit`,
     `lastSessionMtime`, `summary`).

## State

`~/.hermes/project-narratives-state.json`, gitignored runtime state, one
entry per project: `{lastRevisedAt, lastCommit, lastSessionMtime, summary}`.
Written atomically (temp file + rename), same pattern as
`agents-overview-state.json`. Deleting it just means every project looks
never-revised on the next run — expensive (one model call per still-live
project, capped at 5/run) but not destructive; existing vault pages are
untouched until a project's `needs_revision()` gate re-fires for real.

## CLI

| Flag | Does |
|-|-|
| `--run` | The cron entry point — the full gated pipeline above, commits. Prints `<project>: <summary>` per revised project, nothing when none (stdout is the Slack body under `--no-agent`). |
| `--bootstrap a,b,c` | Forces `since=null` and `previousPage=None` for the named projects (ignores the gate entirely), writes pages + regenerates the index + lints, but **never commits** — prints the written page paths so Johannes reviews the `git diff` by hand. |
| `--briefing` | Prints `narrative: <project> — <summary>` for every project revised in the last 26h (from state — no job call, no network), or nothing. Feeds `briefing-context.py` → the morning briefing's "Agenten & Projekte" block. |
| `--dry-run` | Lists which projects would be revised this run and why (`HEAD moved (<old> -> <new>)`, `newer Claude Code session`, or `never revised`) — no job call, no writes. |
| `--projects a,b` | Restricts discovery to exactly this set, combinable with any mode above. |

## Registering the cron

Registered 2026-09-07 as job `9909f808fe17` (see the registry in `docs/scheduled-jobs.md`).
The command, kept for a re-install:

```bash
hermes cron create "30 6 * * *" --name "Project narratives" \
  --script narratives-cron.py --no-agent --deliver slack:C0BVDE5R562
# registered 2026-09-07 as job 9909f808fe17 — edit with `hermes cron edit 9909f808fe17`, never re-create
```

Verify with `hermes cron list` — `Script: narratives-cron.py`, `Mode:
no-agent`. `scripts/narratives-cron.py` is the thin loader (same shape as
`agents-cron.py`/`dispatch-sweep-cron.py`) the cron-creation guard needs —
see `docs/scheduled-jobs.md` for why a substantial entry point gets rejected
regardless of content.

## Testing

`tests/test_project_narratives.py` — pure `needs_revision()` branches,
discovery's deny list + env skip on a temp `SourceRoot`, index rendering
from page frontmatter, state round-trip, and `main(["--run"])` end to end
with a monkeypatched `run_narrative_job` (the network seam) and a
monkeypatched `subprocess.run` recording every git/node invocation. Run:

```bash
~/.hermes/hermes-agent/venv/bin/python3 tests/test_project_narratives.py
```
