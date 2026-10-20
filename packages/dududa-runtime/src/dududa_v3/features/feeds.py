"""AI news feeds: 橘鸦AI早报 overview, OpenAI/Anthropic official blog and podcast updates, optional daily push."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .base import (
    Command,
    Ctx,
    FeatureError,
    Job,
    JobCtx,
    Registry,
    Reply,
    Task,
    Tool,
    Toolkit,
)

FEATURE = "feeds"
SHANGHAI = ZoneInfo("Asia/Shanghai")
JUYA_FEED = "https://daily.juya.uk/rss.xml"
JUYA_HOME = "https://daily.juya.uk/"
JUYA_REFRESH_SECONDS = 600
UPDATES_TTL_SECONDS = 900
OVERVIEW_LIMIT = 1500
SUMMARY_CHARS = 60
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

COMPANY_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic"}
KIND_LABELS = {"blog": "官方博客", "podcast": "播客/视频"}
SOURCES = {
    ("openai", "blog"): ("rss", "https://openai.com/news/rss.xml", "https://openai.com/news/"),
    ("anthropic", "blog"): ("anthropic_news", "https://www.anthropic.com/news", "https://www.anthropic.com/news"),
    # The OpenAI Podcast (acast feed, resolved from Apple Podcasts id 1820330260).
    ("openai", "podcast"): ("rss", "https://feeds.acast.com/public/shows/68470ba8d911dedd6501609c",
                            "https://openai.com/podcast/"),
    # Anthropic has no official podcast feed; its YouTube channel carries the talk/interview series.
    ("anthropic", "podcast"): ("rss", "https://www.youtube.com/feeds/videos.xml?channel_id=UCrDwWp7EBBv4NwvScIpBDOA",
                               "https://www.youtube.com/@anthropic-ai"),
}
TRACKING_PARAMS = re.compile(r"^(utm_\w+|ref|ref_src|source|fbclid|gclid|mc_cid|mc_eid|si)$", re.IGNORECASE)


# ---------------------------------------------------------------- generic helpers


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def clean_link(url: str) -> str:
    """Drop tracking query parameters and fragments; keep meaningful ones (e.g. YouTube ``v``)."""
    parts = urlsplit((url or "").strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not TRACKING_PARAMS.match(k)])
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def to_date(value: str) -> str:
    """RFC 822 / ISO 8601 / ``Oct 15, 2026`` → ``YYYY-MM-DD`` (empty when unparseable)."""
    value = (value or "").strip()
    if not value:
        return ""
    for parse in (parsedate_to_datetime, lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
                  lambda v: datetime.strptime(v, "%b %d, %Y"),  # noqa: DTZ007 -- date-only value
                  lambda v: datetime.strptime(v, "%B %d, %Y")):  # noqa: DTZ007 -- date-only value
        try:
            return parse(value).strftime("%Y-%m-%d")
        except (TypeError, ValueError, IndexError):
            continue
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else ""


def parse_feed(body: bytes | str) -> list[dict]:
    """RSS 2.0 or Atom → ``[{"title","link","date","summary"}]`` in document order."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise FeatureError("订阅源格式解析失败") from error
    items = []
    for item in root.iter("item"):
        items.append({"title": strip_html(item.findtext("title") or ""),
                      "link": clean_link(item.findtext("link") or item.findtext("guid") or ""),
                      "date": to_date(item.findtext("pubDate") or item.findtext(
                          "{http://purl.org/dc/elements/1.1/}date") or ""),
                      "summary": strip_html(item.findtext("description") or "")})
    for entry in root.iter(ATOM_NS + "entry"):
        link = ""
        for node in entry.findall(ATOM_NS + "link"):
            if node.get("rel", "alternate") == "alternate":
                link = node.get("href", "")
                break
        items.append({"title": strip_html(entry.findtext(ATOM_NS + "title") or ""),
                      "link": clean_link(link),
                      "date": to_date(entry.findtext(ATOM_NS + "published") or entry.findtext(
                          ATOM_NS + "updated") or ""),
                      "summary": strip_html(entry.findtext(ATOM_NS + "summary") or "")})
    return [item for item in items if item["title"]]


class _AnthropicNewsParser(HTMLParser):
    """Collects ``<a href="/news/...">`` cards with their ``<time>`` and title text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self.card: dict | None = None
        self.nested = 0
        self.field = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        values = dict(attrs)
        if tag == "a":
            href = values.get("href") or ""
            if self.card is None and re.match(r"^(https://www\.anthropic\.com)?/news/[\w-]+/?$", href):
                self.card = {"href": href, "time": "", "title": "", "heading": "", "text": []}
                self.nested = 0
            elif self.card is not None:
                self.nested += 1
            return
        if self.card is None:
            return
        cls = values.get("class") or ""
        if tag == "time":
            self.field = "time"
        elif tag in ("h1", "h2", "h3", "h4"):
            self.field = "heading"
        elif "title" in cls.lower():
            self.field = "title"
        else:
            self.field = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.card is not None:
            if self.nested:
                self.nested -= 1
            else:
                self.items.append(self.card)
                self.card = None
        elif tag in ("time", "h1", "h2", "h3", "h4", "span", "div", "p"):
            self.field = ""

    def handle_data(self, data: str) -> None:
        if self.card is None or not data.strip():
            return
        if self.field in ("time", "title", "heading") and not self.card[self.field]:
            self.card[self.field] = data.strip()
        self.card["text"].append(data.strip())


def parse_anthropic_news(html: str) -> list[dict]:
    parser = _AnthropicNewsParser()
    parser.feed(html)
    seen, items = set(), []
    for card in parser.items:
        link = clean_link(urljoin("https://www.anthropic.com/", card["href"]))
        title = card["title"] or card["heading"] or (card["text"][0] if card["text"] else "")
        if not title or link in seen:
            continue
        seen.add(link)
        items.append({"title": title, "link": link, "date": to_date(card["time"]), "summary": ""})
    items.sort(key=lambda item: item["date"], reverse=True)   # stable: undated cards keep page order at the end
    return items


def parse_company(text: str) -> str | None:
    word = (text or "").strip().lower()
    if word.startswith("o"):
        return "openai"
    if word.startswith(("a", "claude")):
        return "anthropic"
    return None


# ---------------------------------------------------------------- 橘鸦AI早报


class _JuyaParser(HTMLParser):
    """Flattens the issue HTML into blocks: ``{"tag", "text", "num"}``."""

    BLOCKS = ("h1", "h2", "h3", "li", "blockquote", "p")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.current: dict | None = None
        self.code: list[str] | None = None

    def _flush(self) -> None:
        if self.current is not None:
            text = re.sub(r"\s+", " ", "".join(self.current["parts"])).replace("↗", "").strip()
            self.blocks.append({"tag": self.current["tag"], "text": text, "num": self.current["num"]})
            self.current = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "hr":
            self._flush()
            self.blocks.append({"tag": "hr", "text": "", "num": None})
        elif tag in self.BLOCKS:
            if tag == "p" and self.current is not None and self.current["tag"] in ("blockquote", "li"):
                return
            self._flush()
            self.current = {"tag": tag, "parts": [], "num": None}
        elif tag == "code":
            self.code = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self.code is not None:
            text = "".join(self.code).strip()
            self.code = None
            if self.current is not None:
                number = re.fullmatch(r"#(\d+)", text)
                if number:
                    self.current["num"] = int(number.group(1))
                else:
                    self.current["parts"].append(text)
        elif self.current is not None and tag == self.current["tag"]:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.code is not None:
            self.code.append(data)
        elif self.current is not None:
            self.current["parts"].append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def one_line(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = text.strip()
    sentence = re.split(r"(?<=[。！？!?；;])", text, maxsplit=1)[0].strip()
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip("，,、 ") + "…"


def parse_juya_issue(html: str) -> list[dict]:
    """Issue HTML → ``[{"num", "category", "title", "summary"}]`` (overview order)."""
    parser = _JuyaParser()
    parser.feed(html)
    parser.close()
    blocks = parser.blocks
    items: list[dict] = []
    summaries: dict[int, str] = {}
    titles: dict[int, str] = {}
    phase, category, pending = "", "", None
    for block in blocks:
        tag, text, num = block["tag"], block["text"], block["num"]
        if tag == "h2":
            phase = "overview" if text == "概览" else "details"
            continue
        if tag == "hr":
            phase = "details" if phase == "overview" else phase
            continue
        if phase == "overview":
            if tag == "h3":
                category = text
            elif tag == "li" and text:
                items.append({"num": num, "category": category, "title": text, "summary": ""})
        elif tag == "h3" and num is not None:
            pending = num
            titles[num] = text
        elif tag == "blockquote" and pending is not None:
            summaries.setdefault(pending, one_line(text))
            pending = None
    if not items:   # Older layout without an overview list: fall back to the detail headings.
        items = [{"num": num, "category": "", "title": title, "summary": ""} for num, title in titles.items()]
    for item in items:
        item["summary"] = summaries.get(item["num"], "")
    return items


def parse_juya_feed(body: bytes) -> list[dict]:
    """RSS → ``[{"date", "link", "items"}]`` newest first."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise FeatureError("橘鸦早报订阅源解析失败") from error
    issues = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        date = re.search(r"\d{4}-\d{2}-\d{2}", title) or re.search(r"\d{4}-\d{2}-\d{2}", item.findtext("link") or "")
        if not date:
            continue
        html = item.findtext(CONTENT_NS) or item.findtext("description") or ""
        issues.append({"date": date.group(0), "link": clean_link(item.findtext("link") or JUYA_HOME),
                       "items": parse_juya_issue(html)})
    issues.sort(key=lambda issue: issue["date"], reverse=True)
    return issues


def _render_items(items: list[dict], budget: int, summarize) -> tuple[list[str], int]:
    lines, category, used, shown = [], None, 0, 0
    for index, item in enumerate(items, 1):
        block = []
        if item["category"] and item["category"] != category:
            block.append(f"◆ {item['category']}")
        entry = f"{item['num'] or index}. {item['title']}"
        if summarize(item) and item["summary"] and item["summary"] not in item["title"]:
            entry += f"\n   {item['summary']}"
        block.append(entry)
        cost = sum(len(line) + 1 for line in block)
        if used + cost > budget:
            break
        lines += block
        used += cost
        shown += 1
        category = item["category"] or category
    return lines, shown


def format_issue(issue: dict, today: str, limit: int = OVERVIEW_LIMIT) -> str:
    """Titles with one-line summaries; long issues keep summaries only for the lead section."""
    head = [f"【橘鸦AI早报 {issue['date']}】"]
    if issue["date"] != today:
        head.insert(0, f"今天（{today}）的早报还没出哦，先看最近一期～")
    tail = f"原文：{issue['link']}"
    items = issue["items"]
    budget = limit - sum(len(line) + 1 for line in head) - len(tail) - 20
    lead = items[0]["category"] if items else ""
    for summarize in (lambda item: True, lambda item: item["category"] == lead, lambda item: False):
        lines, shown = _render_items(items, budget, summarize)
        if shown == len(items):
            break
    if not items:
        lines.append("（这期没解析出条目，直接看原文吧）")
    elif shown < len(items):
        lines.append(f"……另有 {len(items) - shown} 条，见原文")
    return "\n".join([*head, *lines, tail])


def shanghai_today() -> str:
    return datetime.now(SHANGHAI).strftime("%Y-%m-%d")


async def juya_issue(ctx: Toolkit, *, force: bool = False) -> dict:
    """Today's issue if cached, otherwise the newest one (feed re-fetched at most every 10 min)."""
    today = shanghai_today()
    cached = ctx.kv_get(FEATURE, f"juya:{today}")
    if cached:
        return cached
    latest = ctx.kv_get(FEATURE, "juya:latest") or {}
    if not force and latest and time.time() - latest.get("fetched_at", 0) < JUYA_REFRESH_SECONDS:
        issue = ctx.kv_get(FEATURE, f"juya:{latest['date']}")
        if issue:
            return issue
    try:
        body, _, _ = await ctx.fetch(JUYA_FEED, timeout=25)
        issues = parse_juya_feed(body)
    except FeatureError:
        issue = ctx.kv_get(FEATURE, f"juya:{latest['date']}") if latest else None
        if issue:
            return issue
        raise
    if not issues:
        raise FeatureError("橘鸦早报订阅源里没有找到任何一期")
    issue = issues[0]
    ctx.kv_set(FEATURE, f"juya:{issue['date']}", issue)
    ctx.kv_set(FEATURE, "juya:latest", {"date": issue["date"], "fetched_at": time.time()})
    return issue


# ---------------------------------------------------------------- official updates


async def official_items(ctx: Toolkit, company: str, kind: str, limit: int = 5) -> list[dict]:
    key = f"updates:{company}:{kind}"
    cached = ctx.kv_get(FEATURE, key)
    if cached and time.time() - cached.get("at", 0) < UPDATES_TTL_SECONDS:
        return cached["items"][:limit]
    parser, url, _ = SOURCES[(company, kind)]
    body, _, _ = await ctx.fetch(url, timeout=25)
    items = parse_anthropic_news(body.decode("utf-8", "replace")) if parser == "anthropic_news" else parse_feed(body)
    items = [item for item in items if "youtube.com/shorts/" not in item["link"]]   # Shorts aren't episodes.
    if not items:
        raise FeatureError(f"{COMPANY_LABELS[company]} {KIND_LABELS[kind]}暂时没解析到内容")
    items = items[:10]
    ctx.kv_set(FEATURE, key, {"at": time.time(), "items": items})
    return items[:limit]


def format_updates(company: str, kind: str, items: list[dict]) -> str:
    lines = [f"【{COMPANY_LABELS[company]} {KIND_LABELS[kind]} · 最新 {len(items)} 条】"]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item['title']}" + (f"（{item['date']}）" if item["date"] else ""))
        lines.append(f"   {item['link']}")
    lines.append(f"来源：{SOURCES[(company, kind)][2]}")
    return "\n".join(lines)


def updates_command(kind: str):
    async def handler(ctx: Ctx) -> str:
        company = parse_company(ctx.args.split()[0]) if ctx.args.split() else None
        name = "博客" if kind == "blog" else "播客"
        if company is None:
            return (f"用法：{name} <公司>，公司可写 OpenAI / Anthropic，也可简写 O/、A/（O 开头算 OpenAI，A 开头算 Anthropic）。\n"
                    f"例如：嘟嘟哒 {name} OpenAI")
        return format_updates(company, kind, await official_items(ctx, company, kind))
    return handler


# ---------------------------------------------------------------- commands, tools and push job


async def news_command(ctx: Ctx) -> str:
    return format_issue(await juya_issue(ctx), shanghai_today())


async def ai_news_tool(ctx: Ctx, args: dict) -> dict:
    issue = await juya_issue(ctx)
    today = shanghai_today()
    return {"ok": True, "today": today, "issue_date": issue["date"], "is_today": issue["date"] == today,
            "overview": format_issue(issue, today)}


async def official_updates_tool(ctx: Ctx, args: dict) -> dict:
    company = parse_company(str(args.get("company") or ""))
    kind = str(args.get("kind") or "blog").lower()
    if company is None or kind not in KIND_LABELS:
        raise ValueError("company 需为 openai|anthropic，kind 需为 blog|podcast")
    items = await official_items(ctx, company, kind)
    return {"ok": True, "company": COMPANY_LABELS[company], "kind": kind, "items": items,
            "source": SOURCES[(company, kind)][2]}


async def news_push_job(ctx: JobCtx) -> None:
    config = ctx.config(FEATURE)
    targets = [str(scope) for scope in config.get("push_targets") or [] if "/" in str(scope)]
    if not targets:
        return
    now = datetime.now(SHANGHAI)
    today = now.strftime("%Y-%m-%d")
    if now.hour < int(config.get("push_hour", 9)) or ctx.kv_get(FEATURE, f"pushed:{today}"):
        return
    issue = await juya_issue(ctx)
    if issue["date"] != today:
        return   # Not out yet; retry on the next tick.
    text = format_issue(issue, today)
    for scope in targets:
        ctx.push(scope, Reply.of_text(text), dedupe=f"feeds:juya:{today}@{scope}")
    ctx.kv_set(FEATURE, f"pushed:{today}", {"at": time.time(), "targets": targets})


def register(registry: Registry) -> None:
    registry.task(Task("news_push", "AI早报推送", "每天定时把橘鸦AI早报概览推送到配置的群", aliases=("早报推送",),
                       default=False))
    registry.command(Command(("新闻", "news", "早报"), news_command, "新闻 / 早报：今天的橘鸦AI早报概览"))
    registry.command(Command(("博客", "blog"), updates_command("blog"),
                             "博客 <OpenAI|Anthropic|O/|A/>：官方博客最新 5 条"))
    registry.command(Command(("播客", "podcast"), updates_command("podcast"),
                             "播客 <OpenAI|Anthropic|O/|A/>：官方播客/视频最新 5 期"))
    registry.tool(Tool("ai_news_today",
                       "获取今天的橘鸦AI早报（中文 AI 行业新闻日报）概览：标题与一句话摘要、原文链接。"
                       "用户问今天/最近有什么 AI 新闻时使用。",
                       {"type": "object", "properties": {}, "additionalProperties": False}, ai_news_tool))
    registry.tool(Tool("official_updates",
                       "获取 OpenAI 或 Anthropic 官方博客（news）或播客/视频的最新 5 条（标题、日期、链接）。",
                       {"type": "object",
                        "properties": {"company": {"type": "string", "enum": ["openai", "anthropic"]},
                                       "kind": {"type": "string", "enum": ["blog", "podcast"]}},
                        "required": ["company", "kind"], "additionalProperties": False},
                       official_updates_tool))
    registry.job(Job("news_push", 300, news_push_job, initial_delay_seconds=60))
