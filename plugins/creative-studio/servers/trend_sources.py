#!/usr/bin/env python3
"""Read-only trend sources as a stdio MCP server. Python stdlib only.

No key needed:   google_trends_daily, wikipedia_top, hackernews_top, telegram_channel
Optional keys:   youtube_trending (YOUTUBE_API_KEY), social_search (APIFY_TOKEN)
Status:          sources_status

Keys come from the environment or from `<state dir>/.env` (see .env.example).
A missing key never breaks anything: the tool answers "not configured" and the
trend-analyst falls back to web search or cached snapshots.
Everything is read-only: the server only issues GET requests (and one
read-only Apify actor run when APIFY_TOKEN is set).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import cs_common as cs
except Exception:  # pragma: no cover
    cs = None

PROTOCOL = "2025-06-18"
UA = "Mozilla/5.0 (compatible; creative-studio-trends/0.1; read-only)"
TIMEOUT = 20


def load_dotenv() -> None:
    if cs is None:
        return
    try:
        home = cs.resolve_home()
    except Exception:
        return
    for path in (home / ".env", cs.PLUGIN_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if value and not os.environ.get(key):
                os.environ[key] = value


def http_get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def http_json(url: str, data: dict | None = None) -> object:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Content-Type": "application/json"},
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=120 if body else TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------- sources

def google_trends_daily(geo: str = "US", limit: int = 20) -> dict:
    raw = http_get(f"https://trends.google.com/trending/rss?geo={urllib.parse.quote(geo.upper())}")
    ns = {"ht": "https://trends.google.com/trending/rss"}
    items = []
    for it in ET.fromstring(raw).iter("item"):
        news = [{"title": n.findtext("ht:news_item_title", default="", namespaces=ns),
                 "source": n.findtext("ht:news_item_source", default="", namespaces=ns),
                 "url": n.findtext("ht:news_item_url", default="", namespaces=ns)}
                for n in it.findall("ht:news_item", ns)][:2]
        items.append({"query": it.findtext("title"), "approx_traffic": it.findtext("ht:approx_traffic", namespaces=ns),
                      "published": it.findtext("pubDate"), "news": news})
    return {"source": "Google Trends daily RSS", "geo": geo.upper(), "fetched": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "items": items[: int(limit)]}


SKIP_WIKI = re.compile(r"^(Main_Page|Special:|Wikipedia:|File:|Portal:|Talk:|Help:|Category:|Template:|Служебная:|Заглавная_страница|Википедия:)")


def wikipedia_top(project: str = "en.wikipedia", date: str = "", limit: int = 25) -> dict:
    day = dt.date.fromisoformat(date) if date else dt.date.today() - dt.timedelta(days=1)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/"
           f"{day.year}/{day.month:02d}/{day.day:02d}")
    try:
        data = json.loads(http_get(url))
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not date:  # yesterday not published yet
            return wikipedia_top(project, (day - dt.timedelta(days=1)).isoformat(), limit)
        raise
    arts = [a for a in data["items"][0]["articles"] if not SKIP_WIKI.match(a["article"])]
    return {"source": f"Wikipedia most-read ({project})", "date": day.isoformat(),
            "items": [{"article": a["article"].replace("_", " "), "views": a["views"], "rank": a["rank"]} for a in arts[: int(limit)]]}


def hackernews_top(limit: int = 15) -> dict:
    ids = json.loads(http_get("https://hacker-news.firebaseio.com/v0/topstories.json"))[: int(limit)]
    items = []
    for i in ids:
        it = json.loads(http_get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")) or {}
        items.append({"title": it.get("title"), "score": it.get("score"), "comments": it.get("descendants"), "url": it.get("url")})
    return {"source": "Hacker News top stories", "items": items}


TG_POST = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TG_VIEWS = re.compile(r'<span class="tgme_widget_message_views">([^<]+)</span>')
TG_DATE = re.compile(r'<time datetime="([^"]+)"')


def telegram_channel(channel: str, limit: int = 15) -> dict:
    """Public channels only, via the t.me/s/<channel> web preview (read-only, no login)."""
    name = channel.strip().lstrip("@").split("/")[-1]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", name):
        raise ValueError("channel must be a public channel username, e.g. 'durov'")
    page = http_get(f"https://t.me/s/{name}").decode("utf-8", "replace")
    texts = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<br\s*/?>", "\n", re.sub(r"<(?!br)[^>]+>", "", t)))).strip()
             for t in TG_POST.findall(page)]
    views, dates = TG_VIEWS.findall(page), TG_DATE.findall(page)
    posts = [{"text": t[:600], "views": views[i] if i < len(views) else None, "date": dates[i] if i < len(dates) else None}
             for i, t in enumerate(texts)]
    if not posts:
        return {"source": f"Telegram t.me/s/{name}", "items": [], "note": "no public preview (private channel or preview disabled)"}
    return {"source": f"Telegram t.me/s/{name}", "items": posts[-int(limit):][::-1]}


def youtube_trending(region: str = "US", category_id: str = "", limit: int = 15) -> dict:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return not_configured("youtube_trending", "YOUTUBE_API_KEY")
    q = {"part": "snippet,statistics", "chart": "mostPopular", "regionCode": region.upper(), "maxResults": min(int(limit), 50), "key": key}
    if category_id:
        q["videoCategoryId"] = category_id
    data = json.loads(http_get("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(q)))
    return {"source": "YouTube Data API mostPopular", "region": region.upper(),
            "items": [{"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                       "tags": v["snippet"].get("tags", [])[:8], "views": v.get("statistics", {}).get("viewCount")}
                      for v in data.get("items", [])]}


APIFY_ACTORS = {"tiktok": ("APIFY_TIKTOK_ACTOR", "clockworks~tiktok-scraper"),
                "instagram": ("APIFY_INSTAGRAM_ACTOR", "apify~instagram-hashtag-scraper")}


def social_search(platform: str, query: str, limit: int = 20) -> dict:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return not_configured("social_search", "APIFY_TOKEN")
    platform = platform.lower()
    if platform not in APIFY_ACTORS:
        raise ValueError(f"platform must be one of {sorted(APIFY_ACTORS)}")
    env, default = APIFY_ACTORS[platform]
    actor = os.environ.get(env, default)
    tag = query.lstrip("#")
    payload = ({"hashtags": [tag], "resultsPerPage": int(limit), "shouldDownloadVideos": False} if platform == "tiktok"
               else {"hashtags": [tag], "resultsLimit": int(limit)})
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={urllib.parse.quote(token)}&timeout=110"
    rows = http_json(url, payload)
    keep = ("text", "caption", "desc", "playCount", "likesCount", "diggCount", "commentsCount", "hashtags", "createTimeISO", "timestamp")
    return {"source": f"Apify {actor}", "query": query,
            "items": [{k: r.get(k) for k in keep if r.get(k) is not None} for r in rows[: int(limit)] if isinstance(r, dict)]}


def not_configured(tool: str, var: str) -> dict:
    return {"configured": False, "tool": tool,
            "note": f"{var} is not set. Add it to your environment or to <state dir>/.env (see .env.example). "
                    "Continue with the key-free tools or web search."}


def sources_status() -> dict:
    return {"key_free": ["google_trends_daily", "wikipedia_top", "hackernews_top", "telegram_channel (public channels)"],
            "youtube_trending": bool(os.environ.get("YOUTUBE_API_KEY")),
            "social_search": bool(os.environ.get("APIFY_TOKEN")),
            "not_included": {"reddit": "public JSON endpoints answer 403 without OAuth",
                             "google_trends_explore": "unofficial API, rate-limited (429) without browser cookies"}}


TOOLS = {
    "google_trends_daily": (google_trends_daily, "Today's rising Google searches for a country (RSS, no key).", {
        "geo": {"type": "string", "description": "ISO country code, e.g. US, GB, DE, RU, BR", "default": "US"},
        "limit": {"type": "integer", "default": 20}}),
    "wikipedia_top": (wikipedia_top, "Most-read Wikipedia articles for a day: what people are paying attention to (no key).", {
        "project": {"type": "string", "description": "e.g. en.wikipedia, ru.wikipedia, de.wikipedia", "default": "en.wikipedia"},
        "date": {"type": "string", "description": "YYYY-MM-DD, default yesterday"},
        "limit": {"type": "integer", "default": 25}}),
    "hackernews_top": (hackernews_top, "Top Hacker News stories (tech culture signal, no key).", {
        "limit": {"type": "integer", "default": 15}}),
    "telegram_channel": (telegram_channel, "Latest posts of a PUBLIC Telegram channel via its web preview (read-only, no key).", {
        "channel": {"type": "string", "description": "public channel username, e.g. 'durov'"},
        "limit": {"type": "integer", "default": 15}}),
    "youtube_trending": (youtube_trending, "YouTube most-popular videos for a region (needs YOUTUBE_API_KEY).", {
        "region": {"type": "string", "default": "US"}, "category_id": {"type": "string", "description": "10 = Music"},
        "limit": {"type": "integer", "default": 15}}),
    "social_search": (social_search, "Read-only TikTok / Instagram hashtag scrape via Apify (needs APIFY_TOKEN).", {
        "platform": {"type": "string", "enum": ["tiktok", "instagram"]}, "query": {"type": "string", "description": "hashtag"},
        "limit": {"type": "integer", "default": 20}}),
    "sources_status": (sources_status, "Which trend sources are available in this environment.", {}),
}
REQUIRED = {"telegram_channel": ["channel"], "social_search": ["platform", "query"]}


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "creative-studio-trends", "version": "0.1.0"},
            "instructions": "Read-only trend signals. Call sources_status first; tools that need a key say so instead of failing."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        tools = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": REQUIRED.get(n, [])},
                  "annotations": {"readOnlyHint": True, "openWorldHint": True}}
                 for n, (_, d, props) in TOOLS.items()]
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
    if method == "tools/call":
        params = msg.get("params", {})
        name, arguments = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            result = TOOLS[name][0](**arguments)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}}
        except Exception as exc:  # network errors, bad args: report, don't crash
            return {"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [{"type": "text",
                    "text": f"{name} failed: {type(exc).__name__}: {exc}. Fall back to another source or web search."}]}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    load_dotenv()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
