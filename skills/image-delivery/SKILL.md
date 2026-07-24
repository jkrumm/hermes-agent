---
name: image-delivery
description: Persist and share an image Hermes has received (Slack upload) or generated, via `imgcli` — private image-share by default (durable homelab copy + admin URL), public CDN only when Johannes explicitly wants a shareable public link, or a friend-shareable token link for an image already in the private layer. Use when an image needs a durable home or a URL to hand out.
version: 1.0.0
metadata:
  hermes:
    tags: [image, images, photo, picture, screenshot, share, publish, upload, cdn, link, url, imgcli, image-share]
    related_skills: [capture, argo-api]
---

# Image delivery

Slack images land in `~/.hermes/image_cache` with nowhere to go — it's a cache, not
storage (excluded from the nightly backup). This skill gives them a durable home via
`imgcli`, the CLI for the personal image stack (private image-share layer + public CDN).

**Tool:** `imgcli` (should be on PATH; fall back to the absolute path if not found:
`/Users/jkrumm/SourceRoot/dotfiles/skills/img/scripts/imgcli`). Always pass `--json`.
Secrets resolve inside `imgcli` via `secrets-run` — Hermes never handles or passes a key.

## When to use this

- A Slack image arrived and Johannes wants it kept, filed, or handed to someone → **share**.
- Johannes explicitly asks for a public link / CDN URL / something embeddable in a note or
  article → **publish**.
- Johannes wants to send an already-shared image to a friend → **link**.
- The image is genuinely sensitive (personal documents, anything he wouldn't want on a
  server) → do neither. Leave it local in `image_cache` and say so.

## Default: private, not public

**Private by default.** `share` is the default verb for "keep this" / "save this
picture" — it never leaves the private homelab layer. Only reach for `publish` when
Johannes says so explicitly ("make this public", "give me a CDN link", "I want to embed
this"). Don't publish just because an image was generated or looks shareable — ask if
unsure whether he wants it public.

## Commands

```bash
imgcli share   <file> --json                  # private — durable homelab copy
imgcli publish <file> [prefix/] --json        # private, then public CDN (default prefix: gen/)
imgcli link    <imageId> --json                # friend-shareable token URL for a shared image
```

### share — private, the default

```bash
imgcli share ~/.hermes/image_cache/photo.png --json
# → {"id","root","relPath","adminFileUrl"}
```

Ingests into image-share's private root. Returns an `id` (needed later for `link`) and
an admin file URL — not something to hand to a third party, just Johannes's own durable
reference.

### publish — explicit public ask only

```bash
imgcli publish ~/.hermes/image_cache/photo.png --json
# → {"id","key","cdnUrl","markdown","renditions":{...}}
```

Stages through the private layer, then pushes to the public CDN (unsigned URL — anything
here is effectively public). Defaults to the `gen/` prefix. Returns `cdnUrl` plus a ready
`![]()` markdown embed — reuse that verbatim rather than hand-building a URL.

### link — share an already-private image with a friend

```bash
imgcli link <imageId> --json
# → a token-role share-page URL, safe to hand to someone without making the image public
```

Use this when Johannes wants to send a specific person a link to something already
`share`d, without promoting it to the public CDN.

## Notes

- **Sensitive images get neither.** If in doubt, ask before running either command —
  once published, the CDN URL is unsigned and effectively public forever.
- **Don't guess intent from format.** A screenshot of a chat, a generated illustration
  for a blog post, and a personal photo all get treated by what Johannes says he wants
  to do with it, not by what kind of image it is.
- Full command reference (`upload`, `sync`, transforms, prefixes) lives in the `img`
  skill in `dotfiles` — this skill only covers the three verbs Hermes needs.
