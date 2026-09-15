---
name: noninteractive-context-verification
description: Use when a cron/launchd job fails but your shell works.
version: 1.0.0
metadata:
  hermes:
    tags: [cron, launchd, systemd, environment, verification, daemon, socket, xdg, headless, a-b, testing]
    related_skills: [headless-secrets, homelab-ops, live-process-change-verification]
---

# Verifying a fix in the context that actually runs it

**Your interactive shell is not the test environment.** A cron job, a launchd
agent and a systemd unit each run with a different environment than the shell you
are typing in — different `PATH`, often no `XDG_RUNTIME_DIR`, no login session, no
`HOME`-derived config the way you expect. A change that works when you run it by
hand can be inert under the scheduler, and the failure is usually **silent**: the
command still succeeds, it just takes a slower or wrong path.

Reach for this whenever the deliverable is "the job will work from now on" rather
than "the command works right now".

## Procedure

1. **Name the context that runs it, and how it gets its environment.** A crontab
   line either sources a profile explicitly (`. ~/.profile; <cmd>`) or gets almost
   nothing. launchd agents get a minimal environment unless the plist sets one.
   systemd units get `Environment=`/`EnvironmentFile=` only. Write down which.
2. **Reproduce that context for the test, rather than testing interactively.**
   ```bash
   env -u XDG_RUNTIME_DIR <cmd>          # the variable cron does not have
   bash -c ". ~/.profile; <cmd>"         # exactly what the crontab line does
   ```
   The second form is the honest one when the crontab sources a profile: it proves
   the file you edited is the file cron reads.
3. **When you cannot reproduce it by hand, install a temporary probe.** Append a
   one-shot crontab line that dumps the environment *and* runs the command with its
   debug flag on, wait one interval, then remove the line and read the log.
   ```bash
   ( crontab -l; echo "* * * * * . /home/<user>/.profile; { echo \"VAR=[\$VAR]\"; <cmd> --debug 2>&1 | head -4; } >> /home/<user>/logs/probe.log 2>&1" ) | crontab -
   # ... wait one interval ...
   ( crontab -l | grep -v probe ) | crontab -   # ALWAYS remove it, and rm the log
   ```
   This is the only way to see the real environment rather than an approximation of
   it. It is a diagnostic, not a fix — take it back out.
4. **Look for a second process that derives its own path/state from the same
   variable.** This is the part that gets missed. If a client and a background
   daemon both compute a socket, cache or state path from the same env var, setting
   the var is what makes **both halves agree** — verify the daemon's path too, not
   just the client's.
   ```bash
   ss -xlp | grep <socket-name>        # where the daemon actually bound
   ps -o pid,user,lstart,cmd -C <name> # which instances exist, and since when
   ```
5. **A/B from a clean state** (see the first pitfall). Change one variable at a
   time and read a line of output that *names the path or state*, never just the
   exit code.
6. **Verify the effect, not the exit code.** A command can exit 0 while having used
   the wrong path. Find the debug/trace line that states which path it took or
   whether the cache engaged, and quote that as the evidence.
7. **Leave nothing behind.** Temp cron entries, probe logs, stray daemons and test
   sockets all get removed, and the final state gets re-read once.

## Pitfalls

- **A pre-existing process makes the broken case look fixed.** The classic wasted
  hour: you test "without the fix" and it passes, because a daemon started earlier
  was already serving the right path. **Kill the old instances and remove the stale
  sockets/state before the first run of an A/B**, and confirm the slate is clean
  (`ps`, `ss -xlp`) before you attribute anything to your change. Two variables
  moving at once is not a test.
- **`pkill -f "<pattern>"` over ssh kills your own session.** The pattern matches
  the ssh command line you just sent, so the shell dies mid-command and you get an
  empty result that reads like "nothing was running". Target by user and exact name
  and kill by pid instead:
  ```bash
  for p in $(pgrep -u <user> -x <name>); do kill $p; done
  ```
- **A process may be spawned by the very command you are testing.** A first
  invocation can start a daemon that then serves every later call — so the "before"
  run and the "after" run are not measuring the same thing. Clean up *between*
  runs, not only before the first.
- **Do not fix the symptom in the wrong layer.** If the real cause is a shared
  budget, a shared quota or an upstream limit, no amount of local tidying clears it;
  identify whether the error is served from local state or live from the server
  (test with the local component stopped, and with caching disabled) before
  recommending a restart.
- **A restart is not a reset.** Restarting a local cache/daemon does not clear an
  error the server is generating. Confirm which side produced the error before
  telling anyone to restart anything.
- **Root and a login user can diverge for the same reason.** A fallback path that
  exists for one uid and not another (`/run/user/0` vs `/run/user/1000`) makes the
  same command behave differently under each. When one account's jobs stay green
  while another's fail identically, suspect the fallback, not the account.

## Worked example

`op`'s local cache is served by an `op daemon` over a UNIX socket, and **both the
client and the daemon derive that socket path from `XDG_RUNTIME_DIR`**. Cron has no
`XDG_RUNTIME_DIR`, so the client dialled `/run/user/<uid>/…` while the daemon
listened in `~/.config/op/`. The cache never engaged, every `op` invocation went to
the network, and a shared account-wide daily request budget drained until it
started returning rate-limit errors. Nothing failed loudly — secrets still
resolved. Pinning `OP_SOCK` in the profile every cron sources made both halves
agree. Full mechanism, per-call request counts and the budget arithmetic:
`headless-secrets`.
