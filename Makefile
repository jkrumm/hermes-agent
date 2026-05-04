HERMES_REPO   := $(shell pwd)
HERMES_DIR    := $(HOME)/.hermes
SOURCEROOT    := $(HOME)/SourceRoot
CLAUDE_DIR    := $(SOURCEROOT)/.claude
DOTFILES_DIR  := $(SOURCEROOT)/dotfiles
LAUNCHAGENTS  := $(HOME)/Library/LaunchAgents
HERMES_SKILLS := capture homelab-api infrastructure schedule slack tasks weather
CC_SKILLS     := hermes-validate hermes-update

# localai-helper plist template lives in dotfiles. Helper service runs only
# on Mac Mini for Hermes; rendered + loaded as part of `make setup` here.
LOCALAI_DIR   := $(DOTFILES_DIR)/localai
HELPER_PLIST  := com.localai.helper

# ============================================================================
# Setup — Mac Mini-only. Symlinks config + skills into ~/.hermes/, renders the
# localai-helper plist, installs liveness + backup cron, symlinks CC skills
# (hermes-validate, hermes-update) into ~/SourceRoot/.claude/skills/.
# ============================================================================

.PHONY: setup
setup:
	@echo ""
	@echo "  Setting up Hermes Agent (Mac Mini-only)..."
	@echo ""
	@$(MAKE) --no-print-directory _precheck
	@$(MAKE) --no-print-directory _symlinks
	@$(MAKE) --no-print-directory _helper
	@$(MAKE) --no-print-directory _cron
	@$(MAKE) --no-print-directory _cc-skills
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
	@if [ ! -d "$(LOCALAI_DIR)" ]; then \
		echo "    ✗ dotfiles not found at $(DOTFILES_DIR) — clone it before running make setup"; \
		exit 1; \
	fi
	@echo "    ✓ dotfiles found (localai-helper plist source)"
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

.PHONY: _helper
_helper:
	@echo "  localai-helper (FastAPI orchestration on :8001)..."
	@mkdir -p "$(LAUNCHAGENTS)"
	@SRC="$(LOCALAI_DIR)/$(HELPER_PLIST).plist.template"; \
	DST="$(LAUNCHAGENTS)/$(HELPER_PLIST).plist"; \
	TMP="$$(mktemp)"; \
	sed "s|__HOME__|$(HOME)|g" "$$SRC" > "$$TMP"; \
	if [ ! -f "$$DST" ] || ! diff -q "$$TMP" "$$DST" >/dev/null 2>&1; then \
		mv "$$TMP" "$$DST"; \
		launchctl unload "$$DST" 2>/dev/null || true; \
		launchctl load "$$DST"; \
		echo "    ✓ $(HELPER_PLIST) (installed + loaded)"; \
	else \
		rm "$$TMP"; \
		echo "    · $(HELPER_PLIST) (up to date)"; \
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

.PHONY: _cc-skills
_cc-skills:
	@echo "  Claude Code skills (symlinked into $$SOURCEROOT/.claude/skills/)..."
	@mkdir -p "$(CLAUDE_DIR)/skills"
	@for skill in $(CC_SKILLS); do \
		$(MAKE) --no-print-directory _link \
			SRC="$(HERMES_REPO)/cc-skills/$$skill" \
			DST="$(CLAUDE_DIR)/skills/$$skill"; \
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
	@for skill in $(HERMES_SKILLS); do \
		$(MAKE) --no-print-directory _check DST="$(HERMES_DIR)/skills/$$skill"; \
	done
	@[ -f "$(HERMES_DIR)/.env" ] \
		&& echo "    ✓ .env (rebuilt from 1Password)" \
		|| echo "    ✗ .env [missing — see README.md \"Rebuild .env\"]"
	@[ -f "$(LAUNCHAGENTS)/$(HELPER_PLIST).plist" ] \
		&& echo "    ✓ $(HELPER_PLIST).plist" \
		|| echo "    ✗ $(HELPER_PLIST).plist [missing — run make setup]"
	@crontab -l 2>/dev/null | grep -q "hermes-liveness.sh" \
		&& echo "    ✓ liveness cron" \
		|| echo "    ✗ liveness cron [missing — run make setup]"
	@crontab -l 2>/dev/null | grep -q "hermes-backup.sh" \
		&& echo "    ✓ backup cron" \
		|| echo "    ✗ backup cron [missing — run make setup]"
	@echo "  CC skills"
	@for skill in $(CC_SKILLS); do \
		$(MAKE) --no-print-directory _check DST="$(CLAUDE_DIR)/skills/$$skill"; \
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
	@echo "  make setup    Mac Mini-only — config symlinks, helper plist, cron, CC skills"
	@echo "  make status   Verify symlinks, helper plist, crontab, CC skills"
	@echo ""
