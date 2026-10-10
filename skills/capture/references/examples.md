# Capture examples

**"Remind me to renew the Tailscale cert next month"**
→ TickTick `🏠Personal`, dueDate = today + 30d.

**"I need to fix the slack patch breaking on long threads"**
→ GitHub `hermes-agent` (concrete code change to an upstream patch under `patches/`).

**"Buy oat milk"**
→ TickTick `📦Shopping`, dueDate = today + 7d (vague urgency).

**"EP-1234 — finish the enrolment form validation"**
→ TickTick `💼Work` (IU ticket → never GitHub).

**"The morning briefing prompt could be tighter"**
→ GitHub `hermes-agent` (concrete code change to `cron/morning-briefing.prompt.txt`).

**"Cancel the Spotify family subscription"**
→ TickTick `🏠Personal`, dueDate = today + 7d.

**"Refactor BasaltUI Button to use the new tokens"**
→ GitHub `basalt-ui` (concrete refactor a coding agent can execute).

**"Checkout imgproxy and Backblaze for image hosting"**
→ TickTick `😇Dev` (or `🏠Personal` if Dev project not used) — *research* + *evaluation* is human work, not coding-agent work, even though the topic is technical. dueDate = today + 14d (typical research lead time).

**"Look into the morning briefing prompt — it's getting long"** (also: "Look at the morning briefing")
→ TickTick `🏠Personal`, dueDate = today + 7d — *look into* = exploration, not a code change. (If after reviewing the user wants to *trim* it, that follow-up becomes a GitHub `hermes-agent` issue.)

**"Compare Tailscale vs Cloudflare Tunnel for the homelab"**
→ TickTick `🏛HomeLab` (or `🏠Personal`) — comparison + decision is human judgment.

**"Evaluate moving from Postgres to SQLite for the small VPS apps"**
→ TickTick `😇Dev` — evaluation/decision, dueDate = today + 14d.

**"Doctor's appointment Thursday at 3pm"**
→ TickTick `🏠Personal`, dueDate = next Thursday. (Calendar events are a separate concern — capture only stores the reminder.)

**"Release v0.4 of basalt-ui"**
→ TickTick `🏠Personal`, dueDate = today + 3d. ("Release X" = pressing publish, human action.)

**"Add OG tags to jkrumm.dev"**
→ GitHub `jkrumm.dev` (concrete code addition).
