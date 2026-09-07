---
name: agents
description: Report on the Claude Code / herdr agents sideclaw is tracking across every project — what needs Johannes, what's working, what's stale, what shipped. Use for "what are my agents doing", "which agent needs me", "project status", "was machen die Agenten", "wo steht <project>", "gibt es was zu tun", "refresh the agent overview", or any question about the state of a background coding agent or a project's open work.
version: 1.0.0
metadata:
  hermes:
    tags: [agents, herdr, claude-code, projects, sideclaw]
    related_skills: [claude-dispatch, obsidian]
---

# Agents overview — read-only status across every tracked project

sideclaw (a local daemon on this mini, `http://localhost:7705`, the same
service `scripts/hermes-cc.sh` uses for the dispatch bridge) keeps a live
overview of every Claude Code / herdr agent running across every project:
what it's doing, whether it's blocked, and a one-word recommendation
(`answer` = blocked on a question, `continue` = idle mid-task, `ship` = done
but uncommitted/unpushed, `review` = pushed, needs review, `merge` = PR
ready, `close` = finished, `stale` = abandoned, `watch` = working, nothing
to do).

**This skill is READ-ONLY.** It never sends keys to a herdr pane and never
dispatches a new episode — it only reads sideclaw's overview. Steering an
agent (answering it, nudging it to continue, opening a new episode) is
`claude-dispatch`'s job, not this one.

## Quick read (no refresh, ~instant)

Bare `curl`, no pipe — piping `curl` output straight into another program is
what tirith's pipeline gate exists to catch (see `podcast`'s pattern), so
read the plain-text overview directly:

```bash
curl -s http://localhost:7705/api/overview.txt
```

Output is ≤ ~40 lines: a header (`agents: N needs_you · N working · N idle ·
N stale · N done · N dispatch  (ISO)  · overview <age>|none`), then per
project `▸ <name>  <branch>[*dirty]  [N agents]` and per agent
`  <icon> <state> <title>  · <age>[  · <waitingFor>]` with an indented
`— <standing>` line. Icons are the recommendation: `?!` answer, `→`
continue, `⇧` ship, `⚑` review, `⇄` merge, `✓` close, `·` stale, `●` watch.

This is enough for almost every question — "what needs me" is just the
`?!` lines, "how's `<project>`" is that project's `▸` block.

## Detail read (structured, when a field the text doesn't carry is needed)

Two commands, never a pipe — write to a file, then `jq` it:

```bash
curl -s http://localhost:7705/api/overview -o /tmp/hermes-agents.json
jq '.data.projects[] | select(.name == "<project>")' /tmp/hermes-agents.json
```

Shape: `{ok, data: {summary{needsYou, working, idle, stale, done, dispatch},
overview: {generatedAt, model, ageMs} | null, projects: [{name, cwd,
git{branch, dirty, ahead, behind, lastCommit}, agents: [{id, title, state,
waitingFor, lastActivityAt, recommendation, standing, blocker,
confidence}]}], warnings[]}}`.

## Refresh (when the overview looks stale)

The header's `overview <age>` tells you how old the last LLM pass is. If
it's stale and Johannes is asking a real question (not just skimming),
trigger a fresh one — bounded, since the `terminal` tool caps at 180s and a
pass runs a Haiku summarization over every agent (usually 30–60s):

```bash
JOB=$(curl -s -X POST localhost:7705/api/jobs \
  -H 'content-type: application/json' -d '{"tool":"overview","params":{}}' \
  | jq -r '.job.id')
```

Then poll, at most 6 times, 20s apart (~2 minutes — one `terminal` chunk):

```bash
for i in $(seq 1 6); do
  ST=$(curl -s "localhost:7705/api/jobs/$JOB" | jq -r '.job.status')
  [ "$ST" = "done" ] || [ "$ST" = "failed" ] && break
  sleep 20
done
curl -s http://localhost:7705/api/overview.txt
```

If it's still `running` after 6 polls, stop — don't loop for the whole
prompt turn. Tell Johannes the refresh is still going and answer from the
last-known overview in the meantime; offer to check back.

## How to answer

- Reply in Johannes's language (usually German).
- **Never paste the whole dump** for a question about one project or one
  agent — pull just the relevant `▸` block or `?!` lines.
- **Lead with what needs him**: `answer` items first, then `ship`/`merge`,
  then `review`, then everything else only if asked.
- If nothing needs him: say so in one line ("Alles ruhig, kein Agent
  braucht dich gerade") rather than dumping the full stale/watch list.
- A `?!` (answer) item is worth naming even unprompted if he asks "what's
  going on" generally — it's the one state where an agent is actually
  stuck waiting on him.

## Related automation

`scripts/agents-overview.py` (a scheduled no-agent script, not part of this
skill's conversational path) posts a Slack digest and feeds the morning
briefing — see `docs/agents-overview.md`. Both of its refreshes are
consumer-driven, not clock-driven: the briefing refreshes only when the
cached overview is older than 2h, and the digest refreshes only when a
deterministic `/api/agents` snapshot fingerprint changed since its last run.
That script is the unattended path; this skill is the conversational one.

**"Post the overview to #agents"** (or a request for a screenshot of the
digest): run the bare command below — no pipe, it posts Block Kit directly
via `chat.postMessage` and needs no further processing of its output.

```bash
python3 ~/SourceRoot/hermes-agent/scripts/agents-overview.py --post-full
```
