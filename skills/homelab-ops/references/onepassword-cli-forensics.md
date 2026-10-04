# 1Password CLI forensics

_Use when an `op` call fails or is rate-limited._

Use when an `op` call fails, is rate-limited, or silently bypasses its cache.
Diagnoses the two failure classes that share one exit status — a dangling ref
versus an exhausted service-account budget — and the daemon-cache miss that
causes the second.

Scope: `op` running against a **service-account token** on a server (homelab,
vps) — cron jobs, `op run --env-file`, `op read`. The seed → cache → app chain
for the mini and MacBook is `headless-secrets`; this file is the runtime failure
side.

## Two failure classes, one `ok:false`

`op run` fails **wholesale** for two unrelated reasons that are indistinguishable
by exit status:

| Cause | `danglingItems` | Cause lives in |
|-|-|-|
| A renamed/deleted item | populated | the item names |
| Service account rate-limited | **empty** | `error` / stderr |

**Rule: whenever `ok:false`, read the error field — never render an empty dangling
list as "no dangling item, likely transient".** That is exactly what a fleet-wide
outage looks like, and the transient wording tells the reader to wait.

## Procedure

1. **Read the budget first.** One command, both hosts:

   ```bash
   ssh <host> 'bash -lc "op service-account ratelimit"'
   ```

   `account read_write  USED == LIMIT, REMAINING 0` = the account-wide daily
   budget is spent. The `token read` / `token write` rows are per-token *hourly*
   limits that reset on their own — the `account` row is the one that bites.

2. **Check whether the cache is engaging.** `OP_DEBUG=true` prints the daemon
   handshake:

   ```bash
   ssh <host> 'cd ~/<repo> && OP_DEBUG=true op run --env-file=.env.tpl -- true 2>&1 | grep -E "InitDefaultCache|requests complete"'
   ```

   - Healthy: `DEBUG InitDefaultCache: successfully initialized cache` and
     `requests complete requests=2`.
   - Broken: `WARN InitDefaultCache: failed to establish RPC connection with
     daemon: dial unix /var/run/user/<uid>/op-daemon.sock: connect: no such file
     or directory` and `requests=4`. The cache is off and every invocation goes
     to the network.

3. **Separate ref problem from budget problem before touching anything.** A
   dangling ref fails identically for every caller on every host; a budget problem
   fails everywhere at once *with the empty dangling list*. Only the second is
   fixed by anything below.

## The daemon cache, and why it silently turns off

`op` resolves its daemon socket from `XDG_RUNTIME_DIR`, falling back to
`/run/user/<uid>/op-daemon.sock`. The daemon itself listens at
`~/.config/op/op-daemon.sock`. A **cron environment has no `XDG_RUNTIME_DIR`**, and
`/run/user/<uid>` is tmpfs created by login/ssh sessions (`Linger` is off by
default) — so when it exists at cron time the client dials a socket that isn't
there and the cache never engages.

**Root is structurally immune: `/run/user/0` does not exist, so root falls back to
`/root/.config/op/op-daemon.sock` and root's cache works. A host where root's crons
succeed while every user cron fails is this bug — not a ref problem, and not a
network problem.**

Fix — pin the socket in the user's shell profile, which every cron line sources:

```bash
export OP_SOCK="$HOME/.config/op/op-daemon.sock"
```

`OP_SOCK` is the documented override and wins over the XDG path.

**Verify in the real cron context, not an interactive shell.** An ssh session is
not a valid test — it creates a login session that changes socket resolution. The
honest test is a temporary crontab line that dumps `$OP_SOCK` and the debug line,
removed afterwards.

Cost of the bug: cached `op run` = 2 network requests, uncached = 4; `op read` = 1
vs 3. At a few hundred invocations a day that multiplier alone exhausts a
1000/day budget.

## Budget arithmetic — do it before blaming the cache

Count the traffic before concluding:

```bash
ssh <host> 'journalctl --since "24 hours ago" --no-pager | grep -c "op run --env-file"'
ssh <host> 'journalctl --since "24 hours ago" --no-pager | grep "op run --env-file" | grep -o "scripts/[a-z-]*\.sh" | sort | uniq -c | sort -rn'
```

The budget is **per 1Password account, shared across every host and every
consumer** — one host's burst starves the other. Add the other hosts, the mini's
LaunchAgents, and any bare `op read` in a script before declaring headroom.

A cache fix removes the *multiplier*, not the traffic. Say the remaining headroom
out loud with the number instead of implying the fix removed the ceiling.

**Reset is a rolling 24h window from first use, not midnight.** Report the actual
reset time from `ratelimit` (it prints "N hours from now"), never "tomorrow".

## Pitfalls

- **`op whoami` succeeding proves nothing about the budget.** Identity lookups are
  cheap and cached; it answers while every real read is refused. `ratelimit` is the
  only honest read.
- **An ad-hoc `op read` costs the same budget as a production cron** — 3 requests
  for a name-addressed item, 1 when you pass item and vault IDs. Diagnostic probing
  during an incident is not free; prefer one `ratelimit` call to many reads.
- **Fix it in the shell profile, not in the cron lines.** Every cron entry sources
  the profile, so one export covers all of them; a per-cron `OP_SOCK=` prefix has to
  be repeated and will drift.
- **Make the fix durable in the repo that provisions the host.** A `~/.profile`
  export is untracked, so a re-provision or rebuild silently reintroduces the cache
  miss. Land it in the host's setup script and its setup docs, and record the
  mechanism in that repo's decisions doc so a future reader does not delete the
  export as redundant.
- **Do not change cron cadence as part of this fix.** Fewer invocations is a real
  remediation for a thin budget, but it is the owner's decision about operational
  urgency — report the arithmetic and the headroom, and leave the schedule alone.
- **Never print a secret.** Verify by length, hash, or exit status.
- **A monitor going red for a missing heartbeat is downstream of this.** When
  op-wrapped crons fail, push monitors go DOWN because the pusher never ran — the
  service they monitor is usually fine. Check the substance before reporting an
  outage; see `alert-liveness-forensics`.
