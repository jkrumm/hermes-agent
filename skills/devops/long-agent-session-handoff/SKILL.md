---
name: long-agent-session-handoff
description: Use when a long agent run must return a verified report.
version: 1.0.0
metadata:
  hermes:
    tags: [agent, handoff, watcher, report, verification, claude-code, herdr, dispatch, background]
    related_skills: [herdr, claude-dispatch, agents, agent-session-reporting, background-work-watch]
---

# Handing a long investigation to an agent session

Triggers: he asks for an agent to "really look at" something, an investigation
that will run 20-90 minutes, or any delegated session whose *output is a document*
he will act on while he is away from the screen.

The mechanics of each lane stay with that lane: opening and prompting a pane is
`herdr`, a tracked/unattended episode is `claude-dispatch`, reading a live session
is `agent-session-reporting`, the generics of waiting are `background-work-watch`.
This skill is the contract that spans them — the things that decide whether the
answer survives the trip back to him.

## 1. The brief: his words verbatim, plus an operational header

Write his text into the prompt file **as it stands** — never restructure,
summarise or "clean it up"; his phrasing carries the ask. Around it, a short
labelled header is legitimate and worth it:

- who is asking, and that he is unreachable (so the agent does not stop to ask);
- the concrete surface to look at (channel id, endpoints, prior sessions);
- **what to produce and where** (see §2);
- what "done" means for this run.

Mark the header as not part of the task, so the agent can tell his words from
yours. When the ask supersedes something already in flight, name that explicitly
so the agent verifies it instead of repeating it.

## 2. Contract: name the artifact file up front

A long answer arrives as scrollback that can scroll away, sit on an alternate
screen, or die with the pane. So put one line in the brief:

> write your full report as markdown to `/tmp/<task>-report.md`, plus a short
> version in your final message.

That file is what you read, what you can attach or re-read days later, and what
the watcher uses as its completion signal. Pane text is the fallback, not the
deliverable.

## 3. Watch it in the background, with an exit set

Never hold a turn open on it. Run one tracked background process with
`notify=True` and let the notice bring you back. The exit set must include
refusals, not just success:

- **finished** — the pane was seen `working`, then `idle`/`done` twice a minute
  apart, with the report file non-empty. Requiring a first `working` matters: the
  prompt returns before the turn starts, so an early poll reads `idle` on a pane
  that has not begun — accepting that is a false completion.
- **blocked** (an approval/question dialog) and **idle-without-a-report** end it
  too. Read the pane, tell him what it asks, never answer the dialog yourself.
- **timeout** and **pane gone** exit as their own states, so a dead run is never
  reported as a finished one.

## 4. Verify before relaying — the report is a self-report

The agent reports what it believes it did. Check the cheap, decision-relevant
claims against the artifact *before* they reach him:

- a claimed commit → `git -C <repo> show --stat <sha>`;
- a claimed test count → re-run that suite and compare;
- a claimed PR or branch → `gh pr view <n> --json state,isDraft,headRefName`;
- a claimed item state → the ledger or board, not the prose.

Relay the handle you just saw, or say plainly that it is the agent's claim and
unverified. He acts on these reports.

## 5. Report once, in the shape he reads

Verdict first, then the few findings that change his next move, then what is
already running and where it lives (ids). Attach the report file, and when he is
away from the screen send the same content as audio — spoken text is prose, not
the bullet list read aloud.

Say explicitly what is left undone: any follow-up you started names its pane/job
id, and any follow-up you deliberately did not start is named as a candidate with
a recommendation — not left as an open question.
