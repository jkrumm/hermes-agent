---
name: headless-secrets
description: Use when verifying or changing a secret on this estate.
version: 1.0.0
metadata:
  hermes:
    tags: [secrets, 1password, dotfiles, cache, verification, mini, macbook]
    related_skills: [human-queue, hermes-gateway]
---

# Headless secrets — the refs → seed → cache → app chain

Use this skill whenever a secret is added, rotated, migrated, or suspected stale
on this estate, and whenever a queue request or a commit claims a secret change
was done. The point of the skill is that **a secret change is only verified by
reading it back through the path the apps use** — never by a refs list, a seed
exit code, or someone else's resolution note.

## The two backends

Which one is live is decided by `~/.config/secrets/backend`:

- **`op` (MacBook)** — live 1Password, biometric prompt, a human is present.
- **`cache` (mini)** — `~/.local/bin/secrets-run` reads the age-encrypted
  `cache/secrets.enc.json` in `dotfiles-private`. No prompt, no network, no `op`
  call, works headless.

`secrets-run` is a drop-in `op` shim — same interface, same `op://` refs, only
the backend differs. That is exactly why a meaningful check has to run on **both**
sides: the MacBook proves what 1Password holds, the mini proves what the apps can
actually resolve.

## The chain, in order

1. **Refs** — `dotfiles-private/headless.refs` (personal account) and
   `headless.iu.refs` (IU account). These are the *allowlist*: a ref that is not
   listed never reaches the cache, whatever 1Password holds.
2. **Seed** — `make -C ~/SourceRoot/dotfiles secrets-seed` on the MacBook
   (biometric). Writes `dotfiles-private/cache/secrets.enc.json`.
3. **Cache** — the mini resolves from that file offline via `secrets-run`.
4. **App** — every consumer (`~/.hermes/.env.tpl`, repo `.env.tpl` files) goes
   through the same shim, so the shim is the correct place to test.

## Verify a change

Read back through the shim, and check the mtime of `secrets.enc.json` to see when
it was last sealed:

```bash
OP_ACCOUNT=<account> ~/.local/bin/secrets-run read "op://<vault>/<item>/<field>"
```

**`OP_ACCOUNT` selects the account whose key decrypts the ref, and the default is
wrong for IU refs.** `secrets-run` defaults to the personal `tkrumm` account; a ref
from `headless.iu.refs` needs `OP_ACCOUNT=careerpartner`, mirroring the
`op --account` the same caller passes on the MacBook. A `MISS` without the account
set is **not** a failed seed — re-run with `OP_ACCOUNT` before concluding anything.

To prove the cache is *current* rather than merely present, compare it against live
1Password on the MacBook. Compare **hashes, never plaintext**:

```bash
printf %s "$(<reader> read "op://<vault>/<item>/<field>")" | shasum -a 256 | cut -c1-12
```

Equal prefixes on both sides = the cache carries the live value. A secret value
must never appear in a chat transcript, a log, or a command that echoes it.

## Pitfalls

- **A ref listed in `headless*.refs` proves nothing about whether it sealed.** The
  list is the input, the encrypted cache is the output, and only a read-back
  through `secrets-run` shows the output. Check the output.
- **A resolution note is a claim by whoever wrote it, not evidence.** A queue
  entry or a commit message saying a reseal happened is the hypothesis; the
  read-back is the test. Report the read-back, and say plainly when the work was
  done by someone else rather than by you.
- **The seed fails closed on a missing item.** Keep the old refs alongside their
  replacements until the consuming branch is merged, then drop them — removing a
  ref early makes the seed refuse rather than warn.
- **Never print a secret value.** Verify by hash, by length, or by exit status.
- **Watch the shell when looping over `"field_a field_b"` pairs.** A
  `for p in "a b" "c d"; do set -- $p; …` loop is **not** word-split under `zsh`
  (no `SH_WORD_SPLIT`), so it silently compares the whole string as one field and
  prints a bogus `ok`. Run verification loops in `bash`, or pass a real array.
- **Never write a plaintext `~/.hermes/.env`.** `.env.tpl` is the one list of
  refs; a stray CLI that persists env values duplicates refs on the same `op://`
  source and is deliberately excluded from backup. Fix the ref list instead.
