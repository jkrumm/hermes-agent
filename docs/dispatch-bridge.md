# Dispatch Bridge — Hermes's own side

The dispatch bridge is `agw-legacy dispatch` (agent-gateway's job-server CLI): one bounded Claude Code
episode in a worktree of the named repo, tiers `investigate` / `author` / `implement`, repo policy
from `agw-legacy policy`. There is no tracked lifecycle behind it — the control plane that once
merged, verified and chased episodes (warden) was retired 2026-10-27. `skills/dispatch/SKILL.md`
carries the brief rules and the command shapes; this file covers only what stays Hermes-side.

## The door: a Slack turn opens a dispatch

Hermes reads its world through **argo** and decides whether a dispatch is worth opening
(`skills/dispatch/SKILL.md` carries the hard rule that infra mutation is `homelab-ops`, never this).
Opening one is `agw-legacy dispatch --repo <name> --caller hermes --no-wait --json "$BRIEF"`;
the turn replies at once with the `jobId`, and the episode runs on the job server.

**Return path.** Nothing delivers a verdict for Hermes any more: the session reads it itself with
`agw-legacy status <jobId> --json` / `agw-legacy wait <jobId> --json --timeout 150`. When a thread
references a dispatch, Hermes re-reads the job rather than trusting thread history — the job record
is the durable copy, the Slack message only a notification.

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
`approval_decision` intent) is gone as of 2026-10-04: the control plane's approval stack it
fed was deleted, and the agent-platform spec keeps only quality gates. Trust comes from Tailscale and the
dispatch policy. Git history holds the design and its one bug (the public key overwritten by a
non-gateway process) if it is ever needed again.

## Tests (this repo)

The dispatch half (worktree isolation, the diff-refusal ladder, the secret scan, repo policy) is tested in
`agent-gateway/tests/` — not restated here since it already drifted once.
