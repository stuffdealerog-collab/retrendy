---
description: Collect current trend signals for a creative brief from key-free sources (Google Trends daily RSS, Wikipedia most-read, Hacker News, public Telegram channels via the trend-sources MCP server), optional keyed sources (YouTube, TikTok/Instagram via Apify) and web search, with cached-snapshot and evergreen fallbacks. Preloaded into the trend-analyst agent. Use directly when the user asks what is trending around a topic, market or platform, or wants a trend scan before ideation.
argument-hint: "[topic, market or platform] [geo]"
---

# Trend radar

Goal: 8-15 **signals** that are fresh, evidenced and relevant to the brief,
labelled by velocity, plus a record of which sources worked. A signal is an
observation with evidence ("searches for X rose; three outlets covered it this
week"), not an opinion ("people love authenticity").

If invoked directly by the user: run the procedure, present the signals as a
table (signal, evidence, source, velocity), then offer to run `insight` or the
full `/create`. Skip the block.

## Sources, in order of preference

1. **trend-sources MCP server** (tools named `mcp__plugin_creative-studio_trend-sources__*`):
   call `sources_status` first.
   - `google_trends_daily(geo)`: what spiked in searches today, per country.
     Use the brief's market; if unknown, use 2-3 large markets.
   - `wikipedia_top(project)`: what people read yesterday. Use the brief's
     language edition (`ru.wikipedia`, `en.wikipedia`, …).
   - `hackernews_top`: tech and internet culture.
   - `telegram_channel(channel)`: public channels only, read-only. Use channels
     the brief or brand file names; never guess private ones.
   - `youtube_trending(region, category_id)`, `social_search(platform, query)`:
     only if `sources_status` says configured. Without keys they answer "not
     configured"; that is normal, move on.
2. **Web search / fetch**: always use it for the domain's seed queries
   (`domains/<domain>/domain.md`, section "Trend angles") and to verify or
   enrich MCP signals. Prefer sources from the last 30 days; note dates.
3. **Cached snapshots**: if live sources fail, read the newest files in
   `<state dir>/trend-snapshots/` (Glob `*.json`, file names start with the date)
   that are younger than 14 days and match the domain. Mode = `cached`.
4. **Evergreen**: if nothing is available, derive signals from durable
   cultural tensions relevant to the brief (and say so). Mode = `evergreen`.

Never invent numbers, dates or sources. "Unknown" is a valid value.

## Procedure

1. From the brief: market/geo, language, audience, domain. Write 3-6 search
   queries specific to them (domain seed queries + the brief's subject).
2. Pull raw signals: MCP tools first (fast, factual), then web search.
3. Filter: drop items irrelevant to the brief's audience or domain (sports
   scores, celebrity deaths) unless they reveal a usable mood or vocabulary.
4. Cluster duplicates; for each cluster write one signal with the strongest
   evidence and its source.
5. Label velocity: `rising` (new, growing), `peaking` (everywhere now, will
   be a cliché soon: a warning, not an invitation), `fading`.
6. Mark the 2-3 signals that are **peaking** explicitly: generators should
   avoid riding them directly; counter-trends often live next to them.

## Output (as part of the trend-analyst's `cs:trends` block)

`mode`, `sources` (each with a short label, e.g. `google_trends_daily:US`),
`signals[]` with `signal`, `source`, `evidence`, `velocity`, `relevance`.
Insights are added by the `insight` method in the same block. The hook saves
the block as a dated snapshot in `<state dir>/trend-snapshots/` for later
degraded runs.
