# Terminal-command guards (tirith patch) — the four rules, limits, tests

The other nine patches, and every retirement, are in **`patches.md`**. This file
keeps the rules, the limits and the regression-suite names — the operational
surface a session needs — with each incident that forced a rule condensed to
one paragraph rather than a full narrative.

All four rules live in `tools/tirith_security.py`, source
`patches/tirith-hermes-guards.patch`. Re-apply:
`cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/tirith-hermes-guards.patch`.
**Edits need a gateway restart** — the module is imported once at startup, so a
green in-process test says nothing about the running process.

## 1. Trusted-pipeline allowlist

Early-return `allow` in `check_command_security` when the command is a
trusted-personal-API pipeline: every URL on `argo.jkrumm.com`,
`karakeep.jkrumm.com`, `research.jkrumm.com`, `hyperdx.jkrumm.com` or
`audio-gateway.jkrumm.com`, piped only through a small safe-program set (curl,
jq, python3, head, tail, tee, tr, cat, wc, cut, grep, sort, awk, sed, uniq,
xargs) with no shell escape hatch. Any redirect, `$(...)`, backtick, `;`, `&&`,
`||`, `&`, `(`, `>` defers to tirith.

Without this, tirith's `[HIGH] Pipe to interpreter` rule fires on every
`curl https://argo.jkrumm.com/... | python3 ...` the LLM produces — a Slack
approval gate on completely safe argo calls that pipe JSON to python3 for
formatting. The threat tirith protects against ("downloaded content executed
without inspection") doesn't apply: these hosts are bearer-authenticated and
serve JSON parsed as data, not executable code. **v0.18.2 nuance:** upstream
independently added its own circuit-breaker early-return (`_circuit_open`,
after `_CRASH_LIMIT` consecutive tirith failures) at the same insertion point;
both are independent early-return gates, order doesn't affect correctness.

## 2. `download_then_execute` block

tirith blocks `curl URL | sh` (`curl_pipe_shell`, MITRE T1059.004) but **not**
the trivially equivalent two-step form (`curl -o /tmp/f … && sh /tmp/f`,
`wget -qO`, `chmod +x`, `$(cat …)`, `<(curl …)`) — verified directly against the
tirith binary, so this is upstream's ruleset gap, not a local regression.
`_download_then_execute_reason()` rejects the shape before tirith is consulted,
placed **before** both the circuit breaker and the allowlist so it holds when
tirith is unavailable (`tirith_fail_open` defaults **True**) and can't be
bypassed via an allowlisted host. It's a `block`, not a `warn` — this agent has
no legitimate reason to fetch a file and execute it. Fires on a downloader's
write later executed, sourced, `chmod +x`'d, fed to an interpreter on stdin, or
expanded via `$(cat …)`; on an inline `$(curl …)`/`<(curl …)`; or a downloaded
file reaching a bare interpreter through a pipe. Write-detection is
per-program (`curl -o`/`-O`, `wget -O`/no-flag, glued and split forms,
`--output=`, `>`/`>>`), taint follows one `cp`/`mv`/`install` hop.

**Known limits — deliberate; this raises the cost of the shape, it does not
eliminate the class.** Not caught: cross-call (download in one terminal call,
execute in the next); value indirection where the written and executed
spellings differ (`F=/tmp/f; curl -o $F URL; sh /tmp/f`); `xargs`-mediated
execution where the path arrives on stdin; arbitrary decode/transformer chains
beyond the single `| sh` stdin case. Not reported upstream to tirith yet.

Regression suite: **`tests/test_download_guard.py`** — 20/20 attack shapes
blocked, 27/27 real Hermes commands allowed, plus 2/2 newline-smuggled bypasses
blocked and 1/1 quoted newline still allowed, 4000-input fuzz clean.

## 3. `raw_agent_invocation`

Blocks Hermes composing its own `claude`/`claude_iu`/`claude_bridge`/`ca`/
`opencode`/`rd bg|work`/`agent-dispatch`/`remote-dev.sh bg|work` call —
every spelling that places a **headless, invisible** session. `rd repos|agents|
read` stay allowed.

**`herdr` is not guarded at all since 2026-09-12** — every verb, `agent
start|prompt|send-keys|attach` and `pane run|send-text|send-keys` included. It
used to be blocked as session placement one hop up, and that bound produced the
exact failure it was meant to prevent: asked in Slack to "open a herdr pane in
warden with `cf`", Hermes was refused, silently substituted a Warden dispatch,
and reported success for work Johannes had not asked for. A herdr pane is **his
own visible workspace** — opened on an explicit request, rendered in the TUI he
is watching, readable and killable by him. The invisible lane is what this rule
still closes. Unattended background work belonging to Warden is now carried by
instruction (SOUL.md, the `herdr` and `claude-dispatch` skills), because on a
lane he is looking at, his eyes are the bound.

Why it exists: handed the `claude-dispatch` skill on 2026-08-02, Hermes read it,
understood the task, and then composed its own prompt and ran `claude -p`
directly from the terminal tool instead of going through `hermes-cc.sh` —
bypassing the tier ceiling, the daily budget, the audit log and the dispatch
record the whole return path is built on. Instruction had already said not to;
instruction is not a bound, so the block moved into tirith. Handles wrapper
programs (`timeout`, `env`, `nohup`, `sudo`, `xargs`, `nice`), env-assignment
prefixes (`K=$(...)`), `sh -c` inline scripts, and subshells.

Regression suite: **`tests/test_raw_agent_guard.py`** — 36/36 attack shapes
blocked, 51/51 real commands allowed, plus 5/5 wrapper-operand bypasses blocked
and 5/5 value-less wrapper flags still blocked, 4000-input fuzz clean.

## 4. `raw_repo_write`

Blocks Hermes editing a repo itself instead of dispatching. `_repo_write_reason()`
is **unconditional, not path-scoped** — `git commit -m x` names no path, the
repo comes from the terminal tool's working directory (invisible to a command
scanner), so a path-scoped rule is evaded by `cd`. It is a **denylist of git
write verbs** (commit, push, merge, rebase, reset, checkout, add, tag, clone,
`config`, …) — every inspection verb (`log`, `status`, `diff`, `show`, `blame`,
`rev-parse`, `for-each-ref`, `fetch`) still works untouched. Also blocked: `gh`
subcommands that change code or its delivery (`pr create/merge/ready`,
`release`, `repo create/delete/edit`, `workflow run`, `secret set`, a mutating
`gh api`) and the same shapes by hand against `api.github.com`.

Why it exists: the `raw_agent_invocation` rule stops Hermes composing its own
`claude -p`; it does not stop Hermes skipping the episode and editing the repo
itself — which happened in the same session that built the `merge` verb.
Asked to fix a README, Hermes read the repo, said "I'll put the fix on master
directly," edited the file, committed, hit a push rejection, rebased and
pushed — nine turns, no `hermes-cc.sh`, no audit line, landed on `origin/master`.

**Two exemptions, both load-bearing, both tested.** (1) **Issues are not repo
writes** — `gh issue create` and the `/issues` API path are exempt; an issue
changes nothing that runs. (2) **The brain vault**, `~/SourceRoot/brain`: the
`obsidian` skill requires a commit for durability, and the vault's only
dispatch tier is `investigate` (read-only, capped, not denied), so the guard's
premise — "there is a bounded write path instead" — is false there. The
exemption is narrow: the command must **name** the vault (`git -C
~/SourceRoot/brain …`, or a `cd` to it on the same command line). A bare
`git commit` stays blocked. An explicit `-C` outside the vault always beats an
earlier `cd` into it.

Regression suite: **`tests/test_repo_write_guard.py`** — 71/71 attack shapes
blocked, 55/55 real commands allowed, plus 5/5 wrapper-operand bypasses
blocked, 3/3 no-false-positive, 7/7 vault-path units, 2/2 lookalike-vault e2e
blocked, 2/2 genuine vault e2e allowed, 3/3 still blocked with
`tirith_enabled: false`, 4000-input fuzz clean. **Known limits:** cross-call
`cd` (fails closed — the commit is refused, so the cost is naming the vault,
not a bypass); editing files without git (not durable, not outward-facing, and
`git status` shows it); value indirection (`G=git; $G push`).

## The newline bypass, and the transferable lesson

A shared tokenizer helper (`_agent_segments`, used by rules 3 and 4) ran
`shlex` with `whitespace_split=True`, whose whitespace set includes `\n` — so a
multi-line command block welded into one argv and nothing past line 1 was ever
scanned. `cd /repo && git push` was blocked; the same thing with a newline
instead of `&&` was not, and it was exploited twice: once directly (a
Tailscale ACL edit landed on `origin/master` with no block, no audit line), and
again as `_is_argo_only_pipeline`'s own separate tokenizer, which let a
trusted-host curl followed by a newline and a hostile `curl | sh` slip past the
allowlist entirely. Fix: `\n`/`\r` moved out of `lex.whitespace` into
`punctuation_chars`, splitting outside quotes only — `sh -c "…"` recursion and
multi-line commit messages are untouched. **A shared helper needs shared
tests**: three guards, one splitter, and only the suite whose author had
already been bitten covered the case — grep every `shlex.shlex(` call in the
file before trusting a tokenizer fix is complete. Two more defects surfaced in
the same audit pass, found by review rather than by anything failing:
`_is_vault_path` matched the brain-vault exemption by `endswith(...)` (so a
path merely ending in the right suffix was exempt), the block-checks sat below
the `tirith_enabled` early return (so disabling tirith in config disabled the
hardening meant to survive exactly that), and `_strip_agent_wrappers` skipped a
wrapper's flags but not their operands (so `env -u FOO git commit` resolved the
program to `FOO`). All fixed; all three suites now assert against the shape
that caused each.
