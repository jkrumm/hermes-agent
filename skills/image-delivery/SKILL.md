---
name: image-delivery
description: Persist and share an image Hermes has received (Slack upload) or generated, via `imgcli` — private by default (durable copy in the bucket's private/ prefix + a time-limited presigned link), public CDN only when Johannes explicitly wants a shareable public link. Use when an image needs a durable home or a URL to hand out.
version: 2.0.0
metadata:
  hermes:
    tags: [image, images, photo, picture, screenshot, share, publish, upload, cdn, link, url, imgcli, private]
---

# Image delivery

Slack images land in `~/.hermes/image_cache` with nowhere to go — it's a cache, not
storage (excluded from the nightly backup). This skill gives them a durable home via
`imgcli`, the CLI for the personal image stack: one B2 bucket with a public CDN prefix
(`img/`) and a private prefix (`private/`, never served by the CDN).

**Tool:** `imgcli` (should be on PATH; fall back to the absolute path if not found:
`/Users/jkrumm/SourceRoot/dotfiles/skills/img/scripts/imgcli`). Always pass `--json`.
Secrets resolve inside `imgcli` via `secrets-run` — Hermes never handles or passes a key.

## Private by default, public only on an explicit ask

`private` is the default verb for "keep this" / "save this picture" / "send this to X" —
the object stays in the private prefix and the returned URL is a presigned link that
expires (default and maximum 7 days). Only reach for `upload` when Johannes says so
explicitly ("make this public", "give me a CDN link", "I want to embed this"). Don't make
an image public just because it was generated or looks shareable — ask if unsure.

**Sensitive images get neither.** Personal documents, anything he wouldn't want on a
server: leave it local in `image_cache` and say so. If in doubt, ask first — a public CDN
URL is unsigned and effectively public forever, and Hermes cannot delete it.

**Don't guess intent from format.** A chat screenshot, a generated blog illustration and a
personal photo are treated by what Johannes says he wants to do with it, not by what kind
of image it is.

## Commands

| Intent | Command | Returns |
|-|-|-|
| Keep it / send someone a link (default) | `imgcli private <file> --json` | `key` + presigned `url` + `expiresAt` — safe to hand out; it stops working after expiry |
| Fresh link for an image already kept | `imgcli private-url <key> --json` | a new presigned `url` |
| Explicit public link / embed | `imgcli upload <file> [prefix/] --json` | `url` (CDN) — default prefix `misc/`, use `gen/` for generated images |
| Generate an image | `imgcli gen "<prompt>" --private --json` | local file + private `key`/`url`; `--public` instead only on an explicit ask |

```bash
imgcli private ~/.hermes/image_cache/photo.png --json
imgcli upload ~/.hermes/image_cache/photo.png gen/ --json
imgcli gen "a minimalist line drawing of a Mac mini on a desk" --private --json
```

`gen` runs `agw image` on the mini. The prompt is data — quote it, never build it from
an untrusted message. Presigned links never go into durable notes — they expire.

Full command reference (`sync`, `ls`, transforms, prefixes) lives in the `img` skill in
`dotfiles`, which Hermes cannot load — this skill covers the verbs Hermes needs.
