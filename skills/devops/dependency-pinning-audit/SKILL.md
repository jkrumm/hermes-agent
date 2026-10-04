---
name: dependency-pinning-audit
description: Use when auditing or pinning JS dependency specifiers.
version: 1.0.0
metadata:
  hermes:
    tags: [dependencies, lockfile, bun, npm, manifests, pinning, supply-chain, peer-ranges]
    related_skills: [change-plan-audit, defect-report-verification, github-issues]
---

# Dependency pinning audit — the lockfile is the ground truth

For any question shaped "are this repo's dependency specifiers correct", "pin the
deps", "why is `<pkg>` on a dist-tag a problem", "did the patch change my deps":
the manifests state intent, the **lockfile states what actually installs**, and
the two disagree more often than not. Every claim in a report about dependencies
must be resolved against the lockfile and the installed tree, never against the
manifest alone.

`change-plan-audit` owns *is a written plan's inventory complete*; this skill owns
the dependency-specific technique both use.

## Procedure

1. **Enumerate every manifest, excluding `node_modules` and `.git`.** A monorepo
   hides offenders in app/package workspaces that a root-only read misses.

   ```python
   import json, subprocess
   files = subprocess.run(['bash','-lc',
       "find . -name package.json -not -path '*/node_modules/*' -not -path './.git/*' | sort"],
       capture_output=True, text=True).stdout.split()
   for f in files:
       d = json.load(open(f))
       for k in ('dependencies', 'devDependencies'):
           for n, v in (d.get(k) or {}).items():
               if v in ('latest','beta','next') or v.startswith(('^','~')):
                   print(f, k, n, v)
   ```

2. **Resolve every target against the lockfile's resolved map.** For `bun.lock`
   (lockfileVersion 1) the `workspaces` map holds declared specifiers and the
   `packages` map holds resolved entries:

   ```python
   import re
   lock = open('bun.lock').read()
   resolved = set(re.findall(r'"%s": \["%s@([^"]+)"' % (re.escape(pkg), re.escape(pkg)), lock))
   ```

   - target in `resolved` → text-only row; with `--frozen-lockfile` CI it is a
     no-op at install time.
   - target **not** in `resolved` → either the one row that changes the resolved
     tree (the only one that can break a build) or an invented version. Say which,
     and check `node_modules/<pkg>/package.json`'s `version` to see what the
     lockfile actually produced.

3. **Test a floating specifier against its consumers' peer ranges.** This is what
   turns "untidy specifier" into an active defect: a dist-tag re-resolves with no
   review and can walk past a compatibility boundary.

   ```python
   for m in re.finditer(r'"(@?[\w/-]+)": \["\1@([^"]+)", "", \{([^}]*)\}\]', lock):
       pkg, ver, meta = m.groups()
       pr = re.search(r'"typescript": "([^"]+)"', meta)   # or whichever peer matters
       if pr: print(pkg, ver, '-> peer typescript', pr.group(1))
   ```

   A resolved prerelease major outside a `>=x <y` peer range is a real finding —
   name the peer packages and their ranges, not just the version.

4. **Classify the severity honestly.** CI running `bun install --frozen-lockfile`
   throughout means floating specifiers are a *local* re-resolution risk, not a
   build-reproducibility defect. A repo-level `.bunfig.toml` is usually absent, so
   a `minimumReleaseAge` cooldown only applies on machines that configure it
   globally. Reports routinely overstate this — correct the severity claim.

5. **Look for the duplicate-copy signal.** Two workspaces declaring
   non-overlapping ranges for one package make the installer keep two copies
   (a second resolved entry keyed by the workspace-qualified name). Pinning the
   root into the other's range is what lets the tree dedupe — a concrete,
   checkable benefit worth naming.

6. **Verify the change by installing, not by reading.** The acceptance test is a
   plain (non-frozen) install followed by a lockfile diff: unchanged means the
   pins were text-only, changed means they must be committed with the manifests.

## Pitfalls

- **Never report `workspace:*` or `peerDependencies` as offenders.** A workspace
  protocol reference is internal, not a registry version; a peer range exists to
  express compatibility for whatever host consumes the package, and pinning one
  defeats its purpose by forcing every consumer onto a single patch version. A
  plan that pins peers is wrong in the other direction — call it out.
- **A version that appears nowhere in the lockfile is not automatically wrong.**
  It may be the deliberate downgrade to a stable release that satisfies a peer
  range. Distinguish "changes the resolved tree on purpose" from "invented" by
  checking whether the target is a published version and whether the current
  resolution is a prerelease of a higher major.
- **A removed package can still sit in a written plan.** Manifests move between
  the plan being written and the audit; diff both directions and report the row
  as stale rather than silently dropping it.
- **`bun run X --cwd Y` recurses infinitely** in package.json scripts — use
  `bun run --filter @pkg X` when a verification step needs to target a workspace.
- **Read the lockfile with python, not the `sqlite3`/`jq` habit.** It is JSONC-ish
  text; a regex over the resolved map is more robust than trying to parse it as
  strict JSON.
