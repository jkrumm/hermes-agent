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

> The `auxiliary-client-gpt5-max-completion-tokens` patch was **retired at v0.15.1** — upstream rewrote `_build_call_kwargs` to omit `max_tokens` by default for non-Anthropic custom endpoints, which supersedes it. The `slack-audio-mime-ext` patch was **retired at v0.18.2** — upstream's own `_resolve_slack_audio_ext()` helper now does the same MIME→extension mapping more thoroughly. The `_resolve_thread_ts` **synthetic-thread guard hunk** was **retired at v0.19.0** with the switch to `reply_in_thread: true` — it was already unreachable (upstream's flat-reply branch returns first) and would have been actively harmful once threads were on. See CLAUDE.md for all three retirement notes.
>
> **Secrets no longer come from a launch wrapper (v0.19.0+).** `scripts/gateway-cache-launch.sh` is gone; Hermes resolves its own secrets via `secrets.command` in `config.yaml` (→ the dotfiles `secrets-run` cache). After any update, confirm `hermes gateway status` prints `Command helper: applied 26 secrets`. If that line is missing the gateway will start **credential-less** (the source degrades with a warning rather than failing closed) — check `secrets-run export --env-file=~/.hermes/.env.tpl` by hand before debugging anything else.
>
> **v0.18.x platform rewrite:** upstream moved built-in chat platforms out of `gateway/platforms/` into a plugin system — Slack now lives at `plugins/platforms/slack/adapter.py` (was `gateway/platforms/slack.py`, which no longer exists). Only the Slack-targeting patch's *path* changed; `gateway/platforms/base.py` (shared response-delivery base class) stayed in place.

Files touched (all are `.patch` files applied with `git apply` — no full-file replacements):

| File | Patch | Kind |
|-|-|-|
| `agent/auxiliary_client.py` | `patches/auxiliary-client-anthropic-mode-respect.patch` | respect `api_mode: anthropic_messages` for custom base URLs |
| `plugins/platforms/slack/adapter.py` | `patches/slack-cannot-reply-to-message.patch` | mrkdwn normalization + `cannot_reply_to_message` retry (3 hunks; the synthetic-thread guard was **retired at v0.19.0**) |
| `gateway/platforms/base.py` | `patches/slack-media-inline-reply-anchor.patch` | pass text reply anchor to media senders so attachments don't thread |
| `cron/scheduler.py` | `patches/scheduler-skip-resolver-for-slack-ids.patch` | skip channel resolver for raw `C…` IDs |
| `run_agent.py` | `patches/run-agent-third-party-endpoint-token-refresh.patch` | broaden third-party endpoint skip to all non-anthropic.com hosts |
| `tools/tirith_security.py` | `patches/tirith-argo-allowlist-and-download-guard.patch` | two local rules: allowlist argo-only pipelines past tirith **and** block download-then-execute (renamed from `tirith-allowlist-argo-pipes.patch` at v0.19.0) |
| `tools/cronjob_tools.py` | `patches/cronjob-tools-allowlist-argo-bearer.patch` | allowlist argo bearer curls past the cron-prompt scanner |
| `tools/tts_tool.py` | `patches/tts-tool-audio-title.patch` | name the audio file from the audio-gateway's `X-Audio-Title` header (DeepSeek-V4-Pro title from the gateway's prep step) instead of `tts_<timestamp>` |

> **STT is not patched.** `tools/transcription_tools.py` (native `openai` STT → `gpt-4o-transcribe`) is pointed at the audio-gateway purely via `config.yaml`. TTS uses the stock native `openai` provider (→ Gemini Charon via the audio-gateway) plus the one small `tts-tool-audio-title` patch above for the filename. After an update, confirm `config.yaml`'s `tts.openai` / `stt.openai` `base_url` still reads `https://audio-gateway.jkrumm.com/v1`.

### Re-apply procedure

```bash
# All eight are .patch files. Use --3way so upstream context shifts get auto-merged.
cd ~/.hermes/hermes-agent
for p in ~/SourceRoot/hermes-agent/patches/*.patch; do
  echo "=== $(basename "$p")"
  git apply --3way "$p"
done
```

> Glob the directory rather than hardcoding names — the list has churned twice now
> (two retirements, one rename), and a stale hardcoded loop silently skips a patch.

**`git apply --3way` STAGES what it applies.** So right after the loop, plain `git diff`
is *empty* and `git status` shows `M`/`UU` — it looks like nothing landed. Always diff
against the commit:

```bash
git diff HEAD --stat          # the real picture: your local mods vs upstream
git diff HEAD --name-only     # should be exactly the patched files, nothing more
```

**Finish the merge: `UU` must not survive the session.** Hand-resolving a `--3way`
conflict edits the *file*; the **index** still records the conflict until you `git add`
it. The tree then looks perfectly healthy — no markers, valid syntax, correct behaviour —
while `git status --short` quietly shows `UU`. The bill comes due at the *next*
`hermes update`, whose first step is a stash: **`git stash` refuses to run on an unmerged
index** (`needs merge` / `cannot save the current index state`), so the update aborts
before it pulls anything. This was found by audit one update later, not by anything that
failed at the time. Always end with:

```bash
git ls-files -u        # MUST be empty
git status --short     # every patched file `M `, never `UU`
```

**The definitive check is a byte-compare, not a diffstat.** Reconstruct the tree from the
patch files alone in a scratch worktree and compare it to the live checkout — this proves
both "every local change is captured in a patch" and "no patch drifted from what's live":

```bash
git worktree add /tmp/hermes-verify HEAD --detach
cd /tmp/hermes-verify && for p in ~/SourceRoot/hermes-agent/patches/*.patch; do git apply "$p"; done
for f in $(git diff --name-only); do
  diff -q "$f" "$HOME/.hermes/hermes-agent/$f" || echo "DRIFT: $f"
done
cd - && git -C ~/.hermes/hermes-agent worktree remove /tmp/hermes-verify --force
```

Watch the worktree's own state while doing this: once you've applied the patches into it,
it is no longer pristine, so any "what does upstream look like?" read from it is
**tainted**. Use `git show HEAD:<path>` or `git checkout -- .` first. (An audit briefly
concluded upstream had adopted one of our patches, having read it back out of the
worktree it had just patched.)

If a `git apply` fails outright (not just a context shift), figure out **which** of three things happened before touching anything — they need different fixes:

1. **File moved/renamed (upstream restructure).** `error: <file> ist nicht im Index` / "not in index" means the target path no longer exists — not a diff mismatch. Don't hand-edit the patch's path and retry blindly. Find where the code went: `grep -rl "<a distinctive function/class name from the patch>" .` (e.g. a class name like `SlackAdapter`, or a helper the patch touches) across the new tree. A major version jump (this repo went v0.16.0 → v0.18.2 in one `hermes update`, 4184 commits) can move whole subsystems — the v0.18.x jump moved every built-in chat platform from `gateway/platforms/*.py` into a `plugins/platforms/<name>/adapter.py` plugin layout. Once you've found the new home, read both the old file (recoverable from the pre-update stash — see below) and the new one, then hand-port each patch hunk into the new structure and update the patch's file path in its own `diff --git a/... b/...` header. Update the path in this skill's table + reapply loop too.
2. **File exists, hunk conflicts (`git apply --3way` leaves `<<<<<<< ours` / `>>>>>>> theirs` markers).** This is a real 3-way merge conflict — see *Resolving 3-way conflict markers* below.
3. **The patch's *purpose* is now upstream's own behavior.** Before spending time on either of the above, check whether upstream independently fixed the same bug or added the same feature — see *Is this patch even still needed?* below. A patch whose target is superseded should be retired, not repaired.

**Recovering the pre-update file for comparison:** `hermes update`'s stash-conflict-reset (see below) leaves a stash ref and prints "Stash ref: `<sha>`" — that ref/commit still has the fully-patched pre-update file even after the working tree resets clean:
```bash
git show <stash-sha>:path/to/old-file.py > /tmp/old-file.py
```
Diff `/tmp/old-file.py` against the new file's likely counterpart to see what upstream changed structurally, independent of your own patch hunks.

### Verify each patch's *semantics*, not that it "applied cleanly"

`git apply --3way` reporting success proves the hunks merged, **not** that the behaviour
survived. Upstream can rewrite a function around your hunk so it still applies but no
longer does what it did. After the loop, grep each patch's distinctive marker and confirm
the file set:

```bash
git diff HEAD --name-only        # must be exactly the patched files
grep -n "_rename_with_title"          tools/tts_tool.py
grep -n "_download_then_execute_reason\|_ALLOWED_PIPELINE_HOSTS" tools/tirith_security.py
grep -n "cannot_reply_to_message"     plugins/platforms/slack/adapter.py
grep -n "_is_third_party_anthropic_endpoint" run_agent.py
```

Two traps this caught at the v0.19.0 jump:

- **Return-type drift.** Upstream changed `_generate_openai_tts` to return `output_path`
  where our patch returns the title. It merged clean; only reading both call sites showed
  the contract still held (the DeepInfra caller discards the value). **Whenever a patch
  changes what a function returns, re-check every caller after an update.**
- **Module-alias confusion.** `gateway.log` reports the Slack adapter as
  `hermes_plugins.slack_platform.adapter`, which does not match the patched path
  `plugins/platforms/slack/adapter.py` and looks alarmingly like a second copy. It isn't —
  the plugin loader assigns that name at runtime. Confirm with
  `find . -name adapter.py -path "*slack*"` returning exactly one file rather than trying
  to import the alias (it isn't importable standalone).

### Is a patch still needed — or now *dead code*?

Beyond "did upstream fix this" (below), check whether the patch is still **reachable**.
At v0.19.0 the `_resolve_thread_ts` synthetic-thread guard applied cleanly, looked
healthy, and had been unreachable for months: upstream's `if not reply_in_thread:` branch
returns before it. It was retired, not repaired. Read the *enclosing* control flow, not
just the hunk — and check the config value the branch keys off, rather than trusting a
doc's claim about it (CLAUDE.md asserted `reply_in_thread: true`; it had been `false`
since `1e753e9`, which inverted the whole analysis).

**"Dormant" is a legitimate third verdict** — distinct from both "needed" and "retire".
Two patches are unreachable under the *current* config but become load-bearing again if
the config moves back:

| Patch | Gate that makes it unreachable today |
|-|-|
| `run-agent-third-party-endpoint-token-refresh` | `self.api_mode != "anthropic_messages"` → returns before the patched line (live: `chat_completions`); `self.provider != "anthropic"` would too (live: `custom`) |
| `auxiliary-client-anthropic-mode-respect` | same `api_mode` branch is never entered |

Both were genuinely live until `0e17b0d` (2026-05-21) moved the brain off
`provider: anthropic` + the IU `/anthropic` base URL. Keep them, but say *dormant* in
CLAUDE.md — a present-tense "without this, every call 401s" reads as a live dependency
and stops the next reader from questioning it. To decide: read the guards **above** the
hunk, then check the live `config.yaml` value each one keys off.

Fastest way to settle "is this still load-bearing" for a scanner/validator patch is to
run it both ways in-process rather than reason about it — import the function from the
live tree and from a pristine worktree and feed it the same inputs:

```bash
PY=~/.hermes/hermes-agent/venv/bin/python3   # NOT ~/.hermes/venv — that path doesn't exist
for d in ~/.hermes/hermes-agent /tmp/hermes-verify; do (cd $d && $PY /tmp/scan_test.py $d); done
```

That is how the cron-scanner allowlist was confirmed at v0.19.0: identical inputs, argo
curls `OK` in the live tree and `Blocked` in pristine, while evil-host and mixed-fence
curls stayed `Blocked` in both.

**Renaming a patch file? Grep the code for its old name.** Patched hunks carry
`# LOCAL MODIFICATION (patches/<name>.patch)` headers pointing at their own source file.
The v0.19.0 rename left two of those stale inside `tirith_security.py`, aiming the next
reader at files that don't exist: `grep -rn "patches/" ~/.hermes/hermes-agent --include=*.py`
and reconcile against `ls ~/SourceRoot/hermes-agent/patches/`.

### Is this patch even still needed?

Before rewriting a failing patch, check whether upstream has since fixed the same underlying bug or shipped the same feature natively — rewriting a patch whose job upstream now does *better* just creates maintenance debt. Grep the new file for the symptom your patch works around (e.g. the buggy line your patch replaces, or a keyword from the bug description) and read what's there now. This happened at v0.18.2: `slack-audio-mime-ext.patch` mapped Slack audio MIME types to extensions to fix a `.ogg`-forced-on-MP4 bug — upstream had, independently, added its own `_resolve_slack_audio_ext()` helper doing the same job more thoroughly (filename-extension-first, then a mimetype map, `.m4a` fallback instead of `.ogg`, plus a bonus video-mislabeled-as-audio rerouter). The patch's target was fully superseded — retire it (delete from `patches/`, add a retirement note to `CLAUDE.md` like the existing ones), don't rewrite it. Conversely, if the check-fn/logic your patch depends on is gone with nothing to replace it, the patch is still needed — rewrite it against the new location/shape.

### Resolving 3-way conflict markers

Every conflict encountered so far (three, at the v0.18.2 jump) was **not** a logic disagreement — it was upstream adding its own independent feature or renaming a variable at the exact insertion point our patch also touches. The tell: `ours` (current file) and `theirs` (patch's target) both look reasonable in isolation, and neither is "wrong." Resolution pattern: **keep both additions, prefer the file's current identifier names over the patch's stale ones.**
- *Adjacent independent early-return* (`tools/tirith_security.py`): upstream added its own circuit-breaker early-return at the same spot our argo-pipeline bypass inserts. Fix: keep both `if` blocks, order doesn't matter since both just return early.
- *Renamed variable* (`gateway/platforms/base.py`): upstream renamed `_thread_metadata` → `_final_thread_metadata` (via a `_mark_notify_metadata()` wrap) at the same call sites our patch adds `reply_to=` to. Fix: grep the surrounding unconflicted code for which name is actually used elsewhere in the function — that's the one to keep — and combine it with the patch's added kwarg.
- *Added return value* (`tools/tts_tool.py`): upstream independently grew a 2-tuple return into a 3-tuple (`api_key, base_url, is_managed`) on a function our patch also touches (to add an `unquote` import). Fix: keep upstream's tuple shape (grep the function's current definition to confirm the real signature) *and* the patch's own addition — they're unrelated changes to the same lines, not alternatives.

After resolving, always sanity-check: `grep -rn "^<<<<<<<\|^=======$\|^>>>>>>>"` across the touched files (loosely — grep `======` alone also matches legitimate RST-style section underlines in docstrings/tests, so eyeball hits before assuming they're conflict markers) and `python3 -c "import ast; ast.parse(open('<file>').read())"` per file to catch syntax breaks before moving on.

### Regenerating patch files after resolving

Once every local mod is re-applied/hand-ported and the working tree is correct, regenerate the canonical `.patch` files instead of hand-diffing. `hermes update`'s stash-conflict-reset leaves `HEAD` in `~/.hermes/hermes-agent` sitting exactly on the clean, freshly-pulled upstream commit (confirm with `git log -1` and `git diff HEAD --stat` — the stat should list exactly the locally-modified files, nothing else):
```bash
cd ~/.hermes/hermes-agent
git diff HEAD -- <file> > /tmp/new-patches/<patch-name>.patch   # once per touched file
```
Before overwriting the canonical copies in `~/SourceRoot/hermes-agent/patches/`, verify each regenerated patch actually applies cleanly against that same baseline using a scratch worktree (cheap, disposable, doesn't touch the live checkout):
```bash
git worktree add /tmp/hermes-verify HEAD --detach
cd /tmp/hermes-verify && git apply --check /tmp/new-patches/<patch-name>.patch   # repeat per patch
cd .. && git -C ~/.hermes/hermes-agent worktree remove /tmp/hermes-verify --force
```
Only then `cp /tmp/new-patches/*.patch ~/SourceRoot/hermes-agent/patches/`, delete any retired patch file, and commit in `~/SourceRoot/hermes-agent` (this repo is direct-to-master).

### config.yaml loses hand-written comments on config-format migration

`hermes update` may print `Updating config format (vN → vM)…` — this re-serializes `config.yaml` through the live symlink and silently **strips comments**, even though it preserves all values. After the update, check `git diff config.yaml` in `~/SourceRoot/hermes-agent` — new default keys are expected and fine, but if any hand-written explanatory comment (the ones documenting *why*, e.g. the audio-gateway routing rationale or the skills-trust `external_dirs` note) got dropped, restore it manually before committing. This is not a patch-tracked file, so there's no `.patch` to re-apply here — just a manual comment restore each time the config version bumps.

### What `hermes update` does on its own

`hermes update` stashes your working changes, pulls upstream, then tries to re-apply the stash. Expect conflicts on the eight patched files — that is normal. The CLI prints the stash ref (`Restore your changes later with: git stash apply <sha>`); keep it as a fallback. After conflicts surface, the CLI resets the working tree clean — re-apply via the loop above.

**Lazy-backend refresh warnings are often benign.** After pulling, `hermes update` refreshes "lazy backends" (optional provider/platform plugins) and may print import warnings for some of them (e.g. `provider.vertex`, `platform.matrix`, `platform.feishu`, `platform.teams`, `tool.trace_upload` failed with a transient import error at the v0.18.2 jump). Before investigating, check whether the affected backend is actually active in `~/.hermes/config.yaml` (search for its provider/platform name under an *enabled* section, not just present as a stock default block — every platform gets a default config block whether used or not). If it's not part of this deployment (this repo only runs the Slack platform + OpenAI-provider TTS/STT via the audio-gateway), the warning is inert and doesn't block the update or the gateway.

### Docs-drift sweep (do this whenever an artifact is removed or renamed)

A structural change silently rots every doc and helper that referenced the old artifact,
and those only fail later, in the middle of an incident. When v0.19.0 retired
`~/.hermes/.env`, four places still read or rebuilt it — including a README recipe that
shells `op read`, which **hangs forever** on this headless mini. Sweep for the removed
name across docs *and* tooling, not just source:

```bash
cd ~/SourceRoot/hermes-agent
grep -rn "<removed-artifact>" --exclude-dir=.git --exclude-dir=patches . | grep -v '\.env\.tpl'
```

Check `README.md`, `CLAUDE.md`, `Makefile` (a `make status` check for a deleted file goes
permanently red), and **both** `.claude/skills/hermes-{update,validate}/SKILL.md`.
**Then actually run every recipe you rewrite** — a doc fix that was never executed is a
guess. Also re-read `make status` output after any change: a stale `✗` line trains you to
ignore the one that eventually matters.

### Environment gotchas on this box

- **The shell is zsh.** Bash associative arrays (`declare -A` + `${!arr[@]}`) fail with
  `bad substitution`. Use a paired `printf … | while IFS='|' read -r a b` loop.
- **`op` is not signed in** (headless mini). Any `op read`/`op run` hangs on the biometric
  prompt. Use `secrets-run` — same interface, age-encrypted offline cache.
- **`hermes gateway install` prints `Bootstrap failed: 5: Input/output error`** several
  times and still succeeds. Trust `hermes gateway status`, not that output.
- **Sessions for API-server requests aren't written to `~/.hermes/sessions/`**, and the
  terminal tool's *command text* is never logged — only `tool terminal completed`. Don't
  plan a verification that depends on recovering the executed command; test the guard
  function directly instead.

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

SOUL.md / config.yaml changes need a gateway restart (skills are symlinked, so SKILL.md edits are already live).

```bash
hermes gateway restart
```

> **launchd supervision works as of v0.19.0.** Earlier revisions of this skill said
> launchd couldn't bootstrap `ai.hermes.gateway` and that restarts fell back to a bare
> `run --replace`. `hermes gateway status` now reports `✓ Gateway is supervised by
> launchd (PID …)`, so auto-start at login and auto-restart on crash are live.
> `hermes gateway install` still prints `Bootstrap failed: 5: Input/output error`
> several times while repairing the definition — **that message is noise**; it finishes
> with `✓ Service definition updated` and `gateway status` shows the true state. Still
> do **not** `launchctl load` a `.plist` by hand.

Verify it came up:

```bash
curl -s "http://$(secrets-run read op://hermes/gateway/host):8642/health"
tail -20 ~/.hermes/logs/gateway.log
```

## Verify

**Touching `tools/tirith_security.py` needs a gateway restart** — the module is imported
once at startup, so an edited guard is inert in the running process no matter what a
direct in-process test says. Test the function standalone first, restart second, then
re-run the live checks below.

**Security rules get a regression suite, not a spot-check.** The download-then-execute
guard passed a hand-written check at v0.19.0 and an adversarial audit one day later found
**11 bypasses** in it, including a shape CLAUDE.md's own table claimed was blocked. What
a suite has to cover, in this order:

1. **Attack shapes** — every spelling of the thing you're blocking. The misses clustered
   in *tokenisation*, not logic: newline separators, glued `>/tmp/f`, a flag whose value
   is the next token (`-qO /tmp/f`), `//tmp//f` vs `/tmp/f` (`os.path.normpath` keeps a
   leading `//`), and `exec`-style prefixes.
2. **Legitimate shapes** — pull real commands from the skills Hermes actually uses
   (argo-api, karakeep, research-gateway, capture, obsidian, reading). A false positive
   here is a Slack approval gate on every routine call, which is worse than the gap.
3. **Fuzz** — a few thousand random token soups asserting only "never raises". These
   helpers run before tirith on *every* command; an exception is an outage.
4. **The premise itself** — confirm the gap is really upstream's before patching around
   it: `~/.hermes/bin/tirith check --json --non-interactive --shell posix -- '<cmd>'`.

The suite lives at `tests/test_download_guard.py` — run it after every update that
touches `tirith_security.py`, before restarting the gateway:

```bash
~/.hermes/hermes-agent/venv/bin/python3 tests/test_download_guard.py
```

It also asserts the documented gaps are *still* gaps, so a change that happens to close
one gets flagged instead of silently drifting from CLAUDE.md. Keep the verdict counts in
CLAUDE.md in sync; a stale "tested against N shapes" is how a false claim survives.

A basic "send a message and see a reply" check doesn't exercise most of the patched code paths — they only fire under specific conditions (a real Slack round-trip, a TTS request, an argo curl). After any update, run through these; each targets a specific patch. Use the `hermes-validate` skill's gateway-API (method A) and Slack-API (method B) send recipes to drive them, and confirm results by reading `~/.hermes/logs/agent.log` / `gateway.log` for the relevant timestamp (not just eyeballing the Slack reply) — that's what actually proves which code path ran.

| Check | Drives | Confirms | What to look for |
|-|-|-|-|
| General question (method A, e.g. "what's on my TickTick") | Core agent loop, unaffected by any patch | Update didn't break routing/skills at all | Clean 200 response, `Turn ended: reason=text_response` in `agent.log` |
| Infra/argo question that triggers a `curl \| jq`/`python3` pipe (method A, e.g. "infra status") | `tirith-argo-allowlist-and-download-guard.patch` | Argo pipelines still bypass tirith | `tool terminal completed` in `agent.log`, **zero** hits for `grep -i "approval\|blocked" gateway.log` around that timestamp — a hit means the patch didn't re-apply |
| Any request routed through real Slack (method B — HomeLab synthetic sender), containing a raw `*` list marker in the model's likely output | `format_message()` pre-steps in `plugins/platforms/slack/adapter.py` | mrkdwn normalization ported to the new adapter path | Fetch the posted message (`GET /api/slack/channels/:id/messages` via argo) — bullets render as `-`, not `*` |
| "Say/speak X out loud" (method B) | `tts-tool-audio-title.patch` + `slack-media-inline-reply-anchor.patch` (base.py) | Title-naming works; media threads with its text reply | `agent.log` line `tools.tts_tool: TTS audio saved: .../<Human Title>.mp3` (not `tts_<timestamp>.mp3`); no errors after `[Slack] Sending response`; since v0.19.0 (`reply_in_thread: true`) the audio and the text reply share the **same `thread_ts`** — they must not land in different places |
| A German-language message (method B) | Config only (`tts.openai.model` = Gemini TTS), not a patch | Charon still pronounces German natively, no translation | Manual listen — text-based checks above can't verify pronunciation |

**Prefer a direct in-process test over a round-trip where one exists.** The table's Slack/TTS rows depend on a real Slack round-trip whose command text is *not* logged, so they prove less than they look like they do. Calling the patched function directly is faster, deterministic, and actually pins the behavior — this is what caught the v0.19.0 `_generate_openai_tts` return-type change. Run these from `~/.hermes/hermes-agent` with `venv/bin/python`:

```python
# tts-tool-audio-title: real call to the audio-gateway, asserts the header + rename
from tools.tts_tool import _generate_openai_tts, _rename_with_title
title = _generate_openai_tts("Kurzer Test.", "/tmp/tts_123.mp3", yaml_cfg["tts"])
assert title, "X-Audio-Title header missing — patch not applied or gateway changed"
_rename_with_title("/tmp/tts_123.mp3", title)   # → '/tmp/Kurzer Test.mp3'

# tirith patch: assert BOTH directions in one shot
from tools.tirith_security import check_command_security as chk
assert chk('curl -s https://argo.jkrumm.com/x | jq .')["action"] == "allow"
assert chk('curl -s https://argo.jkrumm.com/x | sh')["action"] == "block"   # must NOT be allowlisted
```

The second tirith assertion is the important one — it proves the allowlist didn't over-broaden into letting argo content pipe to a shell. (Note: `curl … > /tmp/f && sh /tmp/f` is allowed for *any* host — that's a pre-existing gap in upstream tirith, not something our patch introduced.)

**Secrets check (v0.19.0+):** `hermes gateway status` must print `Command helper: applied 26 secrets`. Missing → the gateway is running credential-less; test the helper directly with `secrets-run export --env-file=~/.hermes/.env.tpl | sed 's/^export //' | wc -l`.

Config sanity check (not patch-related, but always confirm after an update): `config.yaml`'s `tts.openai.base_url` / `stt.openai.base_url` still read `https://audio-gateway.jkrumm.com/v1`.
