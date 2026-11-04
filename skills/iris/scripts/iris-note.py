#!/usr/bin/env python3
"""Write an Iris voice memo into the brain Inbox and commit it.

Reproduces Iris's former journal destination (iris server/src/adapters/journal.ts): same folder,
same title and filename rule, same frontmatter. The commit goes through scripts/brain-commit.sh,
which takes brain-sync's mkdir lock (pid file, live holder waits, pidless lock under 60 s waits,
dead or older pidless lock reclaimed) and pushes fail-soft.

Usage:  iris-note.py [--memo <id>] [--dry-run] < memo-text
Prints one JSON line {"ref", "committed", "title"}. Exit 0 ok, 3 lock busy (note written,
NOT committed), 1 failure.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata

BRAIN = os.path.expanduser(os.environ.get("IRIS_NOTE_BRAIN_DIR", "~/SourceRoot/brain"))
COMMIT = os.path.expanduser("~/.hermes/scripts/brain-commit.sh")
TITLE_MAX, SLUG_MAX = 60, 50


def title_of(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    title = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(title) > TITLE_MAX:
        clipped = title[: TITLE_MAX + 1]
        last = clipped.rfind(" ")
        title = clipped[:last] if last > 0 else title[:TITLE_MAX]
    title = re.sub(r"[\s.,;:]+$", "", title)
    return title or "Voice memo"


def slug_of(title: str) -> str:
    s = title.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:SLUG_MAX].rstrip("-")
    return s or "memo"


def memo_of(path: str):
    try:
        head = open(path, encoding="utf-8").read(1024)
    except OSError:
        return None
    fm = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", head)
    m = fm and re.search(r"^memo:\s*(\S+)\s*$", fm.group(1), re.M)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memo", default=os.environ.get("HERMES_SESSION_ID", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    body = sys.stdin.read().strip()
    if not body:
        print("iris-note: empty memo text on stdin", file=sys.stderr)
        return 1

    inbox = os.path.join(BRAIN, "Inbox")
    os.makedirs(inbox, exist_ok=True)
    title = title_of(body)
    name = None
    if args.memo:  # a retry finds its note by the memo: frontmatter and neither rewrites nor re-commits it
        for n in sorted(os.listdir(inbox)):
            if n.endswith(".md") and memo_of(os.path.join(inbox, n)) == args.memo:
                name = n
                break
    if name is None:
        date = datetime.date.today().isoformat()
        base = f"{date}-{slug_of(title)}"
        name = f"{base}.md"
        if os.path.exists(os.path.join(inbox, name)):  # that name belongs to another memo
            name = f"{base}-{(args.memo or str(os.getpid()))[:8]}.md"
        lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}", f"date: {date}",
                 "tags: [journal, iris]", "source: iris"]
        if args.memo:
            lines.append(f"memo: {args.memo}")
        content = "\n".join(lines + ["---", "", body + "\n"])
        if args.dry_run:
            print(f"Inbox/{name}\n{content}")
            return 0
        target = os.path.join(inbox, name)
        tmp = f"{target}.tmp-{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            os.link(tmp, target)  # never overwrites what raced us to the name
        finally:
            os.unlink(tmp)

    ref = f"Inbox/{name}"
    r = subprocess.run([COMMIT, f"journal: {title}", ref], capture_output=True, text=True)
    sys.stderr.write(r.stderr)
    committed = r.returncode == 0 and "committed" in r.stdout
    print(json.dumps({"ref": ref, "committed": committed, "title": title}, ensure_ascii=False))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
