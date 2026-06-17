HERMES_REPO   := $(shell pwd)
HERMES_DIR    := $(HOME)/.hermes
# Standalone skills symlinked into ~/.hermes/skills/. The former infrastructure,
# schedule, slack, tasks, weather, garmin-health and strength skills were
# consolidated into argo-api/references/*.md (commit 3087645) — they are no longer
# separate dirs, so listing them here only created dead symlinks.
HERMES_SKILLS := capture argo-api work karakeep obsidian

# TTS/STT is served by the audio-gateway (https://audio-gateway.jkrumm.com/v1),
# a VPS Docker container reached over the tailnet — Hermes only points its native
# openai TTS/STT providers at it in config.yaml. No local audio service to install.

# ============================================================================
# Setup — Mac Mini-only. Symlinks config + skills into ~/.hermes/, installs
# liveness + backup cron. Claude Code skills (hermes-validate, hermes-update)
# live committed at .claude/skills/ — no setup step needed; they auto-load when
# Claude is started inside this repo.
# ============================================================================

.PHONY: setup
setup:
	@echo ""
	@echo "  Setting up Hermes Agent (Mac Mini-only)..."
	@echo ""
	@$(MAKE) --no-print-directory _precheck
	@$(MAKE) --no-print-directory _symlinks
	@$(MAKE) --no-print-directory _cron
	@echo ""
	@echo "  Done. Follow-up:"
	@echo "    1. Create push monitors in UptimeKuma UI (Hermes Agent - Push, Hermes Backup - Push)"
	@echo "    2. Store push URLs:"
	@echo "         op item create --account tkrumm --vault hermes --category login \\"
	@echo "           --title uptime-kuma agent-push-url=<url> backup-push-url=<url>"
	@echo "    3. Rebuild ~/.hermes/.env (see README.md \"Rebuild .env\")"
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

.PHONY: _cron
_cron:
	@echo "  Cron (liveness + backup, both ping UptimeKuma)..."
	@chmod +x $(HERMES_REPO)/scripts/hermes-liveness.sh $(HERMES_REPO)/scripts/hermes-backup.sh
	@LIVENESS="*/5 * * * * $(HERMES_REPO)/scripts/hermes-liveness.sh >> /tmp/hermes-liveness.log 2>&1"; \
	BACKUP="0 3 * * * $(HERMES_REPO)/scripts/hermes-backup.sh >> /tmp/hermes-backup.log 2>&1"; \
	CURRENT=$$(crontab -l 2>/dev/null || true); \
	NEW=$$(echo "$$CURRENT" | grep -v "hermes-liveness.sh" | grep -v "hermes-backup.sh"); \
	printf '%s\n%s\n%s\n' "$$NEW" "$$LIVENESS" "$$BACKUP" | sed '/^$$/d' | crontab -; \
	echo "    ✓ crontab installed (*/5 liveness, 03:00 backup)"

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
	@for skill in $(HERMES_SKILLS); do \
		$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/skills/$$skill"; \
	done
	@[ -f "$(HERMES_DIR)/.env" ] \
		&& echo "    ✓ .env (rebuilt from 1Password)" \
		|| echo "    ✗ .env [missing — see README.md \"Rebuild .env\"]"
	@curl -fsS https://audio-gateway.jkrumm.com/health >/dev/null 2>&1 \
		&& echo "    ✓ audio-gateway (TTS/STT)" \
		|| echo "    ✗ audio-gateway [not reachable — VPS Docker container over tailnet]"
	@crontab -l 2>/dev/null | grep -q "hermes-liveness.sh" \
		&& echo "    ✓ liveness cron" \
		|| echo "    ✗ liveness cron [missing — run make setup]"
	@crontab -l 2>/dev/null | grep -q "hermes-backup.sh" \
		&& echo "    ✓ backup cron" \
		|| echo "    ✗ backup cron [missing — run make setup]"
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
	@echo "  make setup    Mac Mini-only — config symlinks, cron, CC skills"
	@echo "  make status   Verify symlinks, audio-gateway, crontab, CC skills"
	@echo ""
