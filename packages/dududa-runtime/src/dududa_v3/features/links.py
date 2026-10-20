"""Link preview: title, cleaned canonical URL and cover for links posted in chat (no LLM)."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

from .base import (
    Ctx,
    FeatureError,
    Inbound,
    Observer,
    Registry,
    Reply,
    Task,
    sniff_mime,
)

log = logging.getLogger(__name__)

FEATURE = "links"
TASK = "link_preview"
DEDUPE_SECONDS = 600
MAX_LINKS = 3
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PAGE_BYTES = 8 * 1024 * 1024
LINK_TIMEOUT = 30

_URL_CHARS = r"A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%"
URL_RE = re.compile(rf"https?://[{_URL_CHARS}]+")
# Share texts often drop the scheme ("xhslink.com/m/…", "b23.tv/…").
BARE_RE = re.compile(rf"(?<![\w./@-])(?:(?:www|m)\.)?(?:b23\.tv|bili2233\.cn|bilibili\.com|arxiv\.org"
                     rf"|mp\.weixin\.qq\.com|x\.com|twitter\.com|xhslink\.com|xhslink\.cn|xiaohongshu\.com)"
                     rf"/[{_URL_CHARS}]+")

TRACKING_PARAMS = {
    "spm_id_from", "spm", "spmid", "from_spmid", "vd_source", "from", "from_source", "track_code", "igshid",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "ref_url",
}
TRACKING_PREFIXES = ("utm_", "share_", "xsec", "sharer_", "spm_")
# Parameters that only mean tracking on specific sites (``t``/``mid``/``s`` matter elsewhere).
SITE_TRACKING = {
    "bilibili.com": {"bbid", "ts", "unique_k", "plat_id", "timestamp", "buvid", "is_story_h5", "up_id", "seid",
                     "mid", "spmid", "msource", "bsource", "launch_id", "session_id"},
    "b23.tv": {"bbid", "ts", "unique_k", "plat_id", "timestamp", "buvid"},
    "x.com": {"s", "t", "ref_url"},
    "twitter.com": {"s", "t", "ref_url"},
    "youtube.com": {"si", "feature", "pp"},
    "youtu.be": {"si", "feature"},
    "open.spotify.com": {"si", "context"},
    "mp.weixin.qq.com": {"scene", "chksm", "mpshare", "srcid", "clicktime", "enterid", "exportkey", "pass_ticket",
                         "wx_header", "sessionid", "subscene", "ascene", "devicetype", "version", "nettype",
                         "lang", "countrycode", "abtest_cookie", "key", "uin", "poc_token", "realreporttime"},
}
# Hosts handled elsewhere or internal to QQ.
SKIP_SUFFIXES = ("xiaohongshu.com", "xhslink.com", "xhslink.cn", "rednote.com", "qq.com.cn", "qpic.cn",
                 "qlogo.cn", "gtimg.cn", "tenpay.com")
MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".mp4", ".mov", ".mp3", ".m4a", ".flac",
                    ".zip", ".rar", ".7z", ".apk", ".exe", ".dmg", ".iso", ".pdf", ".doc", ".docx", ".xls",
                    ".xlsx", ".ppt", ".pptx", ".tar", ".gz")
TWITTER_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com", "fxtwitter.com", "vxtwitter.com",
                 "fixupx.com", "fixvx.com"}
BILIBILI_SHORT = {"b23.tv", "bili2233.cn"}
ARXIV_ID = r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)"
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s?#&]+)")
# Captcha / bot-wall / error pages are not worth previewing.
BAD_TITLE_RE = re.compile(r"验证码|安全验证|人机验证|环境异常|访问异常|Just a moment|Attention Required|Access Denied"
                          r"|Are you a robot|^(?:403|404|500|502|503)\b|Forbidden|Not Found|^Error$", re.IGNORECASE)
GENERIC_LABELS = {"podcasts.apple.com": "播客", "xiaoyuzhoufm.com": "小宇宙", "nature.com": "Nature",
                  "science.org": "Science", "bilibili.com": "B站", "b23.tv": "B站", "bili2233.cn": "B站",
                  "zhihu.com": "知乎", "github.com": "GitHub",
                  "youtube.com": "YouTube", "youtu.be": "YouTube", "sspai.com": "少数派"}

_recent: dict[str, float] = {}


@dataclass
class Link:
    url: str
    hint_title: str = ""
    hint_desc: str = ""


@dataclass
class Preview:
    label: str
    title: str
    url: str
    lines: list[str] = field(default_factory=list)
    image_url: str | None = None
    image: tuple[bytes, str] | None = None

    @property
    def text(self) -> str:
        return "\n".join([f"【{self.label}】{self.title}", *(line for line in self.lines if line), self.url])


# ---------------------------------------------------------------- URL helpers


def _trim(url: str) -> str:
    url = url.rstrip(".,;:!?'\"]}>")
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1].rstrip(".,;:!?'\"")
    return url


def find_urls(text: str) -> list[str]:
    """Explicit http(s) URLs plus scheme-less share links of well-known hosts, in order."""
    found: list[tuple[int, str]] = []
    for match in URL_RE.finditer(text or ""):
        found.append((match.start(), _trim(match.group(0))))
    rest = URL_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    for match in BARE_RE.finditer(rest):
        found.append((match.start(), "https://" + _trim(match.group(0))))
    result: list[str] = []
    for _, url in sorted(found):
        if url not in result and urlsplit(url).hostname:
            result.append(url)
    return result


def message_links(inbound: Inbound) -> list[Link]:
    """Links from QQ cards (with their titles as hints) and from the message text."""
    links: list[Link] = []
    seen: set[str] = set()

    def add(url: str, title: str = "", desc: str = "") -> None:
        key = clean_url(url)
        if key not in seen:
            seen.add(key)
            links.append(Link(url, title.strip(), desc.strip()))

    for segment in inbound.segments:
        if segment.get("type") == "light_app" and isinstance(segment.get("url"), str):
            urls = find_urls(segment["url"])
            if urls:
                add(urls[0], str(segment.get("title") or ""), str(segment.get("description") or ""))
    texts = [inbound.text] + [s.get("text", "") for s in inbound.segments if s.get("type") == "text"]
    for text in texts:
        for url in find_urls(text if isinstance(text, str) else ""):
            add(url)
    return links


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def host_matches(host: str, *suffixes: str) -> bool:
    return any(host == item or host.endswith("." + item) for item in suffixes)


def clean_url(url: str) -> str:
    """Drop tracking parameters and share fragments; keep everything meaningful."""
    parts = urlsplit(url)
    host = host_of(url)
    site = set().union(*(params for suffix, params in SITE_TRACKING.items() if host_matches(host, suffix)))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS and k.lower() not in site
             and not k.lower().startswith(TRACKING_PREFIXES)]
    fragment = "" if parts.fragment in ("rd", "wechat_redirect") or parts.fragment.startswith(":~:") \
        else parts.fragment
    path = parts.path
    if path.endswith("/") and path.count("/") > 1:
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query, quote_via=quote),
                       fragment))


def should_skip(url: str) -> bool:
    host = host_of(url)
    if not host or host_matches(host, *SKIP_SUFFIXES):
        return True
    if host_matches(host, "qq.com") and not host_matches(host, "mp.weixin.qq.com"):
        return True
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return True
    return _is_internal_ip(host)


def _is_internal_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # Narrow on purpose: fake-IP proxies hand out 198.18.0.0/15 for ordinary foreign hosts.
    internal = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
    return (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast
            or any(ip in ipaddress.ip_network(net) for net in internal))


async def _resolves_internal(host: str) -> bool:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False  # The proxy may still resolve it.
    return any(_is_internal_ip(str(info[4][0])) for info in infos)


def _recent_hit(conversation_id: str, key: str, now: float, window: float) -> bool:
    """True if ``key`` was seen in this conversation within ``window``; otherwise remember it."""
    for stale in [k for k, at in _recent.items() if now - at > window]:
        del _recent[stale]
    full = f"{conversation_id}|{key}"
    if full in _recent:
        return True
    _recent[full] = now
    return False


# ---------------------------------------------------------------- HTML helpers


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.canonical = ""
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key and values.get("content", "").strip():
                self.meta.setdefault(key, []).append(values["content"].strip())
        elif tag == "link" and "canonical" in values.get("rel", "").lower() and values.get("href"):
            self.canonical = self.canonical or values["href"]
        elif tag == "title" and not self.title:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


@dataclass
class PageMeta:
    meta: dict[str, list[str]]
    title: str
    canonical: str

    def first(self, *keys: str) -> str:
        for key in keys:
            for value in self.meta.get(key, []):
                if value.strip():
                    return _squash(value)
        return ""

    def all(self, key: str) -> list[str]:
        return [_squash(value) for value in self.meta.get(key, []) if value.strip()]


def decode_html(body: bytes, content_type: str = "") -> str:
    charset = ""
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.IGNORECASE)
    if match:
        charset = match.group(1) if isinstance(match.group(1), str) else match.group(1).decode("ascii", "ignore")
    for candidate in (charset, "utf-8", "gb18030"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def parse_meta(page: str) -> PageMeta:
    end = page.lower().find("</head>")
    parser = _HeadParser()
    parser.feed(page[:end] if end > 0 else page[:400_000])
    return PageMeta(parser.meta, _squash(parser.title), parser.canonical)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _cut(text: str, limit: int) -> str:
    text = _squash(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def first_sentence(text: str, limit: int = 160) -> str:
    text = _squash(text)
    match = re.search(r"^(.+?[.!?。！？])(?:\s|$)", text)
    return _cut(match.group(1) if match else text, limit)


def short_authors(names: list[str], limit: int = 3) -> str:
    names = [n for n in (_squash(n) for n in names) if n]
    # "Family, Given" (citation meta) → "Given Family" so the comma-joined list stays readable.
    names = [f"{m.group(2)} {m.group(1)}" if (m := re.fullmatch(r"([^,]+),\s*([^,]+)", n)) else n for n in names]
    if len(names) > limit:
        return ", ".join(names[:limit]) + " et al."
    return ", ".join(names)


def human_count(value: object) -> str:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value or "")
    if number >= 100_000_000:
        return f"{number / 100_000_000:.1f}亿".replace(".0亿", "亿")
    if number >= 10_000:
        return f"{number / 10_000:.1f}万".replace(".0万", "万")
    return str(number)


def human_duration(seconds: object) -> str:
    try:
        total = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _date(ts: object) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _js_unescape(text: str) -> str:
    text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return _squash(text.replace("\\'", "'").replace('\\"', '"').replace("\\/", "/"))


# ---------------------------------------------------------------- parsers (pure)


def bilibili_video_id(url: str) -> tuple[str, str] | None:
    """("bvid", "BV…") or ("aid", "123") from a bilibili video URL."""
    parts = urlsplit(url)
    if not host_matches(host_of(url), "bilibili.com"):
        return None
    match = re.search(r"/video/(BV[0-9A-Za-z]{10})", parts.path) or re.search(r"(?:^|&)bvid=(BV[0-9A-Za-z]{10})",
                                                                               parts.query)
    if match:
        return "bvid", match.group(1)
    match = re.search(r"/video/av(\d+)", parts.path, re.IGNORECASE) or re.search(r"(?:^|&)aid=(\d+)", parts.query)
    return ("aid", match.group(1)) if match else None


def parse_bilibili_view(data: dict, url: str) -> Preview | None:
    if not isinstance(data, dict) or data.get("code") != 0 or not isinstance(data.get("data"), dict):
        return None
    video = data["data"]
    page = dict(parse_qsl(urlsplit(url).query)).get("p", "")
    canonical = f"https://www.bilibili.com/video/{video.get('bvid')}" + (f"?p={page}" if page not in ("", "1") else "")
    owner = (video.get("owner") or {}).get("name", "")
    stats = video.get("stat") or {}
    meta = " · ".join(item for item in (
        f"UP主 {owner}" if owner else "", human_duration(video.get("duration")),
        f"{human_count(stats.get('view'))}播放" if stats.get("view") is not None else "") if item)
    pic = video.get("pic") or ""
    if pic.startswith("//"):
        pic = "https:" + pic
    return Preview("B站", _cut(video.get("title", ""), 80), canonical, [meta],
                   image_url=(pic + "@640w_400h_1c.jpg") if pic else None)


def bilibili_space_mid(url: str) -> str | None:
    host, path = host_of(url), urlsplit(url).path
    match = re.match(r"/(\d+)", path) if host == "space.bilibili.com" else \
        re.match(r"/space/(\d+)", path) if host_matches(host, "bilibili.com") else None
    return match.group(1) if match else None


def parse_bilibili_card(data: dict, mid: str) -> Preview | None:
    card = ((data.get("data") or {}).get("card") or {}) if isinstance(data, dict) and data.get("code") == 0 else {}
    if not card.get("name"):
        return None
    fans = card.get("fans")
    line = " · ".join(item for item in (f"粉丝 {human_count(fans)}" if fans is not None else "",
                                        _cut(card.get("sign") or "", 60)) if item)
    face = card.get("face") or ""
    return Preview("B站", f"UP主 {card['name']}", f"https://space.bilibili.com/{mid}", [line],
                   image_url=(face + "@240w_240h_1c.jpg") if face.startswith("http") else None)


def parse_wechat(page: str, url: str) -> Preview | None:
    meta = parse_meta(page)

    def var(*patterns: str) -> str:
        for pattern in patterns:
            match = re.search(pattern, page)
            if match and match.group(1).strip():
                return _js_unescape(match.group(1))
        return ""

    title = var(r"var msg_title = '((?:[^'\\]|\\.)*)'", r'var msg_title = "((?:[^"\\]|\\.)*)"',
                r"msg_title\s*[:=]\s*'((?:[^'\\]|\\.)*)'") or meta.first("og:title", "twitter:title")
    if not title or BAD_TITLE_RE.search(title):
        return None
    nickname = var(r'var nickname = htmlDecode\("((?:[^"\\]|\\.)*)"\)', r"var nickname = \"((?:[^\"\\]|\\.)*)\"",
                   r"nick_name\s*:\s*'((?:[^'\\]|\\.)*)'",
                   r'<strong class="profile_nickname"[^>]*>\s*([^<]+?)\s*</strong>')
    published = _date(var(r'var ct = "(\d+)"', r"\bct\s*=\s*'(\d+)'"))
    cover = var(r'msg_cdn_url = "([^"]+)"', r"msg_cdn_url = '([^']+)'") or meta.first("og:image", "twitter:image")
    desc = var(r'msg_desc = htmlDecode\("((?:[^"\\]|\\.)*)"\)') or meta.first("og:description", "description")
    line = " · ".join(item for item in (nickname, published) if item)
    return Preview("公众号", _cut(title, 80), wechat_canonical(url), [line, _cut(desc, 80)],
                   image_url=cover or None)


def wechat_canonical(url: str) -> str:
    parts = urlsplit(url)
    if parts.path.startswith("/s/"):
        return f"https://mp.weixin.qq.com{parts.path}"
    keep = [(k, v) for k, v in parse_qsl(parts.query) if k in ("__biz", "mid", "idx", "sn")]
    return f"https://mp.weixin.qq.com{parts.path}?{urlencode(keep)}" if keep else clean_url(url)


def twitter_status(url: str) -> str | None:
    if host_of(url) not in TWITTER_HOSTS:
        return None
    match = re.match(r"/(?:[A-Za-z0-9_]{1,15}|i(?:/web)?)/status(?:es)?/(\d+)", urlsplit(url).path)
    return match.group(1) if match else None


def parse_fxtwitter(data: dict) -> Preview | None:
    tweet = data.get("tweet") if isinstance(data, dict) else None
    if not isinstance(tweet, dict) or not tweet.get("id"):
        return None
    author = tweet.get("author") or {}
    screen = author.get("screen_name") or "i"
    media = tweet.get("media") or {}
    photos = media.get("photos") or []
    videos = media.get("videos") or []
    image = None
    if photos:
        image = photos[0].get("url")
        if image and "pbs.twimg.com/media/" in image and "?" not in image:
            image += "?name=small"
    elif videos:
        image = videos[0].get("thumbnail_url")
    text = _cut(tweet.get("text") or "", 160)
    extras = []
    if photos:
        extras.append(f"{len(photos)}图")
    if videos:
        extras.append("含视频")
    stamp = tweet.get("created_timestamp")
    meta = " · ".join(item for item in (_date(stamp) if stamp else "", *extras,
                                        f"♥{human_count(tweet.get('likes'))}" if tweet.get("likes") else "") if item)
    name = author.get("name") or screen
    return Preview("X", f"{name} (@{screen})", f"https://x.com/{screen}/status/{tweet['id']}", [text, meta],
                   image_url=image)


def arxiv_id(url: str) -> str | None:
    if not host_matches(host_of(url), "arxiv.org"):
        return None
    match = re.match(rf"/(?:abs|pdf|html|format)/{ARXIV_ID}(?:\.pdf)?/?$", urlsplit(url).path)
    return match.group(1) if match else None


def parse_arxiv_atom(xml: str, paper: str) -> Preview | None:
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title = _squash(entry.findtext("a:title", "", ns))
    if not title or title.lower() == "error":
        return None
    authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]
    category = entry.find("arxiv:primary_category", ns)
    line = " · ".join(item for item in (short_authors(authors),
                                        category.get("term", "") if category is not None else "") if item)
    return Preview("arXiv", _cut(title, 120), f"https://arxiv.org/abs/{paper}",
                   [line, first_sentence(entry.findtext("a:summary", "", ns))])


def parse_arxiv_page(page: str, paper: str) -> Preview | None:
    meta = parse_meta(page)
    title = meta.first("citation_title")
    if not title:
        return None
    return Preview("arXiv", _cut(title.replace("\\", ""), 120), f"https://arxiv.org/abs/{paper}",
                   [short_authors(meta.all("citation_author")),
                    first_sentence(meta.first("citation_abstract", "og:description"))])


def rxiv_doi(url: str) -> tuple[str, str] | None:
    host = host_of(url)
    server = "biorxiv" if host_matches(host, "biorxiv.org") else "medrxiv" if host_matches(host, "medrxiv.org") \
        else None
    match = re.match(r"/content/(?:early/\d{4}/\d{2}/\d{2}/)?(10\.1101/(?:\d{4}\.\d{2}\.\d{2}\.)?\d+)"
                     r"(?:v\d+)?(?:[./].*)?$", urlsplit(url).path)
    return (server, match.group(1)) if server and match else None


def parse_rxiv(data: dict, server: str) -> Preview | None:
    items = data.get("collection") if isinstance(data, dict) else None
    if not items:
        return None
    paper = items[-1]
    label = "bioRxiv" if server == "biorxiv" else "medRxiv"
    authors = short_authors([a for a in (paper.get("authors") or "").split(";")])
    line = " · ".join(item for item in (authors, paper.get("date", ""), paper.get("category", "")) if item)
    url = f"https://www.{server}.org/content/{paper.get('doi')}v{paper.get('version', 1)}"
    return Preview(label, _cut(paper.get("title", ""), 120), url, [line, first_sentence(paper.get("abstract", ""))])


def parse_crossref(data: dict, label: str, url: str) -> Preview | None:
    work = data.get("message") if isinstance(data, dict) else None
    if not isinstance(work, dict) or not work.get("title"):
        return None
    authors = [" ".join(p for p in (a.get("given", ""), a.get("family", "")) if p) or a.get("name", "")
               for a in work.get("author") or []]
    parts = ((work.get("published") or work.get("issued") or {}).get("date-parts") or [[]])[0]
    published = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts)) if parts else ""
    journal = (work.get("container-title") or [""])[0]
    line = " · ".join(item for item in (short_authors(authors), journal, published) if item)
    abstract = re.sub(r"<jats:title>.*?</jats:title>", " ", work.get("abstract") or "", flags=re.DOTALL)
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    return Preview(label, _cut(work["title"][0], 120), url, [line, first_sentence(abstract)])


def site_label(url: str, meta: PageMeta | None = None) -> str:
    host = host_of(url)
    for suffix, label in GENERIC_LABELS.items():
        if host_matches(host, suffix):
            return label
    site = meta.first("og:site_name") if meta else ""
    return _cut(site, 16) if site else host


def parse_generic(page: str, url: str) -> Preview | None:
    meta = parse_meta(page)
    title = meta.first("citation_title", "og:title", "twitter:title") or meta.title
    if host_matches(host_of(url), "bilibili.com"):
        title = re.sub(r"\s*[-_]\s*哔哩哔哩.*$", "", title)
    if not title or BAD_TITLE_RE.search(title):
        return None
    label = site_label(url, meta)
    authors = meta.all("citation_author") or meta.all("dc.creator")
    journal = meta.first("citation_journal_title")
    published = meta.first("citation_publication_date", "citation_date", "article:published_time")[:10]
    lines = []
    if authors or journal:
        lines.append(" · ".join(item for item in (short_authors(authors), journal, published) if item))
    description = meta.first("og:description", "twitter:description", "description")
    if description and description != title:
        lines.append(_cut(description, 90))
    canonical = meta.canonical if meta.canonical.startswith("http") else meta.first("og:url")
    if not canonical.startswith("http") or host_of(canonical) != host_of(url):
        canonical = url
    image = meta.first("og:image", "og:image:url", "twitter:image", "twitter:image:src")
    if image.startswith("//"):
        image = "https:" + image
    elif image.startswith("/"):
        parts = urlsplit(url)
        image = f"{parts.scheme}://{parts.netloc}{image}"
    return Preview(label, _cut(title, 100), clean_url(canonical), lines,
                   image_url=image if image.startswith("http") else None)


# ---------------------------------------------------------------- fetchers


async def _page(ctx: Ctx, url: str, **headers: str) -> tuple[str, str]:
    body, info, final = await ctx.fetch(url, headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                                                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", **headers},
                                        max_bytes=MAX_PAGE_BYTES, timeout=20)
    content_type = info.get("content-type", "")
    if content_type and not re.search(r"html|xml", content_type, re.IGNORECASE):
        raise FeatureError("不是网页")
    return decode_html(body, content_type), final


async def _bilibili(ctx: Ctx, url: str) -> Preview | None:
    page = ""
    if host_of(url) in BILIBILI_SHORT:
        # Reuse the landing page: a second request right after the redirect tends to hit a captcha.
        page, url = await _page(ctx, url)
    video = bilibili_video_id(url)
    if video is not None:
        data = await ctx.fetch_json(f"https://api.bilibili.com/x/web-interface/view?{video[0]}={video[1]}",
                                    headers={"Referer": "https://www.bilibili.com/"}, timeout=15)
        return parse_bilibili_view(data, url)
    mid = bilibili_space_mid(url)
    if mid is not None:
        data = await ctx.fetch_json(f"https://api.bilibili.com/x/web-interface/card?mid={mid}",
                                    headers={"Referer": "https://www.bilibili.com/"}, timeout=15)
        return parse_bilibili_card(data, mid)
    if not page:
        page, url = await _page(ctx, url)
    return parse_generic(page, clean_url(url))


async def _wechat(ctx: Ctx, url: str) -> Preview | None:
    page, final = await _page(ctx, url)
    return parse_wechat(page, final if host_of(final) == "mp.weixin.qq.com" else url)


async def _twitter(ctx: Ctx, status: str) -> Preview | None:
    return parse_fxtwitter(await ctx.fetch_json(f"https://api.fxtwitter.com/status/{status}", timeout=20))


async def _arxiv(ctx: Ctx, paper: str) -> Preview | None:
    try:
        body, _, _ = await ctx.fetch(f"https://export.arxiv.org/api/query?id_list={quote(paper, safe='/.')}",
                                     timeout=10)
        preview = parse_arxiv_atom(body.decode("utf-8", "replace"), paper)
        if preview:
            return preview
    except FeatureError:
        pass  # The export API rate-limits aggressively; the abstract page has citation meta.
    page, _ = await _page(ctx, f"https://arxiv.org/abs/{paper}")
    return parse_arxiv_page(page, paper)


async def _rxiv(ctx: Ctx, server: str, doi: str) -> Preview | None:
    return parse_rxiv(await ctx.fetch_json(f"https://api.biorxiv.org/details/{server}/{doi}", timeout=20), server)


async def _crossref(ctx: Ctx, doi: str, label: str, url: str) -> Preview | None:
    data = await ctx.fetch_json(f"https://api.crossref.org/works/{quote(doi, safe='/')}", timeout=15)
    return parse_crossref(data, label, url)


async def _generic(ctx: Ctx, url: str) -> Preview | None:
    if urlsplit(url).path.lower().endswith(MEDIA_EXTENSIONS):
        return None
    doi = DOI_RE.search(urlsplit(url).path)
    if host_matches(host_of(url), "science.org") and doi:
        # science.org sits behind a bot wall; Crossref has the same bibliographic data.
        return await _crossref(ctx, doi.group(1), "Science", f"https://www.science.org/doi/{doi.group(1)}")
    try:
        page, final = await _page(ctx, url)
    except FeatureError:
        if doi:
            return await _crossref(ctx, doi.group(1), site_label(url), clean_url(url))
        raise
    return parse_generic(page, clean_url(final) if host_of(final) == host_of(url) else url)


async def _image(ctx: Ctx, url: str) -> tuple[bytes, str] | None:
    try:
        body, info, _ = await ctx.fetch(url, headers={"Accept": "image/avif,image/webp,image/*;q=0.8"},
                                        max_bytes=MAX_IMAGE_BYTES, timeout=15)
    except FeatureError:
        return None
    mime = sniff_mime(body) or info.get("content-type", "").split(";")[0].strip()
    return (body, mime) if mime.startswith("image/") else None


async def preview_link(ctx: Ctx, link: Link, *, with_image: bool = True) -> Preview | None:
    url = link.url
    host = host_of(url)
    if await _resolves_internal(urlsplit(url).hostname or ""):
        return None
    preview: Preview | None = None
    try:
        if host in BILIBILI_SHORT or host_matches(host, "bilibili.com"):
            preview = await _bilibili(ctx, url)
        elif host == "mp.weixin.qq.com":
            preview = await _wechat(ctx, url)
        elif (status := twitter_status(url)) is not None:
            preview = await _twitter(ctx, status)
        elif (paper := arxiv_id(url)) is not None:
            preview = await _arxiv(ctx, paper)
        elif (rxiv := rxiv_doi(url)) is not None:
            preview = await _rxiv(ctx, *rxiv)
        elif not host_matches(host, "arxiv.org"):
            preview = await _generic(ctx, url)
    except (FeatureError, ValueError, KeyError, TypeError) as error:
        log.info("link preview %s failed: %s", url, error)
    if preview is None and link.hint_title:
        # QQ mini-app cards: their title is still useful next to an openable URL.
        preview = Preview(site_label(url), _cut(link.hint_title, 80), clean_url(url), [_cut(link.hint_desc, 80)])
    if preview is None or not preview.title:
        return None
    if with_image and preview.image_url:
        preview.image = await _image(ctx, preview.image_url)
    return preview


# ---------------------------------------------------------------- observer


async def link_preview(ctx: Ctx) -> Reply | None:
    config = ctx.config(FEATURE)
    limit = int(config.get("max_links", MAX_LINKS))
    window = float(config.get("dedupe_minutes", DEDUPE_SECONDS / 60)) * 60
    now = time.monotonic()
    candidates = []
    for link in message_links(ctx.inbound):
        if len(candidates) >= limit:
            break
        if should_skip(link.url):
            continue
        key = clean_url(link.url)
        if _recent_hit(ctx.inbound.conversation_id, key, now, window):
            continue
        candidates.append(link)
    if not candidates:
        return None
    outcomes = await asyncio.gather(*(asyncio.wait_for(preview_link(ctx, link, with_image=config.get("image", True)),
                                                       LINK_TIMEOUT) for link in candidates),
                                    return_exceptions=True)
    reply = Reply()
    for link, outcome in zip(candidates, outcomes):
        if isinstance(outcome, BaseException):
            log.info("link preview %s failed: %s", link.url, outcome)
            continue
        if outcome is None:
            continue
        if outcome.url != clean_url(link.url) and _recent_hit(ctx.inbound.conversation_id, outcome.url, now, window):
            continue
        reply.text(outcome.text)
        if outcome.image:
            reply.image(outcome.image[0], mime=outcome.image[1])
    return reply or None


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "链接解析", "群里发链接时自动补上标题、干净链接和封面（B站/公众号/X/arXiv/论文/博客/播客）",
                       aliases=("链接预览", "link preview", "links")))
    registry.observer(Observer(TASK, link_preview, order=20))
