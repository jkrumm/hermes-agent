# Dispatch Bridge — Hermes's own side

The dispatch bridge itself (tiers, the sideclaw `dispatch` job tool, the
worktree isolation, the `merge` verb, the ledger schema, repo policy) moved
to `~/SourceRoot/warden` on 2026-09-10 — see its `DESIGN.md` (authoritative
design), `CLAUDE.md` (developer notes) and `FLOWS.md` (six end-to-end
scenarios). `scripts/hermes-cc.sh` in this repo (= `~/.hermes/scripts/hermes-cc.sh`)
is now a 6-line exec shim into `warden/scripts/warden`, kept only because the
Hermes-side guards (`tests/test_raw_agent_guard.py`,
`tests/test_repo_write_guard.py`) key on that exact path.

What genuinely stays Hermes-side is the door a Slack turn opens through, and
the artifact that makes an `implement` click mean something.

## The door: a Slack turn opens a dispatch

Hermes reads its world through **argo** and decides whether a dispatch is
worth opening (`skills/claude-dispatch/SKILL.md` carries the tier judgment
and the hard rule that infra mutation is `homelab-ops`, never this). Opening
one shells into `warden` via `scripts/hermes-cc.sh`; everything after that —
the record, the episode, the verdict — is warden's.

**Return path.** A dispatch reports where it was born: a Slack-thread origin
gets progress and verdict posted back into that thread; a watchdog-event
origin lets the digest report outcome instead of re-reminding. For anything
longer than an `investigate` (~3 min), warden's 5-min sweeper posts the
verdict into `origin_thread_ts` — and that post lands as Hermes's own bot
token, which `plugins/platforms/slack/adapter.py` drops on ingest to prevent
echo loops (keyed on the sender's user id). So a sweeper-delivered verdict is
visible to the human but invisible to the session. The compensation lives in
the skill: when a thread references a dispatch, Hermes re-reads it with
`warden status <job-id>` rather than trusting thread history — the dispatch
record is the durable copy, the Slack message only a notification.

**`slack.allow_bots: all` is deliberate — do not "fix" it (owner decision,
2026-08-02).** HomeLab, VPS and Argo all post from inside the tailnet, they
are Johannes's own infra, and gating them would break the self-healing
premise the bridge exists to serve — `allow_bots` is load-bearing for Hermes
ingesting an UptimeKuma alert in `#alerts` and dispatching on it. The trust
boundary is the workspace, not the human/bot distinction; the real exposure
is hostile *content* relayed by a trusted sender, which is why
`briefing-coverage.py` marks non-`jkrumm` GitHub items as third-party rather
than authenticating the messenger.

## The signed approval artifact (`plugins/dispatch-approval/`)

`implement` needs a Slack-signed approval, and the signature is minted here,
not in warden. A flag on the same invocation, set by the same agent it
constrains, is not a bound — `dispatch` carries no `--confirm` at all. The
plan branch posts **Approve/Deny buttons** into the origin channel; the
click lands in the gateway, which signs it with an **Ed25519 key minted at
startup, held in RAM only** (public half at `~/.hermes/dispatch-approval.pub`).
`_record_decision()` spools the signed decision as an `approval_decision`
intent and drains it **synchronously** through `warden/scripts/intents.py`,
whose `drain()` calls `lifecycle/approvals.py`'s `execute_approved()` — the
same verifier, the same budget/policy re-check, the same in-flight lock —
the moment the decision lands, so the episode is already opening (or already
refused) by the time the click handler's own call returns. This plugin's own
`execute_approved()` then only reads the row back (`spent_job_id` /
`spend_error`) and posts the outcome — it runs nothing itself. The point is
not "who clicked" — it is that a click is not text: injected prose cannot
mint a signature or cause a Slack interaction payload to exist.

Bound to `verb|repo|tier|brief|why|context`, single-use, 30-min TTL, **fails
closed** on no plugin / no key / no gateway / expired / spent / hash
mismatch; a gateway restart voids pending approvals.

**The one bug this has had:** `register()` runs in every process that
discovers plugins — a CLI call, a cron subprocess — and the first build
published the public key unconditionally, so a non-gateway process could
overwrite it with a key nothing would ever sign with. Symptom: a visible
Approve click, a validly signed row, and the CLI still refusing as *"has not
been clicked yet"*. Two properties close it: publish only when argv says
`gateway run`, and republish on the way to signing whenever the file on disk
is not ours. Tell: `grep 'published public key'` vs `Wired 2 plugin action
handler` in `~/.hermes/logs/agent.log` — a publish with no matching wire line
means a non-gateway process overwrote the key. Enable once with `hermes
plugins enable dispatch-approval`.

**`merge` is deliberately NOT gated on this approval** — see warden's
`DESIGN.md` for why (the implement approval covers the change, not the
diff, and a second click per PR trains the rubber stamp this design already
warns about).

## Tests (this repo)

`tests/test_raw_agent_guard.py` (the recursion guard that refuses `warden`
when `CLAUDE_CODE_SESSION` is set) and `tests/test_repo_write_guard.py` (the
guard that keeps a dispatched episode off paths it should never touch) — run
with `~/.hermes/hermes-agent/venv/bin/python3`. The signed-approval gate
itself now has its own suite in `~/SourceRoot/warden/tests/test_dispatch_approval.py`
(moved with the rest of the bridge); everything else (tiers, worktree
isolation, the merge verb, the ledger, repo policy) is tested in
`~/SourceRoot/warden/tests/` and `sideclaw/tests/` — not restated here since
it already drifted once.
