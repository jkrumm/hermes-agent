HERMES_REPO   := $(shell pwd)
HERMES_DIR    := $(HOME)/.hermes
# Upstream Hermes checkout the patches/ dir is applied to (see `make patch-check`).
HERMES_SRC    := $(HERMES_DIR)/hermes-agent
# Standalone skills symlinked into ~/.hermes/skills/. The former infrastructure,
# schedule, slack, tasks, weather, garmin-health and strength skills were
# consolidated into argo-api/references/*.md (commit 3087645) — they are no longer
# separate dirs, so listing them here only created dead symlinks.
HERMES_SKILLS := capture argo-api work karakeep obsidian reading wildrift research-gateway image-delivery homelab-ops homelab briefing-tts claude-dispatch

# Gateway plugins symlinked into ~/.hermes/plugins/. Same durability argument as the
# skills: a plugin that lives only under ~/.hermes/ is one `hermes update` away from
# being unreviewable state. dispatch-approval holds the Ed25519 key that makes the
# dispatch bridge's --confirm an artifact rather than an instruction — it must also be
# enabled once, with `hermes plugins enable dispatch-approval`.
HERMES_PLUGINS := dispatch-approval

# Scheduled jobs run as user LaunchAgents, not macOS crontab — see the Setup
# banner below for why. Templates live in launchd/, rendered into ~/Library/LaunchAgents.
LAUNCHD_DIR   := $(HERMES_REPO)/launchd
LAUNCHAGENTS  := $(HOME)/Library/LaunchAgents
HERMES_PLISTS := com.jkrumm.hermes-liveness com.jkrumm.hermes-backup

# TTS/STT is served by the audio-gateway (https://audio-gateway.jkrumm.com/v1),
# a VPS Docker container reached over the tailnet — Hermes only points its native
# openai TTS/STT providers at it in config.yaml. No local audio service to install.

# ============================================================================
# Setup — Mac Mini-only. Symlinks config + skills into ~/.hermes/, installs the
# liveness + backup LaunchAgents. Claude Code skills (hermes-validate,
# hermes-update) live committed at .claude/skills/ — no setup step needed; they
# auto-load when Claude is started inside this repo.
#
# `make setup` must be runnable non-interactively (from an agent on the headless
# mini, not just a human at a screen). Nothing in this chain may block on a TCC
# prompt — which is why the two scheduled jobs moved off macOS crontab, whose
# WRITE path (`crontab -`) needs Full Disk Access on the invoking process and
# hangs forever when it isn't granted. See _agents and cron-migrate below.
# ============================================================================

.PHONY: setup
setup:
	@echo ""
	@echo "  Setting up Hermes Agent (Mac Mini-only)..."
	@echo ""
	@$(MAKE) --no-print-directory _precheck
	@$(MAKE) --no-print-directory _symlinks
	@$(MAKE) --no-print-directory _agents
	@echo ""
	@echo "  Done. Follow-up:"
	@echo "    1. Create push monitors in UptimeKuma UI (Hermes Agent - Push, Hermes Backup - Push)"
	@echo "    2. Store push URLs:"
	@echo "         op item create --account tkrumm --vault hermes --category login \\"
	@echo "           --title uptime-kuma agent-push-url=<url> backup-push-url=<url>"
	@echo "    3. Confirm secrets resolve: 'make status' shows '✓ secrets (N refs …)'"
	@echo "       (no ~/.hermes/.env — config.yaml 'secrets.command' reads the secrets-run cache)"
	@echo ""

.PHONY: _precheck
_precheck:
	@echo "  Prerequisites..."
	@if ! command -v hermes >/dev/null 2>&1; then \
		echo "    ✗ hermes CLI not installed — run install per README.md §2"; \
		exit 1; \
	fi
	@echo "    ✓ hermes $$(hermes --version 2>/dev/null | head -1)"
	@mkdir -p "$(HERMES_DIR)"
	@mkdir -p "$(HERMES_DIR)/memories"
	@mkdir -p "$(HERMES_DIR)/skills"

.PHONY: _symlinks
_symlinks:
	@echo "  Hermes config symlinks..."
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/config.yaml" \
		DST="$(HERMES_DIR)/config.yaml"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/.env.tpl" \
		DST="$(HERMES_DIR)/.env.tpl"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/SOUL.md" \
		DST="$(HERMES_DIR)/SOUL.md"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/cron" \
		DST="$(HERMES_DIR)/cron"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/scripts" \
		DST="$(HERMES_DIR)/scripts"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/hooks" \
		DST="$(HERMES_DIR)/hooks"
	@$(MAKE) --no-print-directory _link \
		SRC="$(HERMES_REPO)/config" \
		DST="$(HERMES_DIR)/config"
	@for plugin in $(HERMES_PLUGINS); do \
		$(MAKE) --no-print-directory _link \
			SRC="$(HERMES_REPO)/plugins/$$plugin" \
			DST="$(HERMES_DIR)/plugins/$$plugin"; \
	done
	@for skill in $(HERMES_SKILLS); do \
		$(MAKE) --no-print-directory _link \
			SRC="$(HERMES_REPO)/skills/$$skill" \
			DST="$(HERMES_DIR)/skills/$$skill"; \
	done
	@$(MAKE) --no-print-directory _copy \
		SRC="$(HERMES_REPO)/USER.md" \
		DST="$(HERMES_DIR)/memories/USER.md"
	@if [[ ! -f "$(HERMES_REPO)/scripts/briefing-state.json" ]]; then \
		echo "  Seeding briefing-state.json from .example..."; \
		cp "$(HERMES_REPO)/scripts/briefing-state.example.json" \
			"$(HERMES_REPO)/scripts/briefing-state.json"; \
	fi
	@if [[ ! -f "$(HERMES_REPO)/skills/capture/state.json" ]]; then \
		echo "  Seeding capture/state.json from .example..."; \
		cp "$(HERMES_REPO)/skills/capture/state.example.json" \
			"$(HERMES_REPO)/skills/capture/state.json"; \
	fi
	@if [[ ! -f "$(HERMES_REPO)/skills/karakeep/state.json" ]]; then \
		echo "  Seeding karakeep/state.json from .example..."; \
		cp "$(HERMES_REPO)/skills/karakeep/state.example.json" \
			"$(HERMES_REPO)/skills/karakeep/state.json"; \
	fi

.PHONY: _agents
_agents:
	@echo "  LaunchAgents (liveness + backup, both ping UptimeKuma)..."
	@chmod +x $(HERMES_REPO)/scripts/hermes-liveness.sh $(HERMES_REPO)/scripts/hermes-backup.sh
	@mkdir -p "$(LAUNCHAGENTS)"
	@$(MAKE) --no-print-directory _render-plists PLISTS="$(HERMES_PLISTS)"
	@$(MAKE) --no-print-directory _legacy-cron-warn

# Renders __HOME__ into each $(LAUNCHD_DIR)/<label>.plist.template and (re)loads
# it only when the rendered content actually differs — so re-running `make setup`
# is a no-op that neither rewrites the file nor bounces a healthy agent. Same
# shape as dotfiles' _render-plists; kept local because this repo does not source
# that Makefile.
.PHONY: _render-plists
_render-plists:
	@for label in $(PLISTS); do \
		SRC="$(LAUNCHD_DIR)/$$label.plist.template"; \
		DST="$(LAUNCHAGENTS)/$$label.plist"; \
		TMP="$$(mktemp)"; \
		sed "s|__HOME__|$(HOME)|g" "$$SRC" > "$$TMP"; \
		if [ ! -f "$$DST" ] || ! diff -q "$$TMP" "$$DST" >/dev/null 2>&1; then \
			mv "$$TMP" "$$DST"; \
			launchctl unload "$$DST" 2>/dev/null || true; \
			launchctl load "$$DST"; \
			echo "    ✓ $$label (installed + loaded)"; \
		else \
			rm "$$TMP"; \
			echo "    · $$label (up to date)"; \
		fi; \
	done

# The liveness/backup jobs lived in macOS crontab until 2026-08-02. Leaving the
# old entries in place alongside the LaunchAgents double-fires both jobs — for
# the 03:00 backup that means two concurrent rsyncs onto the same destination, so
# this warns loudly rather than quietly tolerating the overlap. It does NOT clean
# up on its own: removing them is a `crontab -` WRITE, the exact TCC-blocking
# call this migration exists to keep out of `make setup`. That lives behind the
# explicit, bounded `make cron-migrate` below.
.PHONY: _legacy-cron-warn
_legacy-cron-warn:
	@if crontab -l 2>/dev/null | grep -q "hermes-liveness.sh\|hermes-backup.sh"; then \
		echo ""; \
		echo "    ⚠ legacy crontab entries still present — both jobs now fire TWICE"; \
		echo "      (the 03:00 backup would run two concurrent rsyncs to homelab)."; \
		echo "      Remove them once:  make cron-migrate"; \
	fi

## Remove the superseded hermes crontab entries (one-time, after the LaunchAgent
## migration). Separate from `make setup` on purpose: `crontab -` needs Full Disk
## Access on the invoking process, and without it macOS raises a TCC dialog that
## a headless mini has nobody to answer — the call then blocks indefinitely (one
## such `make setup` sat wedged for 19h). Bounded by `timeout` so the worst case
## is a 15s failure with instructions, never a hang. Run it from a terminal that
## HAS Full Disk Access (System Settings → Privacy & Security → Full Disk Access).
.PHONY: cron-migrate
cron-migrate:
	@if ! crontab -l 2>/dev/null | grep -q "hermes-liveness.sh\|hermes-backup.sh"; then \
		echo "  · no hermes crontab entries — nothing to migrate"; exit 0; \
	fi
	@TO=$$(command -v timeout || command -v gtimeout || true); \
	NEW=$$(crontab -l 2>/dev/null | grep -v "hermes-liveness.sh" | grep -v "hermes-backup.sh"); \
	if [ -z "$$TO" ]; then \
		echo "  ✗ no 'timeout' binary — refusing to run an unbounded 'crontab -'."; \
		echo "    brew install coreutils, or edit by hand: crontab -e"; exit 1; \
	fi; \
	if printf '%s\n' "$$NEW" | sed '/^$$/d' | $$TO 15 crontab -; then \
		echo "  ✓ hermes crontab entries removed (jobs now run as LaunchAgents)"; \
	else \
		echo "  ✗ 'crontab -' failed or timed out — almost certainly a TCC prompt"; \
		echo "    this process cannot answer. Re-run from a terminal with Full Disk"; \
		echo "    Access, or remove the two hermes lines by hand: crontab -e"; \
		exit 1; \
	fi

## Unload + remove the liveness/backup LaunchAgents.
.PHONY: agents-teardown
agents-teardown:
	@for label in $(HERMES_PLISTS); do \
		PLIST="$(LAUNCHAGENTS)/$$label.plist"; \
		launchctl unload "$$PLIST" 2>/dev/null || true; \
		rm -f "$$PLIST"; \
		echo "  ✓ $$label torn down (unloaded + plist removed)"; \
	done

# ============================================================================
# Status
# ============================================================================

.PHONY: status
status:
	@echo ""
	@echo "  Hermes setup status"
	@command -v hermes >/dev/null 2>&1 \
		&& echo "    ✓ hermes CLI" \
		|| echo "    ✗ hermes CLI [not installed]"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/config.yaml"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/.env.tpl"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/SOUL.md"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/cron"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/hooks"
	@$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/config"
	@for skill in $(HERMES_SKILLS); do \
		$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/skills/$$skill"; \
	done
	@# Dispatch bridge. dispatch-repos.json is the whole bounding mechanism for
	@# hermes-cc.sh — the root it resolves names under, the deny list, and the tier
	@# ceilings — so an unreadable or contradictory one must be loud here. The validator
	@# re-runs the checks hermes-cc.sh makes at dispatch time: hermes-cc.sh fails CLOSED
	@# on a malformed policy, which is correct but surfaces mid-incident on the first
	@# dispatch. Catch it at setup instead, while nobody is waiting on an answer.
	@if [ -x "$(HERMES_REPO)/scripts/hermes-cc.sh" ]; then \
		out=$$(python3 "$(HERMES_REPO)/scripts/validate-dispatch-policy.py" "$(HERMES_DIR)/config/dispatch-repos.json" 2>&1); \
		if [ $$? -eq 0 ]; then \
			echo "    ✓ hermes-cc.sh ($$out)"; \
		else \
			echo "    ✗ hermes-cc.sh [dispatch-repos.json unusable: $$out]"; \
		fi; \
	else \
		echo "    ✗ hermes-cc.sh [missing or not executable]"; \
	fi
	@curl -fsS --max-time 5 http://localhost:7705/health >/dev/null 2>&1 \
		&& echo "    ✓ sideclaw job server (:7705, dispatch backend)" \
		|| echo "    ✗ sideclaw job server [:7705 unreachable — dispatch would fail with exit 3]"
	@# Secrets resolve natively via config.yaml `secrets.command` -> the dotfiles
	@# secrets-run cache. There is deliberately no ~/.hermes/.env any more, so this
	@# asserts the helper actually renders refs rather than checking for a file.
	@n=$$($(HOME)/.local/bin/secrets-run export --env-file="$(HERMES_DIR)/.env.tpl" 2>/dev/null | grep -c '^export ' || true); \
	if [ "$${n:-0}" -gt 0 ]; then \
		echo "    ✓ secrets ($$n refs via secrets-run cache)"; \
	else \
		echo "    ✗ secrets [secrets-run resolved nothing — gateway would start credential-less]"; \
	fi
	@curl -fsS https://audio-gateway.jkrumm.com/health >/dev/null 2>&1 \
		&& echo "    ✓ audio-gateway (TTS/STT)" \
		|| echo "    ✗ audio-gateway [not reachable — VPS Docker container over tailnet]"
	@# Scheduled jobs. `launchctl list` reporting the label is the load check;
	@# a loaded-but-missing plist would survive a reboot only by luck, so assert
	@# the rendered file too.
	@for label in $(HERMES_PLISTS); do \
		if launchctl list 2>/dev/null | grep -q "$$label" && [ -f "$(LAUNCHAGENTS)/$$label.plist" ]; then \
			echo "    ✓ $$label"; \
		elif [ -f "$(LAUNCHAGENTS)/$$label.plist" ]; then \
			echo "    ✗ $$label [plist present but not loaded — run make setup]"; \
		else \
			echo "    ✗ $$label [missing — run make setup]"; \
		fi; \
	done
	@if crontab -l 2>/dev/null | grep -q "hermes-liveness.sh\|hermes-backup.sh"; then \
		echo "    ✗ legacy crontab entries [double-firing — run make cron-migrate]"; \
	fi
	@# Every skill a cron job preloads must actually resolve. The scheduler only
	@# logs a WARNING and runs anyway when one doesn't (cron/scheduler.py: "skill
	@# not found, skipping"), and the watchdog matches ERROR|CRITICAL only — so a
	@# renamed skill rots here invisibly. It did: the 2026-06 consolidation into
	@# argo-api/references/ left 7 dead names in the briefings for weeks.
	@python3 -c 'import json,os,sys;\
p=os.path.expanduser("$(HERMES_DIR)/cron/jobs.json");\
sys.exit(0) if not os.path.exists(p) else None;\
d=json.load(open(p));\
bad=sorted({(j.get("name"),s) for j in d.get("jobs",[]) for s in (j.get("skills") or []) if not os.path.exists(os.path.expanduser("$(HERMES_DIR)/skills/"+s))});\
[print("    ✗ cron skill \"%s\" missing [job: %s]" % (s,n)) for n,s in bad];\
print("    ✓ cron job skills resolve") if not bad else None' 2>/dev/null \
		|| echo "    ✗ cron job skills [could not read jobs.json]"
	@$(MAKE) --no-print-directory patch-check
	@# Hermes writes into this repo through the skill symlinks during ordinary
	@# foreground use — it has authored whole nested skills under skills/homelab/
	@# and patched skills/homelab-ops/references/ in place. Those edits are real
	@# work and they are protected from the background curator (they resolve under
	@# skills.external_dirs), but nothing commits them and the watchdog's
	@# stray_skill source cannot see them: it skips symlinked top-level dirs, and
	@# would exclude anything under external_dirs anyway. Git is the only thing
	@# that notices, so ask it.
	@d=$$(git -C "$(HERMES_REPO)" status --porcelain -- skills 2>/dev/null); \
	if [ -z "$$d" ]; then \
		echo "    ✓ skills/ committed"; \
	else \
		echo "    ✗ skills/ has uncommitted agent-written content [read it, then commit or delete]"; \
		echo "$$d" | sed 's/^/        /'; \
	fi
	@echo "  CC skills (per-repo, auto-loaded by Claude Code inside this dir)"
	@for skill in hermes-update hermes-validate; do \
		if [ -d ".claude/skills/$$skill" ]; then \
			echo "    ✓ $$skill"; \
		else \
			echo "    ✗ $$skill [missing in .claude/skills/]"; \
		fi; \
	done
	@echo ""

# ============================================================================
# Local patches
# ============================================================================

# Asserts every patch in patches/ is currently applied to the live checkout.
#
# `git apply --reverse --check` succeeds exactly when a patch is already
# present, so this proves applied-ness without a worktree, without writing
# anything, and in milliseconds — cheap enough for `make status` to run on
# every invocation. It is the fast half of the guarantee the /hermes-update
# skill's byte-compare gives: that check also proves no *unpatched* local edit
# exists, which needs a scratch worktree and belongs in the update flow.
#
# Two distinct failures, deliberately reported apart, because the fixes differ:
#   not applied  — an update reset the tree and the re-apply loop was skipped
#                  or silently failed. Re-run the loop.
#   drifted      — the live file was edited past what the patch records. The
#                  patch is now the STALE half, and the next update's re-apply
#                  would silently revert the newer work. Regenerate it:
#                  git -C $(HERMES_SRC) diff HEAD -- <file> > patches/<name>.patch
.PHONY: patch-check
patch-check:
	@if [ ! -d "$(HERMES_SRC)/.git" ]; then \
		echo "    ✗ local patches [$(HERMES_SRC) is not a git checkout]"; exit 0; \
	fi; \
	ok=0; bad=""; \
	for p in "$(HERMES_REPO)"/patches/*.patch; do \
		[ -e "$$p" ] || continue; \
		n=$$(basename "$$p"); \
		f=$$(sed -n 's|^--- a/||p' "$$p" | head -1); \
		if git -C "$(HERMES_SRC)" apply --reverse --check "$$p" >/dev/null 2>&1; then \
			ok=$$((ok+1)); \
		elif [ -n "$$f" ] && ! git -C "$(HERMES_SRC)" diff --quiet HEAD -- "$$f" 2>/dev/null; then \
			bad="$$bad\n        · $$n [drifted — $$f is edited past the patch; regenerate]"; \
		else \
			bad="$$bad\n        · $$n [not applied — re-run the re-apply loop]"; \
		fi; \
	done; \
	total=$$(ls "$(HERMES_REPO)"/patches/*.patch 2>/dev/null | wc -l | tr -d ' '); \
	if [ -z "$$bad" ]; then \
		echo "    ✓ local patches ($$ok/$$total applied)"; \
	else \
		echo "    ✗ local patches ($$ok/$$total applied)"; \
		printf "$$bad\n"; \
	fi

# ============================================================================
# Helpers (lifted from dotfiles Makefile)
# ============================================================================

.PHONY: _link
_link:
	@if [ -L "$(DST)" ] && [ "$$(readlink $(DST))" = "$(SRC)" ]; then \
		echo "    · $(notdir $(DST)) (ok)"; \
	else \
		if [ -e "$(DST)" ] && [ ! -L "$(DST)" ]; then \
			echo "    Backing up $(DST) → $(DST).bak"; \
			mv "$(DST)" "$(DST).bak"; \
		fi; \
		ln -sfn "$(SRC)" "$(DST)"; \
		echo "    ✓ $(notdir $(DST))"; \
	fi

.PHONY: _copy
_copy:
	@if [ -f "$(DST)" ] && cmp -s "$(SRC)" "$(DST)"; then \
		echo "    · $(notdir $(DST)) (ok)"; \
	else \
		cp "$(SRC)" "$(DST)"; \
		echo "    ✓ $(notdir $(DST)) (copied)"; \
	fi

.PHONY: _check
_check:
	@if [ -L "$(DST)" ] && [ -e "$(DST)" ]; then \
		echo "    ✓ $(notdir $(DST))"; \
	elif [ -L "$(DST)" ]; then \
		echo "    ✗ $(notdir $(DST)) [BROKEN]"; \
	elif [ -e "$(DST)" ]; then \
		echo "    ✗ $(notdir $(DST)) [real file — run make setup]"; \
	else \
		echo "    ✗ $(notdir $(DST)) [missing — run make setup]"; \
	fi

# ============================================================================
# Help
# ============================================================================

.PHONY: help
help:
	@echo ""
	@echo "  hermes-agent"
	@echo ""
	@echo "  make setup           Mac Mini-only — config symlinks, LaunchAgents, CC skills"
	@echo "  make status          Verify symlinks, audio-gateway, LaunchAgents, CC skills"
	@echo "  make patch-check     Assert every patches/*.patch is applied to the live checkout"
	@echo "  make cron-migrate    One-time — drop the superseded crontab entries"
	@echo "  make agents-teardown Unload + remove the liveness/backup LaunchAgents"
	@echo ""
