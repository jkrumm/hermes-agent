# Skill durability, trust and stray-skill detection

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Symlink Map / Editing Rules points here — nothing was rewritten, only relocated.

> **Skill trust (v0.16.0+).** Skills are symlinked into `~/.hermes/skills/`, but v0.16.0's skill-security check resolves each skill's *realpath* and warns — and may later **block** — when it lands outside a trusted dir (our symlink targets do). `config.yaml` therefore sets `skills.external_dirs: [~/SourceRoot/hermes-agent/skills]` so the resolved realpath is trusted. The symlink and the external entry resolve to the same path, which `skills_tool` dedups (by realpath on load, by name on listing) — no duplicate-skill collisions. If a future update reintroduces the "skill file is outside the trusted skills directory" warning, confirm this key is still populated.

> **`external_dirs` is also what protects a skill from the background self-improvement pass — this is why every durable skill must live in this repo.** The autonomous curator fork (`is_background_review()`) refuses every mutating action — edit, patch, delete, write_file, remove_file — on a skill whose resolved path falls under `skills.external_dirs` (`tools/skill_manager_tool.py` → `_background_review_write_guard`). A skill created ad hoc under `~/.hermes/skills/` by the agent itself (not symlinked from here) has no such protection: it sits outside `external_dirs`, so the same background pass can — and, observed in practice, repeatedly did — silently rewrite it, growing by accretion with no review (`skills.write_approval` is off by default) until it was restorable only from the nightly rsync backup. **Symlinking a skill from this repo is not cosmetic — it is the only thing that makes it durable.** As of 2026-08-02, **`scripts/watchdog-poll.py`'s `stray_skill` source is the primary defence** — every 30 min it walks `~/.hermes/skills/` two levels deep (top-level and one level nested inside a bundled category dir, since real strays hide there too — `homelab-alerts` was under `devops/`) and flags any non-symlink dir with its own `SKILL.md` whose name isn't in `.bundled_manifest` **and** whose `~/.hermes/skills/.usage.json` record shows local mutation — `created_by == "agent"` (the marker `skill_manager_tool.py` sets only inside the background curator fork) **or** `patch_count >= 1`. It surfaces in the watchdog Slack digest (weekly reminder cadence — see `REM_HOURS["stray_skill"]`) and auto-resolves once the skill is adopted (symlinked in from here) or deleted, no manual sweep required. A plain manifest-membership check over-fires: the live tree carries 19 dirs that are absent from `.bundled_manifest` by name yet legitimate (hub-installed, or seeded by an early pre-manifest-tracking sync). But 18 of those 19 have never been touched, so *mutation* is what separates them — one candidate on the current tree against six real strays it would have caught. `created_by` alone is too narrow: it catches the worst class (`homelab-alerts`, 89 rewrites) but missed four of the six cleaned up on 2026-08-02, since the curator's consolidations of upstream skills carry `created_by: None` with 1-5 patches each. Those are the same problem — a divergent local copy `hermes update` will never refresh — and the patch count is what exposes them.
>
> Manual fallback (e.g. to sanity-check the automated source, or if `watchdog-poll.py` itself is broken) — coarser, top-level only, no mutation filter, so it can false-positive on legitimate untracked nested skills:
> ```bash
> for d in ~/.hermes/skills/*/; do d="${d%/}"; [[ -L "$d" ]] && continue; [[ -f "$d/SKILL.md" ]] || continue; grep -q "^$(basename "$d"):" ~/.hermes/skills/.bundled_manifest || echo "$(basename "$d")"; done
> ```
> Any real hit needs the same treatment this file's history documents: read it fully, separate durable knowledge from dated incident sediment, land the durable part under `skills/` here, wire it into `HERMES_SKILLS` + this table, archive the original outside git (`.skill-archive/`, gitignored — it will carry secrets the source itself doesn't scrub), then delete the untracked original.

**A new or renamed skill also needs a gateway restart.** `make setup` creates the symlink,
but the skills index in the system prompt is cached **in-process** (`_SKILLS_PROMPT_CACHE`,
`agent/prompt_builder.py`) under a key of directory paths only — no mtime, no manifest — and
nothing clears it except `skill_manager_tool`. The disk snapshot under it *is* manifest-checked
and self-heals, and `hermes skills list` runs in a fresh CLI process, so **both will show the
new skill while the running gateway still cannot see it**. Verify against a rebuilt prompt after
restarting: `./venv/bin/python3 -c "from agent.prompt_builder import build_skills_system_prompt as b; print('<name>' in b())"`.

**Renaming or retiring one is the half that gets forgotten — and it fails silently.** A cron
job preloads skills *by name*; when a name no longer resolves, `cron/scheduler.py` logs
`skill not found, skipping` at **WARNING** and runs the job anyway, and `watchdog-poll.py`
matches `ERROR|CRITICAL` only. So the job keeps reporting `ok` while running with fewer
skills than it declares. That is exactly what the 2026-06 consolidation into
`argo-api/references/*.md` did: both briefings kept naming `tasks`, `schedule`, `weather`,
`infrastructure`, `slack`, `garmin-health`, `strength` — 7 of 8 dead — for weeks, logging 12
warnings a day. They only survived because every endpoint is also spelled out inline in the
prompt and `work` happened to carry the argo auth pattern. Fixed 2026-08-02: both jobs now
preload `argo-api` + `work`, and `make status` asserts **every skill named in
`~/.hermes/cron/jobs.json` resolves** (negative-tested — it prints `✗ cron skill "…" missing`).
Run `make status` after any skill rename.

**Bundled-skill collision (obsidian).** Upstream ships a stock bundled `obsidian` skill (generic, filesystem-first) listed in `.bundled_manifest`. Our local `obsidian` (symlinked from this repo) has the same name; the stock one was removed from `~/.hermes/skills/note-taking/obsidian/` so ours is canonical. It **re-seeds on `hermes update`** — `/hermes-update` carries the `rm -rf ~/.hermes/skills/note-taking/obsidian` reconciliation step. In `hermes skills list` ours may show source `builtin` (name is in the manifest) — cosmetic; an empty *category* column confirms the top-level symlink (ours) is loaded.
