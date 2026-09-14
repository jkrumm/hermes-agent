---
name: agent-session-reporting
description: Use when reporting on a live agent session's progress.
version: 1.0.0
metadata:
  hermes:
    tags: [agent, session, status, report, claude-code, herdr, pane, verification, quota]
    related_skills: [herdr, agents, claude-dispatch]
---

# Reporting on a live agent session

Triggers: "wie läuft seine Session", "was macht der Agent in <repo>", "wo steht er",
"ist er fertig?", or any question about the state of one agent you (or he) started.

Scope: this is the **reading and reporting** half. Reaching a pane at all (the
`herdr pane read` / `agent get` verbs, explicit ids, focus rules) is the `herdr`
skill; the cross-project "what needs me" view is `agents` (sideclaw). This skill
is what to look at once you are there, and how to say it.

## Procedure

**1. Status word and transcript in one call.**

```bash
herdr agent get <pane> | jq -r '.result.agent.agent_status'
herdr pane read <pane> --source recent-unwrapped --lines 60
```

`idle` · `working` · `blocked` · `done` · `unknown`. `unknown` is a process herdr
cannot classify — *not* proof of completion. `done` means finished unseen work,
nothing about what it produced.

**2. Read the agent's final message, not the status word.** The last block carries
the substance: files written, commits, verdicts, questions left open. Summarize
that. A status word alone answers nothing.

**3. Read the footer.**

```
MAX · Fable 5.1 · high | 210k/970k 21% | 19min | 19%/5h ↺187m · 68%/wk
```

Model · reasoning effort · context used · wall time · subscription quota left.
Report these when he asks how the session is going — the `/5h` and `/wk` figures
are the decision-relevant ones: they say whether he can start another agent now.

**4. Read the input line `❯ …`.** Non-empty means text typed into the agent but
**never submitted** — a draft, usually his, sometimes a leftover. Name it and ask
whether to send it. Never submit it yourself and never treat it as yours to
clear: submitting a draft he was still editing destroys his edit.

**5. Say where it is.** Workspace label, tab id, pane id, what is running in it,
and — when it wrote durable knowledge — *which* place it landed (project Area for
him to read, project `wiki/` for the LLM, repo for the present state). "Started"
or "done" without ids is not an answer.

## Verify before relaying

An agent's closing summary is a **self-report**. "Committed and pushed", "all tests
pass", "wrote N files", "page created in the vault" are claims, not results. Check
the cheap ones before repeating them as fact:

```bash
git -C <repo> log --oneline -3
git -C <repo> status --short
```

Relay the verified handle (the hash you just saw, the file you just read), or say
plainly that it is the agent's claim and unverified. He acts on these reports; a
relayed-but-unchecked commit hash is worse than no report.

## How to answer

- Lead with **state + what it produced**, then the handful of findings that change
  his next move (verdicts that contradict a premise he holds, blockers, decisions
  waiting on him), then the quota footer.
- **Never paste the transcript** or its tables. Distil to bullets.
- German by default.

## Pitfalls

- The agent's framing can be wrong: it reports what it believes it did. The repo
  (and the vault) is ground truth — see *Verify before relaying*.
- Do not answer an approval/question dialog the pane is blocked on. Read it, tell
  him what it asks, let him decide.
- Do not submit text found in a pane's input line — that draft is his.
- A long run is not a stuck run. Poll `agent_status`; do not interrupt to "check".
