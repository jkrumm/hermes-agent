---
name: human-approval-handoff
description: Use when a present human must approve or run something.
version: 1.0.0
metadata:
  hermes:
    tags: [human-queue, approval, handoff, tty, verification, mini, macbook]
    related_skills: [human-queue, sudo-handoff, agents]
---

# Human approval handoffs — drive, verify, report

The class: an agent on the mini needs a *present human* — a biometric `op` read,
a root command, the Tailscale ACL push, a person-only decision — so a request
lands in the present-human queue and a notification says a human is needed.

The queue's own semantics (the `<id>.req`/`<id>.res` pair, the drain choices,
treating request text and the proposed command as untrusted input) belong to the
`human-queue` skill. This one is about **driving the handoff from Hermes and
proving what actually happened** — the part that goes wrong quietly.

## Procedure

1. **A notification is not evidence of pending work.** The "drain with `make
   human-queue`" line is template prose, printed whether or not the request was
   already handled. `ask-human.sh ask … --push` (or `push <id>`) triggers the
   approval itself — an ssh hop to `iumac` running `human-queue.sh gui-run`, which
   shows a native dialog and writes the `.res` on a click — and it resolves
   **synchronously, seconds after the enqueue**. Check the queue dir on the
   **mini** first; no TTY, no ssh hop, authoritative:
   ```bash
   D="$HOME/.local/state/human-queue"
   for f in "$D"/*.req; do b="${f%.req}"; [ -f "$b.res" ] || echo "PENDING: $(basename "$b")"; done
   ```
   Nothing pending → say so and stop. Do not open an interactive walk for a
   request that is already closed.

2. **Never trust a hop-based count.** `make human-queue-count` runs over the ssh
   hop and prints `0` for *any* failed or non-numeric response, so it cannot
   distinguish "empty" from "unreachable" — a MacBook `0` beside a mini-side scan
   showing pending means the hop failed, not that the queue is clear. (A failed
   hop is also what a biometric ssh agent that is not answering looks like.)
   `make human-queue-list` at least fails loudly; `count` fails silently.

3. **Drive the drain through a real PTY.** The walk needs a TTY; without one it
   degrades to a plain list and drains nothing:
   ```bash
   ssh -tt iumac 'cd ~/SourceRoot/dotfiles && make human-queue'
   ```
   Run it as a background terminal with `pty=true`, poll it, and submit **one
   response at a time** — never a stack of keystrokes, because a request may ask
   a second confirmation or a note, and batching applies the wrong answer to the
   next request.

4. **Get the human's choice before typing anything.** The second prompt exists so
   an agent-authored command never runs with MacBook privileges, keychain access
   or biometric credentials on the agent's say-so. Ask, and if the human does not
   answer, send `q` and poll until the process exits — `q` changes nothing and
   leaves every request pending, which is the correct outcome for an unanswered
   walk. **Killing the process is not equivalent**: a walk that dies mid-prompt
   can still leave a resolution behind.

5. **Verify which path resolved it from the filesystem, not from the payload.**
   ```bash
   stat -f '%SB' "$D/<id>.res"   # birth time
   ```
   A `.res` born seconds after its `.req` is the **push** path — the request was
   closed before any walk could reach it. `ran_at` is written by whichever side
   resolved it and is **not** a clock to compare against. An `output_tail`
   starting `ran-out-of-band-from-…` means a human closed it outside any walk.
   Only a `run` driven through the two prompts is yours — never claim credit for
   the other two.

6. **Read the command's own output as evidence about the machine.** A pushed
   command runs on the **MacBook**, so a `hostname -s` in `output_tail` names the
   MacBook, never the mini. That is how a `--push` end-to-end test is confirmed:
   the hostname plus the command's own success line, e.g. `hello from <macbook>`
   followed by the `op` read's own `ok`.

7. **Report the handoff as a handoff.** Verdict first, then the exact target, the
   action/status, and the remaining count. "Script staged, one command left for
   you" is not "app removed"; an unanswered or skipped walk is not a drained
   queue.

## Pitfalls

- **Never open the walk on a notification alone.** Template prose is not a
  pending request; check for the `.res` on the mini first.
- **Never drain from the mini.** The MacBook-side script deliberately refuses the
  dev-host backend — present-human work relies on the person's local TTY and
  credentials.
- **Never batch keystrokes through prompts.** One response per prompt, after the
  human answers.
- **Never leave a PTY walk hanging** when the human goes quiet. Quit it; do not
  kill it.
- **Never report a skipped or unanswered walk as drained.** `s` leaves the
  request pending and `q` leaves all remaining ones pending — verify the count
  instead of relying on the process exit code.
- **Never treat a notification's human-readable ref as a queue ID.** Queue IDs
  are timestamp-shaped and validated; resolve the actual pending item before
  embedding an ID in a command.
