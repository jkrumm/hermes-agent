# Content extraction from social media links

When the user sends a social media link (Instagram, TikTok, etc.) as part of a capture — they're asking for the *thing referenced by the link*, not the link itself. Extract the actual content before writing the TickTick/GitHub item.

## Instagram specifically

Instagram aggressively blocks non-logged-in access:
- **Cookie consent dialog**: click "Optionale Cookies ablehnen" to dismiss. Content may still be partially visible.
- **Login popup**: appears after dismissing cookies. Click X to close — limited content visible.
- **Carousel navigation**: clicking through slides in a carousel often triggers the login wall. Individual slide images are rarely accessible.

### Extraction strategy (escalation)

1. **Read the visible caption** from the page snapshot. Instagram captions appear below the image and often contain the recipe name, key parameter hints, and hashtags.
2. **Web search** for the recipe/entity name + domain keywords (e.g., `"Cuban Classic Negative" fujifilm recipe settings`). The canonical source is almost always indexed.
3. **Extract from canonical source** — `web_extract` the top result. For Fujifilm recipes, `filmsimrecipes.com` is the canonical database and search hits it reliably.
4. **Fill TickTick content** with the full structured parameters, not just a link. The user wants the recipe *in the task*, not a URL to open later.

### Fujifilm recipes specifically

- Canonical source: `filmsimrecipes.com`
- Search pattern: `"<recipe name>" fujifilm recipe settings`
- TickTick `content` field: include all parameters as a structured reference (Film Simulation, Grain, Color Chrome, WB, Tone Curve, Color, Sharpness, NR, ISO, Clarity). Include source credit and URL.
- Routing: TickTick `🏠Personal` (personal interest, not code, not work)
- Due date: +7d from capture (standard no-urgency default)

## General pattern for any gated social media content

1. Snapshot → extract entity name / key identifiers
2. Web search → find un-gated canonical source
3. Extract full content from canonical source
4. Capture to TickTick with content inline, not just a link
