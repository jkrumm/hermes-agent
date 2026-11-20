# Alert liveness forensics

_Use when deciding whether an alert is still live._

An alert message is a **timestamped observation**, never a statement about now. A
digest line, an alert post and an UptimeKuma notification are all history; the
question "is this still true" is answered only by the source that owns the
measurement. Answer it before relaying anything as outstanding work.

This skill owns **what the producer's own state says right now.**

## Procedure

1. **Identify the producer behind the alert text.** The title names it: a bare
   sentence (`🌡️ HomeLab CPU hot`) is the homelab watchdog; a
   bracketed one (`[Gluetun - Docker] [:red_circle: Down] …`) is UptimeKuma; an
   emoji-led one (`🚨 <service> <event> >= 1 (1h)`) is HyperDX. The
   producer, not the channel, holds the live state.
2. **Probe that producer read-only** (recipes below). Two facts are needed and
   they are different: *is the condition true now*, and *when did it last fire
   and clear*. A firing that resolved 40 minutes later is not an open incident.
3. **Check the alert is not already answered.** A `✅`-prefixed recovery message
   in the same channel is the positive pairing; a `200` from the service's own
   URL settles a "new incident" line outright.
4. **Report liveness first, mechanism second.** For each family: still triggered /
   last fired and cleared / answered 200 — then why it reached the surface it
   reached (which filter, which rule, which producer shape).
5. **Never turn a liveness check into a fix.** Restarting a service, clearing a
   flag or pruning storage is a separate decision with its own blast radius;
   name the number (reclaimable GB, disk %, free space) and let the owner call it.

## Recipes

### Host metric alerts — ClickStack and the watchdog

Beszel was removed on 2026-11-19; host metrics are ClickStack alerts (emoji-led, see above) and CPU temperature is the
homelab watchdog's `🌡️ HomeLab CPU hot` / "cool again" pair. Probe the producer, not the message:

- **ClickStack rule:** `AGW_CALLER=hermes agw hdx query clickstack_get_alert` lists every alert with `state`
  (`OK` or alerting); `get_alert {"id"}` adds the recent evaluations, so "did it cross, and is it still over" is one call.
  Recipes and the tile re-run: skill `hyperdx`, and `references/host-metric-alert-triage.md` for the host metrics.
- **Watchdog thermal:** its state dir is root-only; read the live package temperature from the kernel
  (`ssh homelab`, `/sys/class/hwmon/hwmon*/temp1_input`, millidegrees). Hot at a 30 min mean >= 90 °C, cleared below 85 °C.

### Alert posts (UptimeKuma, HyperDX, watchdogs)

Hermes cannot read the alert messages themselves (they go to the ntfy topic `alerts`;
software-factory Issue 259 adds a read). Work from what the owner relays, then probe the producer as above:

- A `✅`-prefixed message is the recovery pairing; its absence is a reason a row
  can sit open, not evidence the service is down.
- For the factory's own view of open problems: `skill_view('fleet')` (`health` + `needs`).

### Public services

One call settles a "new incident" line:
`curl -s -o /dev/null -w '%{http_code}' https://<host>/`.

## Pitfalls

- **A recurring digest line is not a new finding.** A digest that re-selects every
  open row will print the same lines for as long as the rows stay open. A family
  present for a week is a standing defect in the loop that reports it — say that
  once, with the mechanism, instead of re-reporting the lines daily.
- **An un-prefixed producer's alerts all land in the "needs a human look" bucket.**
  A watchdog emitting plain sentences never looks like a structured bot alert,
  however real it is. When a whole family surfaces as unstructured prose, suspect
  the producer's message shape, not the routing policy.
- **Never map an alert to an owner by an opaque numeric monitor id.**
  `uk:<number>` changes when the monitor is recreated; the stable form is derived
  from the title (`Homelab Backup - Push` → `uk:homelab-backup-push`). A rule written
  against the number silently stops matching.
- **A one-shot alert's ledger row keeps the firing timestamp, so an old-looking digest
  line can still be live.** The watchdog's thermal alert fires once on the threshold crossing and
  emits nothing more until it clears, so the event's `last_seen` stays at that moment while the
  condition holds — read the live sensor (or a ClickStack alert's `state`), never the row's age,
  before calling a resource-threshold line stale.
- **A duplicate-heavy rule file is its own finding.** Auto-appended rules are not
  deduplicated, so count *unique* match values as well as entries before reading a
  policy file as a rule set, and report the duplication rather than quietly
  working around it.
