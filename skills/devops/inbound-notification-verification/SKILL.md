---
name: inbound-notification-verification
description: "Use when a push names a queue or work id. Verify first."
version: 1.0.0
metadata:
  hermes:
    tags: [notification, push, hook, queue, human-queue, verification, phantom, producer, state-db, triage]
    related_skills: [human-queue, status-projection-verification, alert-liveness-forensics, warden]
---

# Inbound notification verification

An automated push — a Slack line from a queue hook, an agent's "human needed"
announcement, an alert card naming an id — is written by a **producer** at the
moment it acts. The store that owns the work is the truth; the push is a
notification about a moment that has already passed. Resolve the named id
against the store before you act, escalate, or report.

Use this for any inbound message that names a ref, id or work item. The
read-only surface skills (`human-queue`, `warden`) own *how to call* the store;
this skill owns *what the push entitles you to claim*.

## Procedure

1. **Resolve the named id in the store before doing anything else.** For the
   present-human queue the store is the mini's own dir, and both files are the
   answer:
   ```bash
   D="$HOME/.local/state/human-queue"; cat "$D/<id>.req"; cat "$D/<id>.res"
   ```
   Then count what is actually pending — never the push's claim:
   ```bash
   for f in "$D"/*.req; do id=$(basename "$f" .req); [ -f "$D/$id.res" ] || echo "PENDING $id"; done
   ```
   A store with every `.req` paired to a `.res` and zero pending is an empty
   queue, whatever the notification said.

2. **Absent id + empty store = phantom, not a lost request.** Do not drain, do
   not re-enqueue, do not escalate. Report the store's real state and say the
   notification named an id the store does not have.

3. **Trace the producer before concluding anything is broken.** A push whose
   artifact is gone was almost always written by a producer that then removed
   its own artifact — a hook test, or a self-cleaning probe. The producer's
   transcript is on this machine and shows the exact command that created *and*
   deleted it. Quote the tool call as the evidence instead of inferring a cause;
   the recipe is the *Producer tracing* section below.

4. **Two ids seconds apart from one producer are one test, not two requests.**
   A harness that fires a hook twice produces a plausible-looking pair; the
   second one's text is often detailed enough to read as genuine work. Correlate
   both ids to the same session before treating either as real.

5. **Report what the store says, then what the push claimed.** Lead with the
   verified state (counts, pending ids), then name the notification as a phantom
   and its producer. Never report "drained" for a queue you never walked, and
   never report "nothing happened" for a push that did fire — both are claims
   about different things.

6. **If the push pointed at genuinely outstanding work, hand over the action.**
   A verified-but-unsatisfiable request (see the host-mismatch pitfall) becomes
   one exact command for the user, not a re-enqueue and not a workaround.

## Producer tracing

A push that names an id but whose artifact is gone is not an unexplained event:
the producer ran on this machine, and its transcript is queryable.

**1. The arrival line gives time and channel, not the producer.**

```
INFO gateway.run: inbound message: platform=slack user=<name> chat=<id> msg='…' reply_to_id=None
```

`grep -n "<HH:MM>" ~/.hermes/logs/agent.log` around the push timestamp gives the
exact second and the channel. A local hook script posts through an HTTP client,
not through the gateway, so this line never names the producer.

**2. Correlate the second against the agent log.** In the same second window the
agent log carries the session id of whatever was running:

```bash
grep -n "<HH:MM:SS>" ~/.hermes/logs/agent.log | grep -E "tool_executor|conversation_loop"
```

`tool terminal completed (…s, N chars)` lines carrying a session id are the
producer's own tool calls. Note that session id.

**3. Read the producer's transcript from the session store.** The durable copy of
every turn is `~/.hermes/state.db`. Read it read-only — the CLI on this host has
no `-uri`, so use Python:

```python
import sqlite3
c = sqlite3.connect('file:/Users/jkrumm/.hermes/state.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
for r in c.execute("""select id, role, timestamp, substr(coalesce(content,''),1,400) c,
                           substr(coalesce(tool_calls,''),1,800) tc
                    from messages where session_id=? order by id""", (sid,)):
    print(r['id'], r['role'], r['timestamp'], (r['c'] or '')[:400])
    if r['tc']: print('TC:', r['tc'][:800])
```

Schema facts that cost time if guessed:

- `messages` has **no `created_at`** — the time column is `timestamp`, a float
  epoch. `sessions` carries `started_at`, `ended_at`, `last_activity_at`,
  `last_activity_description`, `title`, `source`.
- The **`tool_calls` column is the evidence**: the exact command lives in
  `function.arguments` as JSON. That is how you show that one command created the
  artifact and a later one deleted it, rather than inferring it.
- `reasoning` on an assistant row often states the producer's intent in prose
  ("let me clean up the test request") — useful corroboration, never the proof.

**4. Confirm the store agrees.** Re-read the store after the transcript: the
transcript says what was attempted, only the store says what survived. Both
together are the report.

This chain does **not** tell you whether the work is still needed — a deleted
request can describe a genuine outstanding problem. Verify the underlying
condition separately and hand the action over if it still holds.

## Pitfalls

- **A push outlives its artifact by construction.** The hook fires *after* the
  request lands on disk, and nothing re-checks the store when posting — so a
  producer that deletes its own `.req` leaves a live Slack line pointing at
  nothing. Treat "the notification exists" and "the work exists" as two
  independent facts and verify the second.
- **Never test a notification hook with a real-looking request.** A probe that
  enqueues a plausible request text is indistinguishable downstream from real
  work: it reaches the human's channel, it can be drained, and its id will be
  chased by the next reader. Test with a text that announces itself as a test,
  and delete the artifact in the same step that created it.
- **A queue request's `cmd` executes on the draining host, not the enqueuing
  one.** The mini proposes; the MacBook runs. A request to restart or reconfigure
  something *on the mini* therefore cannot be satisfied by a drain — the command
  would run on the wrong machine. Check the target host against the executor
  before offering the queue as the path, and hand the command over instead.
- **A guard-blocked command is not a reason to re-enqueue it elsewhere.** When
  the action is blocked for you (a self-restart, a privileged change), the
  correct output is the one command for the user plus the reason it is theirs —
  not a queue entry, not a script that spells the phrase differently.
- **Never claim credit for a resolution you did not drive.** A `.res` written by
  someone else, a count that dropped between two reads, or work finished out of
  band is a fact about the store, not about your walk. Say who did it when you
  can tell, and say you cannot when you cannot.
- **Do not consume unrelated pending work to satisfy a notification.** If the
  named target is absent, stop — resolving a neighbouring request because it was
  the only thing pending applies a human decision to the wrong item.
