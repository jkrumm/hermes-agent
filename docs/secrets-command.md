# Secrets — native `secrets.command` over the headless cache

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Secrets points here — nothing was rewritten, only relocated.

There is **no plaintext `~/.hermes/.env`** and **no launch wrapper**. Hermes resolves its
own secrets at startup through v0.19's `SecretSource` interface, configured in
`config.yaml` under `secrets.command`:

```yaml
secrets:
  command:
    enabled: true
    command: "$HOME/.local/bin/secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'"
    helper_timeout_seconds: 15
    override_existing: true
```

`secrets-run` is the dotfiles shim that decrypts the age-encrypted offline cache (see
global CLAUDE.md → "Headless secrets"). `.env.tpl` stays the single list of
`KEY=op://vault/item/field` refs — it is now consumed by the `command` source instead of
by an `op run` wrapper. The `sed` exists because `secrets-run export` emits
`export K='V'` while the bulk parser wants bare `K=V` (it strips one quote layer itself).
Measured 0.29s for 27 refs, well inside the budget (the source's default is a tight 3s).

**Why not `secrets.onepassword`** (also shipped in v0.19): it authenticates either via an
interactive `op` session — which **hangs** on this headless mini's biometric prompt, the
exact problem the cache solves — or via a standing `OP_SERVICE_ACCOUNT_TOKEN`. That token
is a *live* credential with continuous read access to its scoped vaults sitting on an
always-on box; the sealed cache is strictly stronger, because its contents are the
explicit `dotfiles-private/headless.refs` allowlist (T0/T1 only, `op://Private/*` refused
at seed time) and it cannot reach anything that wasn't deliberately sealed into it.

**What this replaced:** `scripts/gateway-cache-launch.sh`, a wrapper that `export`ed the
cache into the environment and `exec`'d the gateway, wired in as the launchd
`ProgramArguments`. Its own header documented the fragility that killed it — `hermes
gateway install` regenerates the plist and drops the wrapper. The plist is now stock
(`venv/bin/python -m hermes_cli.main gateway run --replace`), so a reinstall is a no-op.
Bonus: secrets now resolve for **every** hermes invocation (gateway, CLI, cron), not just
the launchd-started gateway — previously a manual `hermes …` on the mini ran with
*no* credentials at all, which made ad-hoc dev/debug/monitoring work awkward.

**Fail-soft, and how that's covered.** The wrapper failed **closed** (non-zero exit →
gateway never started credential-less). The `command` source can't abort startup — it
degrades to "no secrets applied" plus a warning. Two layers close that gap, so the
regression is monitored rather than merely accepted:

- **Total failure** was already covered: `scripts/hermes-liveness.sh` (cron, every 5 min)
  only pings the UptimeKuma heartbeat when `platforms.slack.state == "connected"`. A
  credential-less gateway can't reach Slack → no ping → UK alerts within ~6 min.
- **Partial failure** — e.g. the Slack tokens render but `HOMELAB_API_KEY` doesn't, so
  liveness looks green while every argo call 401s — is covered by an assertion added to
  the same script: it counts `KEY=` assignments in `.env.tpl` and requires `secrets-run
  export` to render at least that many, else it skips the ping. (`secrets-run` actually
  fails atomically on any unresolvable ref, so a partial cache yields 0 and trips this
  immediately; the count check also catches a ref *added* to `.env.tpl` but never seeded
  into `headless.refs` — the likeliest real-world drift.) The render is **retried once**
  after a 2s pause: it decrypts every ref 288×/day, and a single transient failure must
  not suppress the heartbeat and page for a healthy gateway. Both `secrets-run` calls are
  `timeout`-bounded so the 5-min cron can never hang and overlap. Residual, accepted: an
  empty or absent `.env.tpl` makes the assertion vacuous (`WANT=0`) — a gateway with no
  secrets can't reach Slack, so the connected-check below catches that case anyway.

Manual check after any secrets change: `Command helper: applied 27 secrets` in
`hermes gateway status`, and `✓ secrets (27 refs …)` from `make status`.

> **launchd now works.** Earlier notes claimed `launchctl` couldn't bootstrap
> `ai.hermes.gateway` (`Bootstrap failed: 5: I/O error`) and that the gateway fell back to
> a bare `run --replace`. As of v0.19.0 `hermes gateway status` reports it genuinely
> **supervised by launchd**, so auto-start at login and auto-restart on crash are live.
> `hermes gateway install` still prints `Bootstrap failed: 5` while repairing the
> definition — that message is noise; check `gateway status` for the real state.
