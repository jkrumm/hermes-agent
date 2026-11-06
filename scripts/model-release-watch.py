#!/usr/bin/env python3
"""model-release-watch — deterministic new-model detector.

Polls two key-free, machine-readable sources and prints ONLY what is new since
the last run. Empty stdout = nothing new (the cron job then delivers nothing).

  • OpenRouter  /api/v1/models   — id + created (unix), fastest public availability signal
  • models.dev  /api.json        — per-provider model lists (azure, amazon-bedrock, openai,
                                   anthropic, google, xai, …) incl. release_date

State: ~/.hermes/state/model-release-watch.json  (seen ids only — no LLM, no server)
Log:   ~/.hermes/state/model-release-watch.log   (one line per run)

Output is Markdown (**bold**, [text](url)). Anything printed is also published to the ntfy
topic `models` (a publish failure exits non-zero); empty output publishes nothing.
"""

import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ntfy_notify  # noqa: E402

STATE_DIR = os.path.expanduser("~/.hermes/state")
STATE_FILE = os.path.join(STATE_DIR, "model-release-watch.json")
LOG_FILE = os.path.join(STATE_DIR, "model-release-watch.log")
LOCK_FILE = os.path.join(STATE_DIR, "model-release-watch.lock")

OR_URL = "https://openrouter.ai/api/v1/models"
MD_URL = "https://models.dev/api.json"
TIMEOUT = 30

# First-party / cloud providers worth waking him up for (models.dev keys).
MD_MAJORS = {
    "openai", "anthropic", "google", "google-vertex", "google-vertex-anthropic",
    "azure", "azure-cognitive-services", "amazon-bedrock",
    "deepseek", "alibaba", "moonshotai", "xai", "mistral", "meta",
    "minimax", "cohere", "zhipuai",
}
MD_PROVIDER_LABEL = {
    "azure-cognitive-services": "azure", "google-vertex-anthropic": "vertex",
    "google-vertex": "vertex", "amazon-bedrock": "bedrock",
}

# OpenRouter id prefixes that count as a major cloud lab model.
OR_MAJOR_PREFIXES = ("anthropic/",)   # Claude only — by request

# Claude models are also mirrored on other model lists; keep those, drop the rest.
CLAUDE_PROVIDERS = {
    "anthropic", "amazon-bedrock", "google-vertex", "google-vertex-anthropic",
    "azure", "azure-cognitive-services", "vercel", "openrouter", "google",
}

# Anthropic's own news sitemap: release announcements and "higher limits /
# reset" posts — the only online place that says whether a launch came with a
# limit reset for everyone.
NEWS_SITEMAP = "https://www.anthropic.com/sitemap.xml"
RESET_SLUG_RE = re.compile(r"reset|higher-limits|more-usage|usage-limit|rate-?limit|limits?-increase", re.I)
MODEL_SLUG_RE = re.compile(
    r"^(claude|introducing-claude|announcing-claude|a-claude)"
    r"|-claude-(fable|opus|sonnet|haiku|mythos)|fable|mythos", re.I)
RESET_WINDOW = 14 * 86400          # a reset post this close to a release counts as "mitgekommen"

# X (x.com) refuses unauthenticated reads from this host (403 / 451 on every
# mirror and on the real site), so the fast wire is Google/Bing News RSS: it
# picks up launch coverage and "limit reset" chatter within minutes and needs
# no credentials.
WIRE_FEEDS = [
    ("google", "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
     ['Anthropic Fable', '"Claude Fable" reset OR "limit reset" OR "higher limits"']),
    ("bing", "https://www.bing.com/news/search?q={q}&format=RSS",
     ["Anthropic Claude Fable"]),
]
WIRE_KEEP_DAYS = 7
WIRE_TEXT_RE = re.compile(r"fable|mythos|limit reset|higher limits|resets? (the )?limits?", re.I)
WIRE_RESET_RE = re.compile(
    r"limit reset|higher limits|resets? (the )?(usage |rate )?limits?|usage reset|more usage",
    re.I)
WIRE_MAX_LINES = 4

FAIL_NOTICE_AFTER = 6 * 3600  # at most one "sources down" line per 6h
MAX_LINES = 12


def log(msg):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}\n")
        if os.path.getsize(LOG_FILE) > 400_000:
            with open(LOG_FILE, "rb") as fh:
                lines = fh.readlines()[-2000:]
            with open(LOG_FILE, "wb") as fh:
                fh.writelines(lines)
    except Exception:
        pass


def fetch_json(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "hermes-model-watch/1.0",
                         "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url}: {last}")


def fetch_text(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (hermes-model-watch)",
                              "Accept": "text/html,application/xml"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url}: {last}")


def iso_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def load_state():
    try:
        with open(STATE_FILE) as fh:
            st = json.load(fh)
    except Exception:
        st = {}
    st.setdefault("or", {})
    st.setdefault("md", {})
    st.setdefault("news", {})
    st.setdefault("wire", {})
    st.setdefault("seeded_at", None)
    st.setdefault("fail_notice_at", 0)
    return st


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=0, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%b %d %H:%M UTC")


def norm_key(model_id):
    """Collapse the same model across providers: last path segment, no -free/:free suffix."""
    s = re.split(r"[:@]", model_id.split("/")[-1])[0].lower()
    s = re.sub(r"-free$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def price(v):
    try:
        p = float(v) * 1_000_000
    except Exception:
        return None
    return "free" if p == 0 else f"${p:g}"


def ctx_label(n):
    try:
        n = int(n)
    except Exception:
        return None
    if n <= 0:
        return None
    return f"{round(n / 1000)}k ctx"


def parse_rss(xml):
    """-> [(title, link, pub_ts, source)]"""
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def grab(tag):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>",
                          block, re.S)
            return html.unescape(m.group(1).strip()) if m else ""
        title, link, pub = grab("title"), grab("link"), grab("pubDate")
        src = grab("source")
        ts = 0
        try:
            ts = email.utils.parsedate_to_datetime(pub).timestamp()
        except Exception:
            pass
        if title and link:
            out.append((title, link, ts, src))
    return out


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:90]


def fetch_wire():
    items = []
    for name, tmpl, queries in WIRE_FEEDS:
        for q in queries:
            try:
                xml = fetch_text(tmpl.format(q=urllib.parse.quote(q)))
            except Exception as exc:  # noqa: BLE001
                log(f"wire {name} '{q[:30]}': {exc}")
                continue
            for title, link, ts, src in parse_rss(xml):
                items.append({"feed": name, "title": title, "link": link,
                              "ts": ts, "src": src})
    return items


def parse_sitemap(xml):
    """-> [(url, lastmod)] for /news/ entries."""
    entries = re.findall(
        r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", xml
    )
    return [(u, lm or "") for u, lm in entries if "/news/" in u]


def emit(text):
    """Print the notice (the cron output keeps it) and publish it to ntfy topic `models`."""
    print(text)
    ntfy_notify.publish("models", "Model release watch", text)


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(LOCK_FILE) > 600:
                os.unlink(LOCK_FILE)
                return main()
        except Exception:
            pass
        log("skip: concurrent run")
        return 0
    try:
        return run()
    except ntfy_notify.NtfyError as e:
        log(f"FAIL ntfy publish: {e}")
        print(f"model-release-watch: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            os.unlink(LOCK_FILE)
        except Exception:
            pass


def run():
    st = load_state()
    seeded = st["seeded_at"] is not None
    errors = []
    or_data = md_data = news_data = None

    try:
        or_data = fetch_json(OR_URL)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"openrouter: {exc}")
    try:
        md_data = fetch_json(MD_URL)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"models.dev: {exc}")
    wire_data = fetch_wire()
    try:
        news_data = parse_sitemap(fetch_text(NEWS_SITEMAP))
    except Exception as exc:  # noqa: BLE001
        news_data = None
        errors.append(f"anthropic-news: {exc}")

    if or_data is None and md_data is None and news_data is None:
        log("FAIL both sources: " + " | ".join(errors))
        now = time.time()
        if now - float(st.get("fail_notice_at") or 0) > FAIL_NOTICE_AFTER:
            st["fail_notice_at"] = now
            save_state(st)
            emit("⚠️ **model-watch** — beide Quellen nicht erreichbar (OpenRouter, models.dev). "
                  "Watcher läuft weiter, nächster Versuch in 15 min.")
        return 0

    recs = []          # {ts, display, id, srcs, date, ctx, price}
    seen_or = seen_md = 0

    # --- OpenRouter ---
    if or_data is not None:
        for m in or_data.get("data") or []:
            mid = m.get("id")
            if not mid:
                continue
            seen_or += 1
            created = int(m.get("created") or 0)
            if mid in st["or"]:
                continue
            st["or"][mid] = created
            if not seeded or not mid.startswith(OR_MAJOR_PREFIXES):
                continue
            pricing = m.get("pricing") or {}
            pin, pout = price(pricing.get("prompt")), price(pricing.get("completion"))
            recs.append({
                "ts": created, "display": mid, "id": mid, "srcs": ["OpenRouter"],
                "date": utc(created) if created else None,
                "ctx": ctx_label(m.get("context_length")
                                 or (m.get("top_provider") or {}).get("context_length")),
                "price": (f"{pin or '?'}/{pout or '?'} per M" if (pin or pout) else None),
            })

    # --- models.dev ---
    if md_data is not None and isinstance(md_data, dict):
        for prov, body in md_data.items():
            if prov not in CLAUDE_PROVIDERS:
                continue
            label = MD_PROVIDER_LABEL.get(prov, prov)
            for mid, m in (body.get("models") or {}).items():
                if not mid.lower().startswith("claude"):
                    continue
                key = f"{prov}/{mid}"
                rel = (m.get("release_date") or "")[:10]
                if key in st["md"]:
                    continue
                st["md"][key] = rel
                seen_md += 1
                if not seeded or not rel:
                    continue
                try:
                    rel_ts = datetime.strptime(rel, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc).timestamp()
                except Exception:
                    rel_ts = 0
                if rel_ts and time.time() - rel_ts > 30 * 86400:
                    continue  # backlog when a provider is newly added upstream
                recs.append({"ts": rel_ts, "display": m.get("name") or mid, "id": mid,
                             "srcs": [label], "date": rel,
                             "ctx": ctx_label((m.get("limit") or {}).get("context")),
                             "price": None})

    # --- fast wire (Google/Bing News): launch coverage + reset chatter ---
    new_wire = []
    if wire_data:
        cutoff = time.time() - WIRE_KEEP_DAYS * 86400
        for it in wire_data:
            key = norm_title(it["title"])
            if not key:
                continue
            fresh = key not in st["wire"]
            if fresh:
                st["wire"][key] = it["ts"] or time.time()
            text = f"{it['title']} {it['src']}"
            if WIRE_RESET_RE.search(text):
                st["wire_reset_ts"] = max(float(st.get("wire_reset_ts") or 0), it["ts"] or time.time())
            if not fresh or not seeded:
                continue
            if it["ts"] and it["ts"] < cutoff:
                continue
            if not WIRE_TEXT_RE.search(text):
                continue
            it = dict(it)
            it["is_reset"] = bool(WIRE_RESET_RE.search(text))
            new_wire.append(it)

    # --- Anthropic news: release posts and "reset / higher limits" posts ---
    new_news = []
    reset_news = []
    if news_data is not None:
        for url, lastmod in news_data:
            if url in st["news"]:
                continue
            st["news"][url] = lastmod
            if not seeded:
                continue
            slug = url.rsplit("/", 1)[-1]
            kind = "reset" if RESET_SLUG_RE.search(slug) else (
                "model" if MODEL_SLUG_RE.search(slug) else None)
            if kind:
                new_news.append((iso_ts(lastmod), kind, slug, url, lastmod))
        cutoff = time.time() - RESET_WINDOW
        for url, lastmod in st["news"].items():
            if RESET_SLUG_RE.search(url.rsplit("/", 1)[-1]) and iso_ts(lastmod) >= cutoff:
                reset_news.append((iso_ts(lastmod), url, lastmod))
        reset_news.sort(reverse=True)

    st["seeded_at"] = st["seeded_at"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
    st["fail_notice_at"] = 0
    save_state(st)

    if not seeded:
        log(f"seeded: or={seen_or} md={seen_md} news={len(st['news'])}")
        emit("✅ **Claude-Watch** scharf — Baseline: "
              f"{seen_or} OpenRouter-Modelle, {seen_md} models.dev-Claude-Einträge, "
              f"{len(st['news'])} Anthropic-News-URLs, {len(st['wire'])} Wire-Meldungen. "
              "Meldet neue Claude-Modelle, Reset-/Limit-Posts und Launch-Schlagzeilen, alle 15 min.")
        return 0

    if not recs and not new_news and not new_wire:
        log(f"no change (or={seen_or} md={seen_md} news={len(st['news'])})")
        if errors:
            log("partial: " + " | ".join(errors))
        return 0

    out = []
    cited_reset_url = None
    if recs:
        # merge the same model reported by several sources into one line
        merged = {}
        order = []
        for r in recs:
            k = norm_key(r["id"]) or r["id"]
            if k not in merged:
                merged[k] = {"ts": r["ts"], "display": r["display"], "id": r["id"],
                             "srcs": [], "date": None, "ctx": None, "price": None}
                order.append(k)
            g = merged[k]
            g["ts"] = max(g["ts"], r["ts"])
            for s_ in r["srcs"]:
                if s_ not in g["srcs"]:
                    g["srcs"].append(s_)
            for field in ("date", "ctx", "price"):
                if not g[field] and r.get(field):
                    g[field] = r[field]
            if "OpenRouter" in r["srcs"]:
                g["display"], g["id"] = r["display"], r["id"]

        items = sorted((merged[k] for k in order), key=lambda g: g["ts"], reverse=True)
        items.sort(key=lambda g: 0 if "fable" in g["id"].lower() else 1)  # Fable first
        log(f"NEW {len(items)}: " + " | ".join(g["id"] for g in items)[:400])

        out.append(f"🆕 **Neues Modell** — {utc(time.time())}" if len(items) == 1
                   else f"🆕 **{len(items)} neue Modelle** — {utc(time.time())}")
        out.append("")
        for g in items[:MAX_LINES]:
            parts = [f"_{' + '.join(g['srcs'])}_"]
            parts += [g[f] for f in ("date", "ctx", "price") if g[f]]
            out.append(f"• **{g['display']}** — " + " · ".join(parts))
        if len(items) > MAX_LINES:
            out.append(f"… +{len(items) - MAX_LINES} weitere")

        # does the launch come with a limit reset for everyone?
        # a reset post counts when it lands around the release (2 days before .. now)
        out.append("")
        release_ts = max((g["ts"] for g in items), default=0) or time.time()
        near = [r for r in reset_news if release_ts - 2 * 86400 <= r[0] <= release_ts + 3 * 86400]
        wire_reset_ts = float(st.get("wire_reset_ts") or 0)
        if not near and release_ts - 2 * 86400 <= wire_reset_ts <= release_ts + 3 * 86400:
            out.append("↳ **Reset mitgekommen:** ja — Reset-Meldung im News-Wire "
                       f"({utc(wire_reset_ts)}), siehe unten")
            near = None
        elif near:
            ts, url, lm = max(near)
            cited_reset_url = url
            out.append(f"↳ **Reset mitgekommen:** ja — `{url.rsplit('/', 1)[-1]}` "
                       f"({lm[:10]}) → {url}")
        else:
            out.append("↳ **Reset mitgekommen:** nein — kein Reset-/Higher-Limits-Post "
                       "zum Release (geprüft: anthropic.com/news)")

    if new_news and cited_reset_url:
        new_news = [n for n in new_news if n[3] != cited_reset_url]
    if new_news:
        new_news.sort(key=lambda x: (0 if x[1] == "reset" else 1, -x[0]))
        if out:
            out.append("")
        out.append("📰 **Anthropic-News**")
        for ts, kind, slug, url, lm in new_news[:6]:
            icon = "🎁" if kind == "reset" else "🚀"
            out.append(f"{icon} **{slug}** — {lm[:10]} → {url}")
        if len(new_news) > 6:
            out.append(f"… +{len(new_news) - 6} weitere")
        log("NEWS: " + " | ".join(n[2] for n in new_news)[:300])

    if new_wire:
        new_wire.sort(key=lambda x: (0 if x["is_reset"] else 1, -(x["ts"] or 0)))
        if out:
            out.append("")
        out.append("📡 **News-Wire**")
        for it in new_wire[:WIRE_MAX_LINES]:
            icon = "🎁" if it["is_reset"] else "•"
            src = f"{it['src']}, " if it["src"] else ""
            date = (datetime.fromtimestamp(it["ts"], timezone.utc).strftime("%b %d")
                    if it["ts"] else "?")
            title = it["title"] if len(it["title"]) <= 120 else it["title"][:117] + "…"
            out.append(f"{icon} [**{title}**]({it['link']}) — {src}{date}")
        if len(new_wire) > WIRE_MAX_LINES:
            out.append(f"… +{len(new_wire) - WIRE_MAX_LINES} weitere")
        log("WIRE: " + " | ".join(norm_title(i["title"]) for i in new_wire)[:300])

    if errors:
        out.append("")
        out.append(f"_Teilausfall ({len(errors)}): Details in "
                   "~/.hermes/state/model-release-watch.log_")
    emit("\n".join(out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
