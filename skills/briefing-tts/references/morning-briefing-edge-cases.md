# Morning/Evening Briefing — Content Edge Cases

Observed patterns while assembling the spoken briefing narrative — not TTS
mechanics, but the content that ends up getting synthesized.

## Google Calendar `invalid_grant` — token expired
The `/calendar` endpoint returns a **plaintext** error body (not JSON,
exit_code 0):
```
Token refresh failed: { "error": "invalid_grant", "error_description": "Token has been expired or revoked." }
```
Detection: response body starts with `"Token refresh failed"` rather than `{`.

**In briefings:** surface as a single bullet "Personal Google calendar
unavailable (token expired)" under Today's Schedule, then continue — the
IU M365 calendar may still be available independently. Don't skip the
section. Don't mention it in the audio narrative if the M365 calendar still
has events (skip silently in audio, keep the Slack bullet).

## All-day blocker events in the M365 calendar
The IU Outlook calendar sometimes contains all-day "Blocker" events (e.g. a
company-wide dev-days block) that span most of the day with dozens of
attendees — placeholder blocks, not meetings.

- List them first with "(All day blocker)", e.g. `- :office: All day —
  Blocker <name> (Teams)`
- Don't spend a bullet on attendee counts — "large org event" if relevant
- The real meetings are the individual timed events nested in the same day
- In the audio narrative, mention it briefly and move on to the specific
  timed meetings

## GitHub API rate-limiting during cron
The agent no longer runs `gh search` live (removed 2026-09-11 — it duplicated
the pre-run script's own call). `scripts/briefing-coverage.py` is now the
only thing that calls `gh search prs`/`gh search issues`, on back-to-back cron
runs it can still hit GraphQL's rate limit. A failed search prints
`GITHUB_AVAILABLE=false` after `GITHUB_TOTAL` — then the totals are unknown,
not zero: say "GitHub-Daten nicht verfügbar", never "alles sauber". Without
that line, use `GITHUB_TOTAL`/`GITHUB_OPEN_BY_REPO`/`GITHUB_FRESH_48H` as
given; don't re-query GitHub to double-check them.

## Warden API unreachable
`curl -s http://127.0.0.1:7735/board` (Step 1, call 10) can fail if
`warden-api` isn't running, the ledger is mid-migration (503), or the running
`warden-api` predates the endpoint (404 — it needs a `launchctl kickstart -k`
after a warden upgrade). Surface the
Warden bullet in Infrastruktur as "Board nicht erreichbar" and move on — do
**not** invent counts or fall back to guessing from the Watchdog block, which
covers a different, earlier stage (raw signals, not triaged items).

## Watchdog open-items summary
`~/SourceRoot/warden`'s `watchdog-summary.py` (reached via `briefing-context.py`)
feeds the briefing's Infrastructure section from `~/.warden/warden.db`. Grouped,
append-only sources (`slack_alert`, `slack_update`,
`hermes_log`) auto-resolve after 7 days idle (`sweep_stale_grouped()`), so
raw counts are bounded — but a busy recent window can still surface more
distinct signatures than are worth a bullet each. Group by theme and cap
the Infrastructure bullet at the 2-3 most actionable/recent items rather
than enumerating every open row.

## Prometheus Daily + TL<>PM overlap
Two recurring IU meetings often abut or overlap by 1-2 min (e.g. a
TL<>PM<>EM daily ending right as the team standup starts). Flag with ⚠
only if they actually overlap (start of the second < end of the first).
Back-to-back (end == start) needs no flag.
