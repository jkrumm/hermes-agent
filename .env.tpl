# Hermes Agent — secrets template
# Resolved via: op run --account tkrumm --env-file=.env.tpl -- hermes gateway start
# Copy to ~/.hermes/.env.tpl on Mac Mini

# Slack (create app via manifest: hermes/slack-app-manifest.json)
SLACK_BOT_TOKEN=op://hermes/slack/bot-token
SLACK_APP_TOKEN=op://hermes/slack/app-token
SLACK_ALLOWED_USERS=op://hermes/slack/allowed-user-id
# Channel IDs — fill after creating channels (Settings > Copy Channel ID)
SLACK_CHANNEL_HERMES=op://hermes/slack/channel-hermes
SLACK_HOME_CHANNEL=op://hermes/slack/channel-hermes
SLACK_CHANNEL_INBOX=op://hermes/slack/channel-inbox

# Anthropic — fallback LLM
ANTHROPIC_API_KEY=op://common/anthropic/API_KEY
ANTHROPIC_BASE_URL=op://common/anthropic/BASE_URL

# Google AI Studio — vision only (Anthropic endpoint doesn't support images)
GEMINI_API_KEY=op://hermes/google-ai-studio/api-key

# Tavily — web search, extract, crawl (replaces browser-based search)
TAVILY_API_KEY=op://hermes/tavily/API_KEY

# Voice — dummy key for OpenAI-compatible TTS/STT on M2 Max (Tailscale handles auth)
VOICE_TOOLS_OPENAI_KEY=not-needed

# GitHub — issue creation, repo queries (watchdog, Phase 3)
GITHUB_TOKEN=op://hermes/github/token

# Homelab API — single integration layer for TickTick, Gmail, Calendar, Docker, UptimeKuma, Slack
# Replaces separate MCP servers for Phase 1 + Phase 3. Base URL: https://api.jkrumm.com
HOMELAB_API_KEY=op://common/api/SECRET
