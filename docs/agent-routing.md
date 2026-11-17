# agent-routing

<!-- MOVED-HERDR: moved verbatim from the root AGENTS.md (Herdr steering, 852 bytes) -->

## Herdr — steering existing terminals

On the owner's explicit request Hermes may read and steer terminals that already exist, through the `herdr` skill
(`skills/herdr/SKILL.md`): `hc ls|read|get`, `hc send`, `hc interrupt`, `hc wait` (herdr-core is the launchd service
`com.jkrumm.herdr-core` on the mini). **Starting agent work is not part of it** — that is the `fleet` skill
(`factory signal file`). Safety rules are the only gate (guidance, not command guards): never `hc server stop|restart`,
`hc update` or `hc machine update` (one core serves every agent), never `hc send --force` (a `blocked` agent needs the
owner), never `hc attach`. Hermes runs outside any terminal, so every `hc read|get|wait|interrupt` takes an explicit
target; `hc read` is plain text (no `jq`); the terminal tool's 180 s timeout means `hc wait` stays below ~150 s.
