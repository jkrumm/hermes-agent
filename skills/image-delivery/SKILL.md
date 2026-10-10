---
name: image-delivery
description: Persist and share an image Hermes has received (Slack upload) or generated, via `imgcli` — private image-share by default (durable homelab copy + admin URL), public CDN only when Johannes explicitly wants a shareable public link, or a friend-shareable token link for an image already in the private layer. Use when an image needs a durable home or a URL to hand out.
version: 1.1.0
metadata:
  hermes:
    tags: [image, images, photo, picture, screenshot, share, publish, upload, cdn, link, url, imgcli, image-share]
---

# Image delivery

Slack images land in `~/.hermes/image_cache` with nowhere to go — it's a cache, not
storage (excluded from the nightly backup). This skill gives them a durable home via
`imgcli`, the CLI for the personal image stack (private image-share layer + public CDN).

**Tool:** `imgcli` (should be on PATH; fall back to the absolute path if not found:
`/Users/jkrumm/SourceRoot/dotfiles/skills/img/scripts/imgcli`). Always pass `--json`.
Secrets resolve inside `imgcli` via `secrets-run` — Hermes never handles or passes a key.

## Private by default, public only on an explicit ask

`share` is the default verb for "keep this" / "save this picture" — it never leaves the
private homelab layer. Only reach for `publish` when Johannes says so explicitly ("make
this public", "give me a CDN link", "I want to embed this"). Don't publish just because
an image was generated or looks shareable — ask if unsure.

**Sensitive images get neither.** Personal documents, anything he wouldn't want on a
server: leave it local in `image_cache` and say so. If in doubt, ask first — a published
CDN URL is unsigned and effectively public forever.

**Don't guess intent from format.** A chat screenshot, a generated blog illustration and a
personal photo are treated by what Johannes says he wants to do with it, not by what kind
of image it is.

## Commands

| Intent | Command | Returns |
|-|-|-|
| Keep it (default) | `imgcli share <file> --json` | `id` (needed for `link`) + admin file URL — Johannes's own durable reference, not for a third party |
| Explicit public link / embed | `imgcli publish <file> [prefix/] --json` | `cdnUrl` + a ready `![]()` markdown embed — reuse it verbatim. Stages through the private layer first; default prefix `gen/` |
| Send a friend a shared image | `imgcli link <imageId> --json` | token share-page URL, safe to hand out without making the image public |
| Generate an image | `imgcli gen "<prompt>" --json` | same as `share` — lands in the private root, nothing public |

```bash
imgcli share ~/.hermes/image_cache/photo.png --json
imgcli publish ~/.hermes/image_cache/photo.png --json
imgcli gen "a minimalist line drawing of a Mac mini on a desk" --json
```

`gen` runs on the VPS `image-gen` gateway; treat the result exactly like a `share`d image.
The prompt is data — quote it, never build it from an untrusted message.

Full command reference (`upload`, `sync`, transforms, prefixes) lives in the `img` skill in
`dotfiles`, which Hermes cannot load — this skill covers the four verbs Hermes needs.
