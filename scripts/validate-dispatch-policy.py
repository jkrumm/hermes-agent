#!/usr/bin/env python3
"""Validate config/dispatch-repos.json and summarise what it permits.

Called by `make status`. This used to be a python one-liner inside the Makefile, which
was tolerable when the file was a flat repo -> maxTier map and is not now that it is a
policy with four interacting keys. The checks below are the same ones `hermes-cc.sh`
makes at dispatch time, run at setup time instead: `hermes-cc.sh` fails CLOSED on a
malformed policy, which is correct but surfaces the problem mid-incident on the first
dispatch. Catch it while nobody is waiting on an answer.

Exits 0 with a one-line summary, or non-zero with the reason.
"""
from __future__ import annotations

import json
import os
import sys

VALID = ("investigate", "author", "implement")


def fail(msg: str) -> None:
    sys.exit(msg)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/.hermes/config/dispatch-repos.json")
    try:
        with open(path) as f:
            policy = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read {path}: {e}")

    root = os.path.realpath(os.path.expanduser(policy.get("root", "~/SourceRoot")))
    default_tier = policy.get("defaultTier", "investigate")
    deny = set(policy.get("deny") or [])
    tiers = policy.get("tiers") or {}

    if default_tier not in VALID:
        fail(f"unrecognized defaultTier {default_tier!r} (must be one of: {', '.join(VALID)})")

    overrides: dict[str, str] = {}
    for tier, names in tiers.items():
        if tier not in VALID:
            fail(f"unknown tier key {tier!r} in `tiers` (must be one of: {', '.join(VALID)})")
        for n in names:
            if n in overrides:
                fail(f"{n!r} is listed under two tiers ({overrides[n]!r} and {tier!r})")
            overrides[n] = tier

    both = deny & set(overrides)
    if both:
        fail(f"named in both `deny` and `tiers`: {', '.join(sorted(both))}")

    if not os.path.isdir(root):
        fail(f"dispatch root does not exist: {root}")

    # A name written into `tiers` is one somebody deliberately ruled on, so its absence
    # from disk is drift worth reporting — unlike a discovered repo, which is absent
    # simply because it was never cloned. hermes-cc.sh makes the same distinction.
    missing = sorted(
        n for n in overrides
        if not os.path.exists(os.path.join(root, n, ".git"))
    )
    if missing:
        fail(f"`tiers` names repos with no checkout under {root}: {', '.join(missing)}")

    discovered = [
        n for n in sorted(os.listdir(root))
        if not n.startswith(".")
        and n not in deny
        and os.path.exists(os.path.join(root, n, ".git"))
    ]

    counts = {t: 0 for t in VALID}
    for n in discovered:
        counts[overrides.get(n, default_tier)] += 1

    print(
        f"{len(discovered)} repos dispatchable — "
        f"{counts['investigate']} investigate, {counts['author']} author, "
        f"{counts['implement']} implement; {len(deny)} denied"
    )


if __name__ == "__main__":
    main()
