---
name: git-binary-diff-forensics
description: Use when a git/GitHub diff shows a file as binary.
version: 1.0.0
metadata:
  hermes:
    tags: [git, github, diff, binary, nul, pr-review, code-quality]
    related_skills: [github-code-review, agent-worktree-verification, defect-report-verification, warden-blocked-items]
---

# A diff that shows a source file as binary

Any of these symptoms is the same defect, and none of them is a tooling problem:

- GitHub's PR file list shows `Binary file not shown.` for a `.ts` / `.py` / `.md` file.
- `gh api repos/<owner>/<repo>/pulls/<n>/files` reports `"additions": 0, "deletions": 0` and no `patch` key for a file that plainly changed.
- `git diff` prints only `Binary files a/x and b/x differ`; `git diff --numstat` marks the file `-  -` instead of two numbers.
- `git show` / `git blame` return nothing useful for a file that exists.
- `git commit` dies with `The argument 'args[N]' must be a string without null bytes`.

**Cause:** git decides "binary" by content sniffing, not by file extension. **One raw NUL byte (0x00) anywhere in the blob makes the whole file binary** to git and to GitHub. The usual source is a deliberate separator written as a literal byte in a string literal instead of an escape sequence.

## Procedure

1. **Confirm and localize the byte.** Never reason from the symptom alone:

   ```bash
   git show <sha>:<path> | python3 -c "import sys;d=sys.stdin.buffer.read();print('bytes',len(d),'NUL',d.count(b'\x00'))"
   python3 -c "
   d=open('<path>','rb').read(); i=d.find(b'\x00')
   print('offset',i,'line',d[:i].count(b'\n')+1); print(repr(d[max(0,i-120):i+120]))"
   ```

   Repo-wide version of step 1, in one shot:

   ```bash
   python3 - <<'PY'
   import subprocess
   files = subprocess.run(['git','ls-files'], capture_output=True, text=True).stdout.split()
   for n in files:
       try: d = open(n,'rb').read()
       except OSError: continue
       if d.count(b'\x00'):
           i = d.find(b'\x00')
           print(f'{n}: {d.count(chr(0).encode())} NUL byte(s), first at line {d[:i].count(chr(10).encode())+1}')
   PY
   ```

2. **Read the diff anyway.** `git diff --text <base> <head> -- <path>` forces git to emit the patch; every downstream inspection works off that output. Piping a blob through `grep` answers `Binary file matches` and shows you nothing useful — use the python read above instead of grep on a blob.

3. **See exactly what GitHub sees:**

   ```bash
   gh api repos/<owner>/<repo>/pulls/<n>/files \
     --jq '.[]|select(.filename=="<path>")|"\(.filename) +\(.additions) -\(.deletions) patch=\(if .patch then "TEXT" else "BINARY" end)"'
   ```

4. **Fix it in the source, not in the tooling.** Replace the raw byte with the language's own escape (`\u0000` in TS/JS/Python strings, `\0` in C). Semantics are identical; the file becomes text again. Do not treat a `.gitattributes` entry as the fix, and do not rewrite history — the byte is what is wrong.

5. **Verify both halves:** step 1 reports `NUL 0`, step 3 reports `patch=TEXT`, and the repo's own test suite still passes (an escape inside a string literal must not change the runtime value).

## Rules that cost time when missed

- **GitHub renders the *pair*, not the file.** If *either* side of a diff contains a NUL, the file shows as binary. A branch that has already escaped the byte therefore still shows `Binary file not shown` while its **base** branch still carries it — a fix branch cannot make its own diff readable. Say this out loud when the owner is being asked to review: the base branch has to carry the fix, or the branch must be rebased onto a base that does.
- **`git blame` and `git log -S` silently skip binary blobs** — no error, empty output. Never read that as "introduced by the most recent commit". Walk the commits and compare blobs directly: `for sha in $(git log --format=%h -N -- <path>); do git show $sha:<path> | …count NULs…; done`.
- **A raw byte vs. an escape is visible in a Python `repr` of the source line.** `b"...}\x00..."` is a literal NUL byte in the file; `b"...}\u0000..."` (double backslash in the repr) is the escape *text* written in the source. Check which form a file actually uses before telling anyone it is fixed.
- **A raw NUL in a commit message kills `git commit`** (`must be a string without null bytes`) *after* the work is done — the episode loses its branch and the diff survives only as a salvage bundle. Never echo a raw byte into a commit message or a shell argument; describe it in words.
- **Judge the blast radius before calling it a blocker.** A binary-rendered file means reviewers cannot read that diff, not that the change is wrong — the merge gate reads changed *paths*, so it still passes. Separate the two claims.

## Report shape

Verdict first: which file, which byte, which line, and what it costs the reader. Then one line for the fix (the escape to use) and one for the verification output. If the fix belongs on a base branch rather than the branch under review, that is the single decision to surface.
