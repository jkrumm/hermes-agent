---
name: hermes-update
description: Update Hermes Agent to latest version, resolve conflicts in locally-modified source files, and restart the gateway
---

# hermes-update

Updates `~/.hermes/hermes-agent/` from upstream, re-applies local customizations if upstream changed the same files, then restarts the gateway.

## Run the update

```bash
hermes update
```

Then check what happened:

```bash
cd ~/.hermes/hermes-agent && git status --short
```

If clean: jump straight to **Restart**. If conflicts or upstream rewrote a customized file: see below.

---

## Known local modifications

Seven local mods. Source-of-truth list (with re-apply commands and *why* each is needed) lives in `~/SourceRoot/hermes-agent/CLAUDE.md` under "Local Modifications to Upstream". This file is the operational playbook.

Files touched:

| File | Patch | Kind |
|-|-|-|
| `tools/tts_tool.py` | `patches/tts_tool.py` | full file replacement (~2200 → ~160 lines) |
| `tools/tts_fast_tool.py` | `patches/tts_fast_tool.py` | new file (additive, auto-discovered) |
| `gateway/platforms/slack.py` | `patches/slack-cannot-reply-to-message.patch` | three-part mrkdwn + thread fallback |
| `cron/scheduler.py` | `patches/scheduler-skip-resolver-for-slack-ids.patch` | skip channel resolver for raw `C…` IDs |
| `run_agent.py` | `patches/run-agent-third-party-endpoint-token-refresh.patch` | broaden third-party endpoint skip to all non-anthropic.com hosts |
| `toolsets.py` | `patches/toolsets-expose-text-to-speech-fast.patch` | expose `text_to_speech_fast` in the `tts` toolset |
| `agent/auxiliary_client.py` | `patches/auxiliary-client-anthropic-mode-respect.patch` | respect `api_mode: anthropic_messages` for custom base URLs |

### Re-apply procedure

```bash
# 1. The two TTS files are full replacements — copy, don't apply.
cp ~/SourceRoot/hermes-agent/patches/tts_tool.py      ~/.hermes/hermes-agent/tools/tts_tool.py
cp ~/SourceRoot/hermes-agent/patches/tts_fast_tool.py ~/.hermes/hermes-agent/tools/tts_fast_tool.py
rm -f ~/.hermes/hermes-agent/tools/__pycache__/tts_tool*.pyc

# 2. The five .patch files. Use --3way so upstream context shifts get auto-merged.
cd ~/.hermes/hermes-agent
for p in slack-cannot-reply-to-message \
         scheduler-skip-resolver-for-slack-ids \
         run-agent-third-party-endpoint-token-refresh \
         toolsets-expose-text-to-speech-fast \
         auxiliary-client-anthropic-mode-respect; do
  git apply --3way ~/SourceRoot/hermes-agent/patches/${p}.patch
done
```

If a `git apply` fails outright (not just a context shift), inspect the upstream file by hand — the patch was written for a specific surrounding shape and may need a new version. The original purpose of each patch is documented in `CLAUDE.md`; rewrite the patch against current upstream and commit the new `.patch` file back to `patches/`.

### What `hermes update` does on its own

`hermes update` stashes your working changes, pulls upstream, then tries to re-apply the stash. Expect conflicts on the five patched files — that is normal. The CLI prints the stash ref (`Restore your changes later with: git stash apply <sha>`); keep it as a fallback. After conflicts surface, the CLI resets the working tree clean — re-apply via the loop above.

---

## Restart

```bash
launchctl unload ~/Library/LaunchAgents/ai.hermes.gateway.plist
sleep 2
launchctl load ~/Library/LaunchAgents/ai.hermes.gateway.plist
```

Verify it came up:

```bash
tail -20 ~/.hermes/logs/gateway.log
```

## Verify

Send a message in `#hermes` on Slack and confirm a response. If TTS was touched, send a message that triggers voice output and check `~/.hermes/cache/audio/` for an MP3 with a sensible title. For `text_to_speech_fast`, ask explicitly for fast/Supertonic TTS — distinct LLM-facing tool.
