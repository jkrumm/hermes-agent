"""Watchdog poll — runs every 30 min as Hermes cron pre-run.

Polls UptimeKuma, Docker (homelab + vps), GitHub, Slack #alerts/#updates,
and Hermes self-state. Reconciles against ~/.hermes/watchdog.db (SQLite).
Emits NEW=, REMINDERS=, RESOLVED= blocks for the LLM cron prompt.

Source of truth: ~/SourceRoot/claude-local/hermes/scripts/watchdog-poll.py
~/.hermes/scripts/ is itself a symlink to this directory (see make hermes).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "watchdog.db"
STATE_PATH = HERMES_HOME / "scripts" / "briefing-state.json"
JOBS_PATH = HERMES_HOME / "cron" / "jobs.json"

API_BASE = "https://api.jkrumm.com"
GH_OWNER = "jkrumm"

CH_ALERTS = "C0AS1LAUQ3C"
CH_UPDATES = "C0ARZJD824W"

UK_DOWN_GATE_MIN = 30
DOCKER_UNHEALTHY_GATE_MIN = 30
GITHUB_STALE_DAYS = 3

# Slack: a topic must fire at least this many times in a single poll batch to surface.
# Single hits are dropped — user already gets a push notification for those.
SLACK_FLAP_THRESHOLD = 3
SLACK_REEMIT_COOLDOWN_HOURS = 24

REM_HOURS = {
    "uk": 6,
    "docker_homelab": 6,
    "docker_vps": 6,
    "github_pr": 72,
    "github_issue": 168,
    "hermes_cron": 6,
    "hermes_log": 24,
}

HERMES_LOG_FILES = [
    ("hermes_errors_log_offset", "logs/errors.log"),
    ("hermes_gw_error_log_offset", "logs/gateway.error.log"),
]
LOG_LEVEL_RE = re.compile(r"\s(ERROR|CRITICAL)\s")
LOG_PARSE_RE = re.compile(r"^\S+\s+\S+\s+(ERROR|CRITICAL)\s+([\w\.]+)\s*:\s*(.+)$")
LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
LOG_RECENT_HOURS = 6  # log lines older than this are ignored even on first run

QUIET_START_H = 0
QUIET_END_H = 7


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = HERMES_HOME / ".env"
    if not p.exists():
        return env
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def in_quiet_hours(state: dict[str, Any]) -> bool:
    tz_name = state.get("timezone") or "Europe/Berlin"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/Berlin")
    return QUIET_START_H <= dt.datetime.now(tz).hour < QUIET_END_H


def vacation_active(state: dict[str, Any]) -> bool:
    vu = state.get("vacation_until")
    if not vu:
        return False
    try:
        return dt.date.today() <= dt.date.fromisoformat(vu)
    except ValueError:
        return False


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        return {"_error": str(e)}


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    payload_json TEXT,
    first_seen TEXT NOT NULL,
    notified_at TEXT,
    last_reminder_at TEXT,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_events_open ON events(source) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_events_resolved_at ON events(resolved_at);

CREATE TABLE IF NOT EXISTS cursors (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def cursor_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM cursors WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def cursor_set(conn: sqlite3.Connection, key: str, value: str, now_iso: str) -> None:
    conn.execute(
        "INSERT INTO cursors(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now_iso),
    )


def poll_uk(env: dict[str, str]) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {env.get('HOMELAB_API_KEY', '')}"}
    data = http_get(f"{API_BASE}/uptime-kuma/monitors", headers)
    if isinstance(data, dict) and "_error" in data:
        return []
    monitors: list[Any] = []
    if isinstance(data, list):
        monitors = data
    elif isinstance(data, dict):
        monitors = data.get("monitors", []) or []
    out: list[dict[str, Any]] = []
    for m in monitors:
        if not isinstance(m, dict):
            continue
        status = m.get("status")
        is_down = (isinstance(status, str) and status.lower() == "down") or status == 0 or status is False
        if not is_down:
            continue
        mid = str(m.get("id") or m.get("monitorId") or m.get("name") or "")
        if not mid:
            continue
        out.append({
            "external_id": mid,
            "title": m.get("name", "monitor") or "monitor",
            "url": m.get("url") or "",
            "payload": {"type": m.get("type"), "status": status},
        })
    return out


def poll_docker(env: dict[str, str], host: str) -> list[dict[str, Any]]:
    """Parse `/docker/{host}/summary` `alerts` block.

    Shape: `{"alerts": {"unhealthyContainers": [name, ...], "highRestartContainers": [name, ...]}}`
    Each entry may be a string (just the name) or a dict with metadata.
    """
    headers = {"Authorization": f"Bearer {env.get('HOMELAB_API_KEY', '')}"}
    data = http_get(f"{API_BASE}/docker/{host}/summary", headers)
    if isinstance(data, dict) and "_error" in data:
        return []
    out: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return out
    alerts = data.get("alerts") or {}
    if not isinstance(alerts, dict):
        return out

    def _name(item: Any) -> str | None:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return item.get("name") or item.get("container") or item.get("service")
        return None

    for unhealthy in alerts.get("unhealthyContainers", []) or []:
        name = _name(unhealthy)
        if not name:
            continue
        out.append({
            "external_id": f"unhealthy:{name}",
            "title": f"{name} unhealthy ({host})",
            "url": "",
            "payload": {"host": host, "kind": "unhealthy"},
        })
    for restart in alerts.get("highRestartContainers", []) or []:
        name = _name(restart)
        if not name:
            continue
        restarts = restart.get("restarts") if isinstance(restart, dict) else None
        title = f"{name} restart-loop ({host})"
        if restarts:
            title = f"{name} restart-loop ×{restarts} ({host})"
        out.append({
            "external_id": f"restart:{name}",
            "title": title,
            "url": "",
            "payload": {"host": host, "kind": "restart_loop", "restarts": restarts},
        })
    return out


def poll_github(env: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"github_pr": [], "github_issue": []}
    gh_env = os.environ.copy()
    if env.get("GITHUB_TOKEN"):
        gh_env["GITHUB_TOKEN"] = env["GITHUB_TOKEN"]
    threshold = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=GITHUB_STALE_DAYS)

    queries = [
        ("github_pr", "prs", "title,repository,url,number,updatedAt,createdAt,isDraft"),
        ("github_issue", "issues", "title,repository,url,number,updatedAt,createdAt"),
    ]
    for kind, search, fields in queries:
        try:
            res = subprocess.run(
                ["gh", "search", search, "--owner", GH_OWNER, "--state", "open",
                 "--json", fields, "--limit", "50"],
                capture_output=True, text=True, timeout=30, env=gh_env,
            )
            if res.returncode != 0:
                continue
            items = json.loads(res.stdout or "[]")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            continue

        for it in items:
            if it.get("isDraft"):
                continue
            updated = it.get("updatedAt") or it.get("createdAt")
            try:
                dt_updated = dt.datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
            except (ValueError, AttributeError):
                dt_updated = None
            if dt_updated and dt_updated > threshold:
                continue
            repo_obj = it.get("repository") or {}
            repo = repo_obj.get("nameWithOwner") or repo_obj.get("name") or "?"
            num = it.get("number")
            out[kind].append({
                "external_id": f"{repo}#{num}",
                "title": it.get("title", "?"),
                "url": it.get("url", ""),
                "payload": {"repo": repo, "updatedAt": updated},
            })
    return out


def poll_slack_messages(env: dict[str, str], channel_id: str, since_ts: str | None,
                        skip_uk_push: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    headers = {"Authorization": f"Bearer {env.get('HOMELAB_API_KEY', '')}"}
    data = http_get(f"{API_BASE}/slack/channels/{channel_id}/messages?limit=50", headers)
    if isinstance(data, dict) and "_error" in data:
        return [], since_ts
    msgs = data.get("messages", []) if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    latest = since_ts
    for m in msgs:
        ts = m.get("ts", "")
        if not ts:
            continue
        # Always advance the cursor by raw ts, even if filtered out — avoids reprocessing.
        if not latest or ts > latest:
            latest = ts
        if since_ts and ts <= since_ts:
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if "ist dem Channel beigetreten" in text or "added an integration" in text:
            continue
        if skip_uk_push and re.search(r"\[[^\]]+Push\]", text):
            continue
        out.append({
            "external_id": ts,
            "title": text[:240].replace("\n", " "),
            "url": "",
            "payload": {"text": text},
        })
    return out, latest


def poll_hermes_logs(conn: sqlite3.Connection, now: dt.datetime, now_iso: str) -> list[dict[str, Any]]:
    """Tail Hermes error logs since byte cursor. Group by error signature.

    Lines older than LOG_RECENT_HOURS are skipped — guards against history floods
    on first run and after log rotation.
    """
    recency_cutoff = now - dt.timedelta(hours=LOG_RECENT_HOURS)
    # Logs use Europe/Berlin local timestamps without tz; treat them as such.
    log_tz = ZoneInfo("Europe/Berlin")
    sigs: dict[str, dict[str, Any]] = {}
    for cur_key, rel_path in HERMES_LOG_FILES:
        path = HERMES_HOME / rel_path
        if not path.exists():
            continue
        cursor = cursor_get(conn, cur_key)
        try:
            last_offset = int(cursor) if cursor else 0
        except ValueError:
            last_offset = 0
        size = path.stat().st_size
        if last_offset > size:
            last_offset = 0  # log was rotated/truncated
        # On first run (cursor=None), process the entire file so existing
        # error signatures surface. Aggregation + cooldown collapse repeats.
        if last_offset >= size:
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                f.seek(last_offset)
                new_text = f.read()
        except OSError:
            continue
        cursor_set(conn, cur_key, str(size), now_iso)
        for line in new_text.splitlines():
            if not LOG_LEVEL_RE.search(line):
                continue
            ts_m = LOG_TS_RE.match(line)
            if ts_m:
                try:
                    line_dt = dt.datetime.strptime(ts_m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=log_tz)
                    if line_dt < recency_cutoff:
                        continue
                except ValueError:
                    pass
            m = LOG_PARSE_RE.match(line)
            if m:
                level, module, msg = m.group(1), m.group(2), m.group(3)
                sig_text = f"{module}: {msg[:120]}"
            else:
                sig_text = line[:160]
            key = normalize_title(sig_text)
            if not key:
                continue
            g = sigs.setdefault(key, {
                "external_id": key,
                "title": sig_text,
                "url": "",
                "payload": {"first_line": line[:500]},
                "count": 0,
            })
            g["count"] += 1
    return list(sigs.values())


def poll_hermes_cron() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        data = json.loads(JOBS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return out
    for j in data.get("jobs", []):
        if not j.get("enabled", True):
            continue
        status = j.get("last_status")
        if status and status != "ok":
            out.append({
                "external_id": j["id"],
                "title": f"Cron '{j.get('name', j['id'])}' status={status}",
                "url": "",
                "payload": {
                    "error": j.get("last_error"),
                    "last_run_at": j.get("last_run_at"),
                    "next_run_at": j.get("next_run_at"),
                },
            })
    return out


def reconcile(conn: sqlite3.Connection, source: str, observed: list[dict[str, Any]],
              now: dt.datetime, gate_min: int, reminder_h: int | None,
              track_resolution: bool = True) -> tuple[list[dict], list[dict], list[dict]]:
    cur = conn.cursor()
    obs_ids = {o["external_id"] for o in observed}

    for o in observed:
        row = cur.execute(
            "SELECT * FROM events WHERE source=? AND external_id=?",
            (source, o["external_id"]),
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO events(source, external_id, title, url, payload_json, first_seen) "
                "VALUES(?,?,?,?,?,?)",
                (source, o["external_id"], o["title"], o.get("url", ""),
                 json.dumps(o.get("payload", {})), now.isoformat()),
            )
        elif row["resolved_at"] is not None:
            cur.execute(
                "UPDATE events SET resolved_at=NULL, first_seen=?, notified_at=NULL, "
                "last_reminder_at=NULL, reminder_count=0, title=?, url=?, payload_json=? WHERE id=?",
                (now.isoformat(), o["title"], o.get("url", ""),
                 json.dumps(o.get("payload", {})), row["id"]),
            )
        else:
            cur.execute(
                "UPDATE events SET title=?, url=?, payload_json=? WHERE id=?",
                (o["title"], o.get("url", ""), json.dumps(o.get("payload", {})), row["id"]),
            )

    new_events: list[dict] = []
    reminder_events: list[dict] = []
    for row in cur.execute(
        "SELECT * FROM events WHERE source=? AND resolved_at IS NULL", (source,),
    ).fetchall():
        first_seen = dt.datetime.fromisoformat(row["first_seen"])
        age_min = (now - first_seen).total_seconds() / 60
        if age_min < gate_min:
            continue
        if row["notified_at"] is None:
            new_events.append(dict(row))
            cur.execute("UPDATE events SET notified_at=? WHERE id=?", (now.isoformat(), row["id"]))
        elif reminder_h:
            anchor = row["last_reminder_at"] or row["notified_at"]
            if (now - dt.datetime.fromisoformat(anchor)).total_seconds() >= reminder_h * 3600:
                reminder_events.append(dict(row))
                cur.execute(
                    "UPDATE events SET last_reminder_at=?, reminder_count=reminder_count+1 WHERE id=?",
                    (now.isoformat(), row["id"]),
                )

    resolved_events: list[dict] = []
    if track_resolution:
        for row in cur.execute(
            "SELECT * FROM events WHERE source=? AND resolved_at IS NULL", (source,),
        ).fetchall():
            if row["external_id"] not in obs_ids:
                cur.execute(
                    "UPDATE events SET resolved_at=? WHERE id=?", (now.isoformat(), row["id"]),
                )
                if row["notified_at"]:
                    d = dict(row)
                    d["resolved_at"] = now.isoformat()
                    resolved_events.append(d)

    return new_events, reminder_events, resolved_events


_DEDUP_NORMALIZE = re.compile(r"[^a-z0-9]+")


def normalize_title(text: str) -> str:
    return _DEDUP_NORMALIZE.sub("-", text.lower()).strip("-")[:120]


def aggregate_slack_batch(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group raw slack messages by normalized title. Returns list of grouped dicts."""
    groups: dict[str, dict[str, Any]] = {}
    for m in msgs:
        key = normalize_title(m["title"])
        if not key:
            continue
        g = groups.setdefault(key, {
            "external_id": key,
            "title": m["title"],
            "url": "",
            "payload": {"first_text": m["title"], "ts_first": m["external_id"], "ts_last": m["external_id"]},
            "count": 0,
        })
        g["count"] += 1
        ts = m["external_id"]
        if ts > g["payload"]["ts_last"]:
            g["payload"]["ts_last"] = ts
        if ts < g["payload"]["ts_first"]:
            g["payload"]["ts_first"] = ts
    return list(groups.values())


def upsert_grouped(conn: sqlite3.Connection, source: str, groups: list[dict[str, Any]],
                   now: dt.datetime, flap_threshold: int = SLACK_FLAP_THRESHOLD,
                   cooldown_hours: int = SLACK_REEMIT_COOLDOWN_HOURS) -> list[dict]:
    """Upsert by dedup key with batch flap threshold + re-emit cooldown.

    A group surfaces only if (a) count in this batch >= flap_threshold, AND
    (b) we haven't surfaced this dedup key within the cooldown window.
    Always records to the DB so cumulative trends are queryable later.
    """
    cur = conn.cursor()
    out: list[dict] = []
    for g in groups:
        row = cur.execute(
            "SELECT * FROM events WHERE source=? AND external_id=?",
            (source, g["external_id"]),
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO events(source, external_id, title, url, payload_json, first_seen) "
                "VALUES(?,?,?,?,?,?)",
                (source, g["external_id"], g["title"], "",
                 json.dumps({**g["payload"], "batch_count": g["count"]}), now.isoformat()),
            )
            row = cur.execute(
                "SELECT * FROM events WHERE source=? AND external_id=?",
                (source, g["external_id"]),
            ).fetchone()

        last_emit = row["last_reminder_at"] or row["notified_at"]
        cooldown_passed = True
        if last_emit:
            cooldown_passed = (now - dt.datetime.fromisoformat(last_emit)).total_seconds() >= cooldown_hours * 3600

        should_emit = g["count"] >= flap_threshold and cooldown_passed

        if should_emit:
            display_title = f"{g['title']} (×{g['count']} in batch)"
            if row["notified_at"] is None:
                cur.execute(
                    "UPDATE events SET notified_at=?, title=?, payload_json=? WHERE id=?",
                    (now.isoformat(), display_title,
                     json.dumps({**g["payload"], "batch_count": g["count"]}), row["id"]),
                )
            else:
                cur.execute(
                    "UPDATE events SET last_reminder_at=?, reminder_count=reminder_count+1, "
                    "title=?, payload_json=? WHERE id=?",
                    (now.isoformat(), display_title,
                     json.dumps({**g["payload"], "batch_count": g["count"]}), row["id"]),
                )
            out.append({
                "source": source,
                "external_id": g["external_id"],
                "title": display_title,
                "url": "",
                "reminder_count": (row["reminder_count"] or 0) + (1 if row["notified_at"] else 0),
            })
        else:
            # Silent record — bump cumulative count but don't surface
            payload = json.loads(row["payload_json"] or "{}")
            payload["batch_count_last"] = g["count"]
            payload["ts_last"] = g["payload"]["ts_last"]
            cur.execute(
                "UPDATE events SET payload_json=? WHERE id=?",
                (json.dumps(payload), row["id"]),
            )
    return out


def fmt_block(label: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return f"{label}=[]"
    lines = [f"{label}=["]
    for it in items:
        src = it.get("source", "?")
        title = it.get("title", "?")
        url = it.get("url") or ""
        rc = it.get("reminder_count")
        suffix_parts = []
        if url:
            suffix_parts.append(url)
        if rc:
            suffix_parts.append(f"reminder#{rc}")
        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
        lines.append(f"  - [{src}] {title}{suffix}")
    lines.append("]")
    return "\n".join(lines)


def main() -> int:
    env = load_env()
    state = load_state()
    quiet = in_quiet_hours(state)
    vacation = vacation_active(state)
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()

    conn = db_connect()

    all_new: list[dict] = []
    all_rem: list[dict] = []
    all_res: list[dict] = []

    n, r, res = reconcile(conn, "uk", poll_uk(env), now, UK_DOWN_GATE_MIN, REM_HOURS["uk"])
    all_new += n; all_rem += r; all_res += res

    for host in ("homelab", "vps"):
        src = f"docker_{host}"
        n, r, res = reconcile(conn, src, poll_docker(env, host), now,
                              DOCKER_UNHEALTHY_GATE_MIN, REM_HOURS[src])
        all_new += n; all_rem += r; all_res += res

    gh = poll_github(env)
    for kind in ("github_pr", "github_issue"):
        n, r, res = reconcile(conn, kind, gh[kind], now, 0, REM_HOURS[kind])
        all_new += n; all_rem += r; all_res += res

    n, r, res = reconcile(conn, "hermes_cron", poll_hermes_cron(), now, 0, REM_HOURS["hermes_cron"])
    all_new += n; all_rem += r; all_res += res

    log_groups = poll_hermes_logs(conn, now, now_iso)
    if log_groups:
        all_new += upsert_grouped(conn, "hermes_log", log_groups, now,
                                  flap_threshold=1, cooldown_hours=REM_HOURS["hermes_log"])

    for cur_key, ch_id, src, skip_uk in [
        ("slack_alert_ts", CH_ALERTS, "slack_alert", True),
        ("slack_update_ts", CH_UPDATES, "slack_update", False),
    ]:
        since = cursor_get(conn, cur_key)
        msgs, latest = poll_slack_messages(env, ch_id, since, skip_uk_push=skip_uk)
        if since is None:
            # First run — establish watermark, do not emit historical messages
            if latest:
                cursor_set(conn, cur_key, latest, now_iso)
            continue
        if msgs:
            groups = aggregate_slack_batch(msgs)
            all_new += upsert_grouped(conn, src, groups, now)
        if latest and latest != since:
            cursor_set(conn, cur_key, latest, now_iso)

    conn.commit()
    conn.close()

    print(f"QUIET_HOURS={'true' if quiet else 'false'}")
    print(f"VACATION={'true' if vacation else 'false'}")
    print(f"NOW={now_iso}")
    print(fmt_block("NEW", all_new))
    print(fmt_block("REMINDERS", all_rem))
    print(fmt_block("RESOLVED", all_res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
