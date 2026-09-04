# Dispatch bridge — the decisions behind each bound

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Dispatch Bridge points here — nothing was rewritten, only relocated.

Hermes observes well and reads repos badly: gpt-5.6-luna with a `terminal` tool cannot
use a repo's `CLAUDE.md`, `.claude/rules/` or `.claude/skills/`, and that context is exactly
what triage needs. `scripts/hermes-cc.sh` is the bounded client that hands the episode to
Claude Code instead — the same closed-verb-set shape as `hermes-ops.sh`, for the same reason.
Design: `docs/dispatch-bridge.md`. The episode itself is sideclaw's `dispatch` job tool.

- **Verbs:** `dispatch <repo>` · `status <job-id>` · `list [open|today|all]` · `merge <job-id>` · `cancel <job-id>`.
  `cancel` abandons the LOCAL record only — sideclaw has no cancel endpoint, and the help text
  and skill both say so rather than implying the episode stopped.
- **No verb takes a path, a command or a URL.** A dispatch names a *repo* — a bare name,
  which the script resolves under the single `root` in `config/dispatch-repos.json`.
  `dotfiles-private`, `homelab-private` and `brain` are in that file's `deny` list and stay
  there. **The enumeration this replaced (2026-08-02) is the lesson:** it was a per-repo
  inventory where absence meant denial, and it rotted — 22 repos listed against 30 on disk,
  three of them (`king-smith-walkingpad-mac`, `linewatch`, `vibe-stack`) unreachable since
  they were cloned, with no way to tell a stale omission from a deliberate one. Discovery
  under a confined root plus an explicit `deny` keeps the denials meaningful and stops the
  file needing an edit per clone. What did **not** change is the property that matters: a
  path never crosses the interface. Composing one from caller input is a step the old map
  lookup never took, so `resolve_repo` carries the weight now — the name must be a single
  segment (`.`, `..` and dotted names refused, which the old `[A-Za-z0-9_.-]` class admitted
  harmlessly as dict keys and would not have as path components), and the resolved
  checkout's parent must **be** the resolved root, so a symlink planted in the root cannot
  point out of it. Both are regression-tested.
- **The brief is data, never argv.** Read from stdin (quoted heredoc) or `--brief-file`.
  There is deliberately no `--brief`: as an argv element the brief would be composed into a
  shell line and expanded *before* the script ran, so a `$(...)` in a Slack message would
  execute. The skill teaches the `<<'BRIEF'` form.
- **All three tiers are built** (Phase 4). `investigate` read-only → verdict; `author`
  read-only → verdict + one filed GitHub issue; `implement` → a `dispatch/…` branch and a
  **draft** PR. **Every tier runs in its own throwaway worktree**, not just `implement` — a
  read tier's `readOnly: true` removes Edit and Write but not `Bash`, and the brief carries
  attacker-influenced text, so a read episode in the live checkout was one injected `sed -i`
  away from editing a repo that deploys on push. It costs no capability; the read tiers get a
  copy of HEAD needing no identity and no network (`docs/dispatch-bridge.md` § "The read
  tiers get a worktree too"). A tier above a repo's ceiling is refused (exit 4),
  never downgraded. `config/dispatch-repos.json` sets those ceilings and states its own
  rationale: `defaultTier` is **`implement`**, with a single `investigate` floor for
  `dotfiles`/`vps`/`homelab`, the machine's own control plane. **There is no `implement`
  allowlist** — there was one for about a day (`hermes-agent`, `sideclaw`, `usage-tracker`,
  the scratch target) and it went the same way the repo inventory did (owner decision,
  2026-08-02): a list that must be edited before the tool can do its job is a list that
  will be stale exactly when it is needed. The point of the bridge is a system that heals
  itself, and a default that stops short of proposing the fix makes it a system that files
  tickets.
  **So an unattended episode can file a world-readable issue, or open a draft PR, on a
  public repo with no human gate.** Also an owner decision. What bounds `implement` is the
  shape of the tier rather than this file — isolated worktree, `dispatch/…` branch, draft
  PR, `--why` **and** `--confirm` — and nothing reaches a default branch without the
  separate `merge` verb. Worst unattended outcome is a draft PR nobody wanted, which costs
  one click. The handler-side secret scan still *refuses* — never redacts — a brief carrying
  credentials, and the skill instructs the agent to summarize rather than quote. It now also
  covers the **diff's added lines**, so an episode cannot inline a credential into the branch
  it pushes; that check is the handler's and deliberately not the repo's `pre-commit` hook,
  since the episode may be running in a repo whose hook it just wrote.
- **`implement` needs `--why` AND `--confirm`.** Without `--confirm` the verb prints its
  exact plan — including a `wouldNeverDo` list — and exits **0** having changed nothing.
  Exit 0 because printing the plan *is* the successful outcome of that request; a non-zero
  code would read as "the dispatch failed" to whatever parses it. `--why` is separate and
  mandatory: it is the audit record of why an unattended episode was allowed to write.
- **`--confirm` became an artifact instead of an instruction (2026-08-03).** It was a flag
  on the same invocation, set by the same agent it constrains — the script's header said
  so plainly, and called the fix "an approval artifact minted outside the agent and bound
  to the repo + brief hash". That is now built. The plan branch posts **Approve / Deny
  buttons** into the origin channel; the click lands in the gateway process, which signs
  it with an **Ed25519 key minted at startup and held in RAM only** (`plugins/dispatch-approval/`,
  public half at `~/.hermes/dispatch-approval.pub`). `--confirm` refuses (exit 4) without
  a valid signature. **The point is not "who clicked" — it is that a click is not text.**
  All Slack senders here are trusted (owner decision, below); the residual risk is hostile
  *content* relayed by a trusted one, and injected prose cannot mint a signature or cause
  a Slack interaction payload to exist. Every column of `dispatch_approvals` is writable
  by this uid, the agent's included, so **only the signature is consulted** — the forged-row
  case is the centre of `tests/test_dispatch_approval.py`. It does not defend against a
  wholly-compromised Hermes with a debugger on the gateway; that was never the claim.
  Bound to `verb|repo|tier|payload|why` — so editing the brief, or swapping the stated
  reason the button showed, voids it — plus single-use and a 30-minute TTL. **Fails closed
  everywhere**: no plugin, no key, no gateway, expired, spent, or hash mismatch all refuse.
  A gateway restart mints a new key and so voids pending approvals, deliberately.
  **Only the gateway may publish the public key, and this is the one thing that has
  already broken.** `register()` runs in every process that discovers plugins — a CLI
  call, a cron subprocess — and the first build published unconditionally, so a
  non-gateway process overwrote the file with a key nothing would ever sign with. The
  symptom is maximally confusing: the click works, the row carries a valid signature,
  and `--confirm` still refuses as *"has not been clicked yet"*. Two properties close
  it, both tested: publish only when argv says `gateway run`, and republish on the way
  to signing whenever the file on disk is not ours (a process handling a click **is**
  the gateway, whatever its argv looks like). If a merge or dispatch ever refuses
  despite a visible Approve in Slack, check `grep 'published public key'` against
  `Wired 2 plugin action handler` in `~/.hermes/logs/agent.log` — a publish with no
  matching wire line is this bug.
  Enable once with `hermes plugins enable dispatch-approval`; `make setup` symlinks it
  (`HERMES_PLUGINS`), and it must live in this repo for the same durability reason skills do.
- **Structural ceilings, because `--max-budget-usd` is API-only and does not cap a Max
  session:** 20 dispatches per UTC day counted from the `dispatches` table, of which at
  most 5 may be `implement` (its own ceiling — a 30-minute writing episode and a 90-second
  read are not the same spend, and one bad day of triage must not consume the allowance for
  real changes), a 240s in-turn `--wait` cap, sideclaw's own turn/timeout/concurrency limits.
  **Both counts are reported by every path that reports anything** — dispatch, the
  `--dry-run` plan, `status`, `list` — as a `budget` object, plus a `budget.warning` naming
  the env var once a ceiling is close. The first build computed them only inside the refusal
  path, so `implementToday` never appeared in a successful response and the sole signal was
  an exit 4 that said nothing about how to proceed; a bound nobody can see approaching reads
  as the tool breaking, not as a budget. Counts are re-read *after* the row is inserted, so a
  caller's number includes its own dispatch rather than trailing the one the next refusal
  will use. Raising a ceiling is Johannes's call: the refusals and warnings name
  `HERMES_CC_DAILY_BUDGET` / `HERMES_CC_IMPLEMENT_BUDGET`, and `claude-dispatch`'s SKILL.md
  forbids the agent composing an invocation that sets either.
- **Audit log:** `~/Library/Logs/hermes-cc.log`, one line per invocation including refusals.
  Four modes, and the distinctions are load-bearing: `opened` (an episode actually ran),
  `planned` (a gated tier stopped to wait for a human), `dry-run` (the caller asked for a
  rehearsal), `refused` (a guard said no). A refusal that logged as `opened` would hide the
  guard doing its job, and a `planned` that logged as `refused` would make the `--confirm`
  gate unverifiable after the fact. **Register it in `dotfiles/scripts/log-rotate.sh`'s
  `FILES` array** — that list is declared, never globbed, so an unregistered log is an
  unbounded one.
- **`dispatches` table** in `~/.hermes/watchdog.db` (additive DDL; `events` is untouched).
  `reported_at` is the delivery contract: NULL means the sweeper still owes a message.
  A `--wait` that returns a terminal verdict stamps it, because handing the verdict to a live
  turn *is* the delivery; `status` deliberately does not, since a poll tells nobody.
  `artifact_url` is denormalized out of the verdict into its own column by **both** settlers
  (`hermes-cc.sh`'s `sync_record` and `dispatch-sweep.py`) — whichever one closes a given
  dispatch has to leave the row in the same shape, and the briefing/watchdog projections want
  a column read, not a JSON parse.
- **`merge` is deliberately NOT gated on the signed approval.** It was, for about an
  hour on 2026-08-03, on the argument that the implement approval covers the *change*
  and not the *diff* — which did not exist yet when it was approved. Reverted the same
  day (owner decision): a second click per PR trains the rubber stamp this file already
  warned about, and it buys little against the bounds the verb already carries — job-id
  lookup rather than a PR number, every implement-time check re-run against the current
  head, a pinned head SHA on the merge call itself, and its own 3/day ceiling. Gating
  `dispatch` is what earns its keep, because that is where an unattended episode starts
  writing from a brief that may trace to third-party text.
- **`merge <job-id>` lands the draft PR, with no human on GitHub (owner decision, 2026-08-02).**
  It inverts a statement sideclaw's `openPullRequest` makes in a comment — "un-drafting is not
  something the episode can do for itself" — so the bounds carry the weight the human used to.
  It takes a **job id, never a PR number or URL**: the pull request is looked up from the
  `dispatches` row, so no shape of caller input can name an arbitrary PR — the same property
  the repo argument has. Eligibility is **derived, not listed**: a repo in
  `dotfiles/config/pr-required-repos.json` (the file the branch-protection hook and
  `github-config.sh` already share) can never be auto-merged, so there is no second list to
  drift. Every bound the episode was held to is re-checked against the **current** head — base
  is the default branch, head is a `dispatch/…` branch in this same repo and never a fork, no
  `.github/workflows|actions` path, sideclaw's 40-file/2000-line ceilings intact,
  `mergeable_state` exactly `clean` (`blocked` and `unstable` are refusals, not judgement
  calls) — and the merge call **pins the head SHA**, so a push landing between inspection and
  merge fails the merge rather than riding it. Own ceiling: 3/day
  (`HERMES_CC_MERGE_BUDGET`), tighter than implement's 5, because not everything written
  should land. Audit mode is **`merged`**, deliberately not folded into `opened` — grepping
  the log for what actually reached a default branch is the reason the log exists. The GitHub
  credential goes in as a curl config on **stdin**, never argv: this machine runs triage that
  reads `ps` output (`skills/homelab-ops/references/launchd-restart-triage.md`), so a token in
  the process table is a real leak path, and a test asserts it never appears there.
- **A bot sender can drive this whole chain, and that is the design (owner decision,
  2026-08-02) — do not "fix" it.** `slack.allow_bots: all` means anything that can post in
  the workspace can reach an agent that can now merge to a default branch. That was raised
  as a hole and rejected: HomeLab, VPS and Argo all post from inside the tailnet, they are
  Johannes's own infra, and gating them is precisely what would break the self-healing
  premise the bridge exists to serve. A per-channel bot policy was designed and not built.
  **The trust boundary here is the workspace, not the human/bot distinction.**
  Two things worth keeping straight if this comes up again. First, `allow_bots` is
  load-bearing for a reason that is easy to get wrong: the watchdog reads `#alerts` over
  the **argo API**, not Slack ingest, so it does not depend on this at all — what does is
  live auto-triage, Hermes ingesting a UptimeKuma alert in `#alerts` and answering it
  (verified 2026-08-02 21:01: `user=unknown chat=C0AS1LAUQ3C msg='[MacMini Dev Host - Push]
  [:red_circle: Down] …'` → a 1034-char reply). Setting `allow_bots: none` would kill that.
  Second, the real exposure is not a hostile *sender* but hostile *content* relayed by a
  trusted one — a stranger's GitHub issue title arriving through Johannes's own bot. That
  is why `watchdog-poll.py` and `briefing-coverage.py` mark non-`jkrumm` GitHub items as
  third-party rather than trying to authenticate the messenger.
- **Tests:** `tests/test_hermes_cc.py` (130 cases, stubbed job server and stubbed GitHub —
  never a real one of either), `tests/test_dispatch_approval.py` (21 checks on the signed
  gate; its centre is the **forged-row** case — an `approve` row written the way a
  compromised agent would write it must still refuse — plus wrong-key, expired, spent,
  brief-edited and why-edited), `tests/test_raw_agent_guard.py` and
  `tests/test_repo_write_guard.py` (the guard that makes the bridge non-optional). Run with `~/.hermes/hermes-agent/venv/bin/python3`.
  Note `test_hermes_cc.py`'s harness now walks the real plan→sign→confirm flow for any
  `--confirm` case (`Harness.run(auto_approve=...)`) rather than duplicating the payload
  hash — the gate is not what that file tests, but it is in the way of everything it does.
  **The other half of the bridge is tested in sideclaw**, which had no suite at all until
  2026-08-03: `sideclaw/tests/` (`bun test`, 175 cases) covers the bounds this side cannot
  reach — worktree isolation and its post-crash sweep, the diff-refusal ladder, the added-lines
  secret scan, `pushBranch`'s four refusals against a local bare `origin` rather than a mock,
  the nonce fence around the untrusted brief, the salvage discrimination, and the worker's CLI
  flag vector. It is mutation-verified; `sideclaw/CLAUDE.md` § "Tests" says how and why.
  **Also fixed there on 2026-08-03: a dispatched repo could execute code in its own episode**
  — a `.claude/settings.json` in the target repo ran hooks (before the model's first turn, and
  on every Bash call) and its `env` block overrode the handler's environment, `GIT_DENY_CREDENTIALS_ENV`
  included. Both closed in sideclaw; `docs/dispatch-bridge.md` § "Verified live" records the
  end-to-end proof against a hostile fixture.

> **The GitHub credential is `op://mini/github/token`, and it needs three permissions.**
> `Contents: write` (the branch push, via the git credential helper) **plus** `Issues: write`
> and `Pull requests: write` (the artifact, via the API). Those are separate grants on a
> fine-grained PAT, and a token holding only the first pushes the branch successfully and
> then fails at the very last step — GitHub's own message for that is "Resource not
> accessible by personal access token", which names neither the permission nor the token.
> `describeGithubFailure` in sideclaw's `dispatch-git.ts` rewrites it to name both.
> There is a `GITHUB_TOKEN` fallback in sideclaw's `.env`, but it is a `gho_` OAuth token —
> the same class retired from the git credential path on 2026-07-26 for expiring silently —
> so the op:// ref is deliberately tried **first** and the fallback must not quietly become
> the real dependency.

