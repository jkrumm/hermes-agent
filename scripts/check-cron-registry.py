#!/usr/bin/env python3
"""Assert docs/scheduled-jobs.md's registry against the live ~/.hermes/cron/jobs.json.

`jobs.json` is gitignored runtime state, so the git-tracked list of what
should be registered is the State-column table (plus the `## Retired`
bullet list) in `docs/scheduled-jobs.md`. This checks both directions:

- a `live` row needs a live job with `enabled: true` and `state != "paused"`
- a `paused (<reason>)` row needs `enabled: false` AND a recorded
  `paused_reason` (a paused job with no reason is a distinct error — `hermes
  cron pause` from the CLI cannot record one)
- a `## Retired` id must have NO live job
- any live job absent from the registry entirely is a ✗, enabled or not
  (that is how the brain drift audit lived for three weeks in jobs.json alone)
- a live job's `prompt` must equal its registry row's `cron/*.prompt.txt`
  (the tracked copy; `hermes cron edit --prompt` is the only way to change it)
- a live job's `provider`/`model` must equal the `pinned` row in its
  `cron/<name>.md` Model line, when that line pins one

Used by `make status` (`Makefile`'s `status` target shells out to this
file); see `tests/test_check_cron_registry.py` for the unit coverage that a
20-line inline `python3 -c` one-liner couldn't have.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROW_RE = re.compile(r"^\| `([0-9a-f]{12})` \|.*\| (live|paused \([^|]*\)) \|$", re.M)
RETIRED_RE = re.compile(r"^- \*\*`([0-9a-f]{12})`", re.M)
PROMPT_RE = re.compile(r"^\| `([0-9a-f]{12})` \|[^\n]*?`(cron/[^`\n]+\.prompt\.txt)`", re.M)
PIN_RE = re.compile(r"^\| Model \| pinned `([^`]*)` / `([^`]*)`", re.M)


def parse_registry(md_text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Return (rows, retired_ids) parsed out of the registry doc.

    `rows` is every `| `id` | ... | live|paused (...) |` table row, in
    document order, as `(id, state)`. `retired_ids` is every id named in a
    `## Retired` bullet (`- **`id`** — ...`).
    """
    rows = ROW_RE.findall(md_text)
    retired = RETIRED_RE.findall(md_text)
    return rows, retired


def parse_prompt_files(md_text: str) -> dict[str, str]:
    """Return {job_id: repo-relative cron/*.prompt.txt} for every row that names one."""
    return {job_id: path for job_id, path in PROMPT_RE.findall(md_text)}


def parse_pin(md_text: str) -> tuple[str, str] | None:
    """Return (provider, model) from a cron/<name>.md `| Model | pinned ... |` line."""
    m = PIN_RE.search(md_text)
    return (m.group(1), m.group(2)) if m else None


def compare_prompts(prompts: dict[str, str], jobs: dict[str, dict]) -> list[str]:
    """`prompts` maps job id -> tracked prompt body; a live job must carry exactly that body."""
    errors: list[str] = []
    for job_id, body in sorted(prompts.items()):
        job = jobs.get(job_id)
        if job is None:
            continue
        if (job.get("prompt") or "").strip() != body.strip():
            errors.append(
                f"live job {job_id} ({job.get('name')}) prompt differs from its tracked "
                "cron/*.prompt.txt — push it with `hermes cron edit --prompt`"
            )
    return errors


def compare_pins(pins: dict[str, tuple[str, str]], jobs: dict[str, dict]) -> list[str]:
    """`pins` maps job id -> (provider, model) recorded in its cron/<name>.md."""
    errors: list[str] = []
    for job_id, (provider, model) in sorted(pins.items()):
        job = jobs.get(job_id)
        if job is None:
            continue
        live = (job.get("provider") or "", job.get("model") or "")
        if live != (provider, model):
            errors.append(
                f"live job {job_id} ({job.get('name')}) is "
                f"{live[0] or 'unpinned'}/{live[1] or 'unpinned'} but cron/*.md pins "
                f"{provider}/{model} — re-pin with `hermes cron edit --provider --model`"
            )
    return errors


def compare(rows: list[tuple[str, str]], retired: list[str], jobs: dict[str, dict]) -> list[str]:
    """Return one error sentence per mismatch; empty means everything matches."""
    errors: list[str] = []

    for job_id, state in rows:
        job = jobs.get(job_id)
        if state == "live":
            if job is None:
                errors.append(
                    f"job {job_id} in docs/scheduled-jobs.md is not registered [hermes cron list]"
                )
            elif not job.get("enabled", True) or job.get("state") == "paused":
                errors.append(
                    f"live job {job_id} ({job.get('name')}) is registered live in "
                    "docs/scheduled-jobs.md but is paused/disabled"
                )
        else:
            if job is None:
                errors.append(
                    f"job {job_id} in docs/scheduled-jobs.md (paused) is not registered "
                    "[hermes cron list]"
                )
            elif job.get("enabled", True):
                errors.append(
                    f"job {job_id} ({job.get('name')}) is still enabled in the live gateway "
                    "but marked paused in docs/scheduled-jobs.md"
                )
            elif not job.get("paused_reason"):
                errors.append(
                    f"job {job_id} ({job.get('name')}) paused with no reason — `hermes cron "
                    "pause` from the CLI cannot record one; pause from chat or document in "
                    "the registry"
                )

    for job_id in retired:
        if job_id in jobs:
            errors.append(
                f"job {job_id} is marked retired in docs/scheduled-jobs.md but still has a "
                "live job [hermes cron list]"
            )

    registered = {job_id for job_id, _ in rows} | set(retired)
    for job_id in sorted(jobs):
        if job_id not in registered:
            errors.append(
                f"live job {job_id} ({jobs[job_id].get('name')}) is not in "
                "docs/scheduled-jobs.md"
            )

    return errors


def _load_jobs(jobs_json_path: str) -> dict[str, dict]:
    if not os.path.exists(jobs_json_path):
        return {}
    with open(jobs_json_path) as f:
        data = json.load(f)
    return {j["id"]: j for j in data.get("jobs", [])}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    md_path = args[0] if len(args) > 0 else os.environ.get("HERMES_SCHEDULED_JOBS_MD")
    jobs_json_path = args[1] if len(args) > 1 else os.environ.get("HERMES_CRON_JOBS_JSON")
    if not md_path or not jobs_json_path:
        print("usage: check-cron-registry.py <scheduled-jobs.md> <cron/jobs.json>", file=sys.stderr)
        return 2

    # A registry MISMATCH is exit 1 with one ✗ line per finding; an inability
    # to compare at all (unreadable file, malformed JSON) is exit 2 with its
    # own ✗ line, so `make status` never has to guess which one it saw.
    try:
        with open(md_path) as f:
            md_text = f.read()
        jobs = _load_jobs(jobs_json_path)
    except (OSError, ValueError) as e:
        print(f"    ✗ cron registry [could not compare jobs.json against docs/scheduled-jobs.md: {e}]")
        return 2

    rows, retired = parse_registry(md_text)
    if not rows and not retired:
        print("    ✗ cron registry [docs/scheduled-jobs.md has no job-id rows]")
        return 1

    errors = compare(rows, retired, jobs)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(md_path)))
    prompts: dict[str, str] = {}
    pins: dict[str, tuple[str, str]] = {}
    for job_id, rel in parse_prompt_files(md_text).items():
        try:
            with open(os.path.join(repo, rel)) as f:
                prompts[job_id] = f.read()
        except OSError:
            errors.append(f"job {job_id} names {rel} in docs/scheduled-jobs.md but the file is missing")
            continue
        pin_path = rel[: -len(".prompt.txt")] + ".md"
        try:
            with open(os.path.join(repo, pin_path)) as f:
                pin = parse_pin(f.read())
        except FileNotFoundError:
            errors.append(f"job {job_id} names {pin_path} (Model pin doc) but it is missing")
            pin = None
        if pin is not None:
            pins[job_id] = pin
    errors += compare_prompts(prompts, jobs)
    errors += compare_pins(pins, jobs)

    if errors:
        for e in errors:
            print(f"    ✗ cron registry: {e}")
        return 1

    live_n = sum(1 for _, state in rows if state == "live")
    paused_n = len(rows) - live_n
    print(
        f"    ✓ cron registry ({live_n} live, {paused_n} paused, {len(retired)} retired — "
        "matches docs/scheduled-jobs.md)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
