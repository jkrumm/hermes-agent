# Dispatch Bridge — Hermes's own side

The dispatch bridge itself (tiers, the sideclaw `dispatch` job tool, the
worktree isolation, the `merge` verb, the ledger schema, repo policy) moved
to `~/SourceRoot/warden` on 2026-09-10 — see its `DESIGN.md` (authoritative
design), `AGENTS.md` (developer notes) and `FLOWS.md` (six end-to-end
scenarios). `scripts/hermes-cc.sh` in this repo (= `~/.hermes/scripts/hermes-cc.sh`)
is now a 6-line exec shim into `warden/scripts/warden`, kept because its
exact path is the one every other doc and script here references.

What genuinely stays Hermes-side is the door a Slack turn opens through.

## The door: a Slack turn opens a dispatch

Hermes reads its world through **argo** and decides whether a dispatch is
worth opening (`skills/dispatch/SKILL.md` carries the brief rules
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

## Removed: the signed approval artifact

`plugins/dispatch-approval/` (Ed25519 key minted at gateway startup, Approve/Deny buttons, the
`approval_decision` intent) is gone as of 2026-10-04: warden Wave 1 deleted the approval stack it
fed, and the agent-platform spec keeps only quality gates. Trust comes from Tailscale and sideclaw's
repo policy. Git history holds the design and its one bug (the public key overwritten by a
non-gateway process) if it is ever needed again.

## Tests (this repo)

Everything (worktree isolation, the merge train, the ledger, repo policy) is tested in `~/SourceRoot/warden/tests/` and
`sideclaw/tests/` — not restated here since it already drifted once.
