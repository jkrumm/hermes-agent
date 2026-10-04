# Probe fidelity

_Use when a probe may not measure what it claims._

An alert, a health check, a smoke test and a backup verifier are all *probes*:
programs that stand in for a real consumer and report whether it would work. A
probe is evidence about its subject **only when it runs in the same environment
the consumer runs in**. When it does not, the failure it reports belongs to the
probe, and every reader attributes it to the subject.

This is the class of alert that survives the obvious checks: the subject is
green, nothing is missing, and the alert is still not wrong — the probe really
did fail. It just answered a different question than the one it was built to ask
("would this work from *my* shell").

Load `alert-mechanism-forensics` for the subject's mechanism and
`alert-liveness-forensics` for whether the condition is live. This skill is the
third possibility both of them assume away: **the producer is the fault.**

## Procedure

1. **Separate the subject from the producer, then read the producer's own
   artifact.** The alert text records what a probe observed; the probe's command,
   the log it writes and its success record record what it did. Never diagnose the
   subject from the alert text alone.
2. **Diff the probe's environment against the consumer's.** Four facts decide it:
   which shell, which environment variables, which working directory, which
   identity. The recurring one is a **non-login shell** — cron, a remote command
   over ssh, a launchd job — versus a login shell that sources a profile: anything
   the profile exports is simply absent in the first. Check the two lists rather
   than reasoning about them.
3. **A/B the two shapes and count the cost, not just the exit code.** An
   unfaithful probe usually still *succeeds* while working harder: an extra
   network round-trip per call, a cold cache, a fallback path. Measure per-call
   cost on both shapes (request counts, wall time). A probe that costs 4 requests
   where the consumer's costs 0 is a probe that will exhaust a shared quota and
   then report the quota's error as the subject's fault.
4. **Fix the probe, and its siblings.** A probe running outside its consumer's
   environment is a property of a *pattern*, not a file. Grep the whole shape
   across the tree — and the neighbouring repo that issues the same kind of remote
   command — and fix every site in one pass; the sites nothing has reported yet are
   the ones that keep the false positive armed.
5. **Prove the fix from the producer's own success record**, then re-check the
   subject. See the first pitfall; the absence of an error line is not the claim.

## Pitfalls

- **Absence of the error line is weak evidence; the producer's own success record
  is strong.** A probe that stopped failing may have stopped running. Read the
  thing written only on *success* — a cursor row, a `last_ok` timestamp, a
  completion marker — and quote it. "No error since the fix" plus "the cursor
  reads ok at <time>" is a proof; the first half alone is not.
- **The same root cause can surface as two different failure classes.** A
  dependency that fails fast returns an error immediately; the same dependency
  under load *blocks*, and the probe's own timeout reports that instead. So "the
  error I was shown is gone" is not "healthy" — read the probe's whole failure
  family in its log and distinguish the classes before declaring one extinct.
- **Read a cadence off the code's own gate, never off log-line frequency.** A job
  spaced by a cursor is retried on *every* tick while it fails, because the cursor
  is written on success only — so the log makes an hourly job look per-tick, and
  the "N times a day" you write down is wrong. The gate is in the source
  (`if (now - last) < INTERVAL_S: return`); the live spacing is in the state row.
- **A faithful probe must still fail on the real defect.** When the fix is "run
  the probe the way the consumer runs", assert the other direction in the same
  file: a genuinely missing input is still reported. Without that case, the next
  reader cannot tell the fix from a probe that now passes unconditionally.
- **A sourcing guard must survive the shell that runs it.** `[ -r "$file" ] &&
  . "$file";` — the `[ -r ]` test is load-bearing, because `.` is a POSIX special
  builtin and `dash` aborts the *entire* command line when it cannot open the
  file, taking the rest of the command down with it.
- **Guarded environment sourcing can eat a piped payload.** If the remote command
  ends in an interpreter that reads its program from stdin (`ssh host '… python -'`
  with the script on stdin), a sourced profile that reads stdin consumes it. Test
  the shape with the payload actually on stdin, never with a `--version`-style
  argument that happens to exit 0.
- **"No dangling item" is not a finding a broken probe can produce.** A probe that
  dies before it can look reports the absence of what it could not check. Read the
  probe's failure mode before believing its conclusion: an error from the
  *transport* — quota, timeout, auth — says nothing about the subject's contents.
- **An alert can be a true statement about a stale card.** Silence does not
  discharge an open item: a resolved signal and a closed card are different rows,
  and the probe's consumer keeps re-sending the card. Fixing the probe ends the
  *signal*, not the item — check the item's own state and close it separately.
