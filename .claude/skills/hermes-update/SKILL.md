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

Eight local mods. Source-of-truth list (with re-apply commands and *why* each is needed) lives in `~/SourceRoot/hermes-agent/CLAUDE.md` under "Local Modifications to Upstream". This file is the operational playbook.

> The `auxiliary-client-gpt5-max-completion-tokens` patch was **retired at v0.15.1** — upstream rewrote `_build_call_kwargs` to omit `max_tokens` by default for non-Anthropic custom endpoints, which supersedes it. See CLAUDE.md for the retirement note.

Files touched (all are `.patch` files applied with `git apply` — no full-file replacements):

| File | Patch | Kind |
|-|-|-|
| `agent/auxiliary_client.py` | `patches/auxiliary-client-anthropic-mode-respect.patch` | respect `api_mode: anthropic_messages` for custom base URLs |
| `gateway/platforms/slack.py` | `patches/slack-cannot-reply-to-message.patch` | three-part mrkdwn + thread fallback |
| `gateway/platforms/base.py` | `patches/slack-media-inline-reply-anchor.patch` | pass text reply anchor to media senders so attachments don't thread |
| `cron/scheduler.py` | `patches/scheduler-skip-resolver-for-slack-ids.patch` | skip channel resolver for raw `C…` IDs |
| `run_agent.py` | `patches/run-agent-third-party-endpoint-token-refresh.patch` | broaden third-party endpoint skip to all non-anthropic.com hosts |
| `tools/tirith_security.py` | `patches/tirith-allowlist-argo-pipes.patch` | allowlist argo-only pipelines past tirith |
| `tools/cronjob_tools.py` | `patches/cronjob-tools-allowlist-argo-bearer.patch` | allowlist argo bearer curls past the cron-prompt scanner |
| `tools/tts_tool.py` | `patches/tts-tool-audio-title.patch` | name the audio file from the audio-gateway's `X-Audio-Title` header (gpt-5.4-mini title) instead of `tts_<timestamp>` |

> **STT is not patched.** `tools/transcription_tools.py` (native `openai` STT → `gpt-4o-transcribe`) is pointed at the audio-gateway purely via `config.yaml`. TTS uses the stock native `openai` provider (→ Gemini Charon via the audio-gateway) plus the one small `tts-tool-audio-title` patch above for the filename. After an update, confirm `config.yaml`'s `tts.openai` / `stt.openai` `base_url` still reads `https://audio-gateway.jkrumm.com/v1`.

### Re-apply procedure

```bash
# All eight are .patch files. Use --3way so upstream context shifts get auto-merged.
cd ~/.hermes/hermes-agent
for p in auxiliary-client-anthropic-mode-respect \
         slack-cannot-reply-to-message \
         slack-media-inline-reply-anchor \
         scheduler-skip-resolver-for-slack-ids \
         run-agent-third-party-endpoint-token-refresh \
         tirith-allowlist-argo-pipes \
         cronjob-tools-allowlist-argo-bearer \
         tts-tool-audio-title; do
  git apply --3way ~/SourceRoot/hermes-agent/patches/${p}.patch
done
```

If a `git apply` fails outright (not just a context shift), inspect the upstream file by hand — the patch was written for a specific surrounding shape and may need a new version. The original purpose of each patch is documented in `CLAUDE.md`; rewrite the patch against current upstream and commit the new `.patch` file back to `patches/`.

### What `hermes update` does on its own

`hermes update` stashes your working changes, pulls upstream, then tries to re-apply the stash. Expect conflicts on the eight patched files — that is normal. The CLI prints the stash ref (`Restore your changes later with: git stash apply <sha>`); keep it as a fallback. After conflicts surface, the CLI resets the working tree clean — re-apply via the loop above.

### Bundled-skill reconciliation

Upstream ships a **stock bundled `obsidian` skill** (generic, filesystem-first) in the `.bundled_manifest`. Our repo provides a tailored local `obsidian` skill (CLI-first, real vault conventions) symlinked into `~/.hermes/skills/obsidian`. Same name → on an update the stock one re-seeds to `~/.hermes/skills/note-taking/obsidian/` and shadows ours. Remove it so our local skill is the only `obsidian`:

```bash
rm -rf ~/.hermes/skills/note-taking/obsidian
# verify ours is active (resolves to the repo, not note-taking/):
readlink ~/.hermes/skills/obsidian   # → ~/SourceRoot/hermes-agent/skills/obsidian
hermes skills list | grep obsidian   # source label may read "builtin" (name is in the
                                      # bundled manifest) — cosmetic; an empty category
                                      # column means the top-level symlink (ours) is loaded
```

(`karakeep` has a unique name, so it never collides.)

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

Send a message in `#hermes` on Slack and confirm a response. To verify TTS, ask for a voice memo (e.g. "speak this") and check `~/.hermes/audio_cache/` for an MP3 named after a gpt-5.4-mini title (not `tts_<timestamp>`) — it's Gemini Charon via the audio-gateway (`https://audio-gateway.jkrumm.com/v1`). Test a German message too: Charon should pronounce German natively (no translation to English), and the audio attachment should land **inline** in the channel, not in a thread.
