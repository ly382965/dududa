"""Xiaohongshu archive: resolve shared notes, archive text + media, reply with a merged forward (no LLM)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

from .base import (
    USER_AGENT,
    Ctx,
    FeatureError,
    Observer,
    Registry,
    Reply,
    Task,
    sniff_mime,
)
from .links import host_matches, host_of, message_links

log = logging.getLogger(__name__)

FEATURE = "xiaohongshu"
TASK = "xhs_archive"
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
NOTE_PATH = re.compile(r"/(?:explore|discovery/item)/([0-9a-f]{24})")
STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL)
UNDEFINED_RE = re.compile(r"(?<=[:\[,])\s*undefined(?=\s*[,}\]])")
MAX_IMAGES = 18
MAX_LINKS = 2
DEDUPE_SECONDS = 600
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REPLY_IMAGE_BYTES = 5 * 1024 * 1024
# Keep one merged forward to a payload NapCat handles comfortably.
MAX_REPLY_TOTAL_BYTES = 30 * 1024 * 1024
LINK_TIMEOUT = 120
BOT_NAME = "嘟嘟哒"

_recent: dict[str, float] = {}


@dataclass
class NoteImage:
    url: str                # preferred (watermark-free) source
    fallback: str = ""      # page-provided URL, used if the preferred one fails
    live_video: str = ""


@dataclass
class Note:
    id: str
    title: str = ""
    desc: str = ""
    type: str = "normal"
    author: str = ""
    author_id: str = ""
    tags: list[str] = field(default_factory=list)
    likes: str = ""
    collects: str = ""
    comments: str = ""
    shares: str = ""
    time: int | None = None
    ip_location: str = ""
    images: list[NoteImage] = field(default_factory=list)
    video_url: str = ""
    video_fallbacks: list[str] = field(default_factory=list)
    xsec_token: str = ""

    @property
    def url(self) -> str:
        if self.xsec_token:
            return (f"https://www.xiaohongshu.com/discovery/item/{self.id}"
                    f"?xsec_token={quote(self.xsec_token, safe='')}&xsec_source=app_share")
        return f"https://www.xiaohongshu.com/explore/{self.id}"

    @property
    def date(self) -> str:
        if not self.time:
            return ""
        seconds = self.time / 1000 if self.time > 10**11 else self.time
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))

    @property
    def heading(self) -> str:
        if self.title:
            return self.title
        first = next((line.strip() for line in self.desc.splitlines() if line.strip()), "")
        return first[:40] or "（无标题）"

    @property
    def stats(self) -> str:
        pairs = (("赞", self.likes), ("藏", self.collects), ("评", self.comments), ("转", self.shares))
        return " · ".join(f"{label} {value}" for label, value in pairs if value not in ("", None))

    def tag_line(self) -> str:
        missing = [tag for tag in self.tags if f"#{tag}" not in self.desc]
        return " ".join(f"#{tag}" for tag in missing)

    def card(self, body_limit: int = 1500) -> str:
        meta = " · ".join(item for item in (f"作者 {self.author}" if self.author else "", self.date,
                                            f"IP {self.ip_location}" if self.ip_location else "") if item)
        body = self.desc if len(self.desc) <= body_limit else self.desc[:body_limit].rstrip() + "…"
        lines = [f"【小红书】{self.heading}", meta, self.stats]
        sections = ["\n".join(line for line in lines if line)]
        if body:
            sections.append(body)
        tail = [self.tag_line()]
        if self.video_url:
            tail.append(f"视频：{self.video_url}")
        tail.append(self.url)
        sections.append("\n".join(line for line in tail if line))
        return "\n\n".join(sections)

    def markdown(self, files: list[str], video_file: str = "") -> str:
        lines = [f"# {self.heading}", "", f"- 链接：{self.url}", f"- 作者：{self.author}（{self.author_id}）"]
        if self.date:
            lines.append(f"- 发布：{self.date}")
        if self.ip_location:
            lines.append(f"- IP 属地：{self.ip_location}")
        if self.stats:
            lines.append(f"- 互动：{self.stats}")
        if self.tags:
            lines.append("- 标签：" + " ".join(f"#{tag}" for tag in self.tags))
        lines.append(f"- 归档：{time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines += ["", self.desc or "（无正文）", ""]
        if files:
            lines += ["## 图片", ""] + [f"![{name}]({name})" for name in files] + [""]
        if self.video_url:
            lines += ["## 视频", "", f"- 源：{self.video_url}"] + ([f"- 文件：[{video_file}]({video_file})"]
                                                                  if video_file else []) + [""]
        lives = [image.live_video for image in self.images if image.live_video]
        if lives:
            lines += ["## 实况", ""] + [f"- {url}" for url in lives] + [""]
        return "\n".join(lines)


# ---------------------------------------------------------------- parsing (pure)


def is_xhs_link(url: str) -> bool:
    host = host_of(url)
    if host_matches(host, "xhslink.com", "xhslink.cn"):
        return True
    return host_matches(host, "xiaohongshu.com") and bool(NOTE_PATH.search(urlsplit(url).path))


def note_ref(url: str, depth: int = 0) -> tuple[str, str] | None:
    """(note_id, xsec_token) from a note URL, including the ``originalUrl`` of block/login redirects."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    match = NOTE_PATH.search(parts.path)
    if match and host_matches(host_of(url), "xiaohongshu.com"):
        return match.group(1), query.get("xsec_token", "")
    if depth < 3:
        for key in ("originalUrl", "redirectPath", "source"):
            nested = query.get(key, "")
            if nested.startswith(("http", "/")):
                found = note_ref(nested if nested.startswith("http") else "https://www.xiaohongshu.com" + nested,
                                 depth + 1)
                if found:
                    return found
    return None


def parse_initial_state(page: str) -> dict | None:
    match = STATE_RE.search(page)
    if not match:
        return None
    try:
        state = json.loads(UNDEFINED_RE.sub("null", match.group(1)))
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def _find_note_dict(state: dict, note_id: str) -> dict | None:
    known = []
    mobile = (((state.get("noteData") or {}).get("data") or {}).get("noteData"))
    known.append(mobile)
    detail = ((state.get("note") or {}).get("noteDetailMap") or {})
    if isinstance(detail, dict):
        entry = detail.get(note_id) or (next(iter(detail.values())) if len(detail) == 1 else None)
        known.append((entry or {}).get("note") if isinstance(entry, dict) else None)
    for candidate in known:
        if isinstance(candidate, dict) and candidate.get("noteId") and \
                (candidate.get("noteId") == note_id or not note_id):
            return candidate
    # Layout drift: search for any dict describing this note.
    stack: list[tuple[object, int]] = [(state, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            if node.get("noteId") == note_id and ("imageList" in node or "desc" in node):
                return node
            if depth < 8:
                stack.extend((value, depth + 1) for value in node.values() if isinstance(value, (dict, list)))
        elif isinstance(node, list) and depth < 8:
            stack.extend((value, depth + 1) for value in node if isinstance(value, (dict, list)))
    return None


def image_token(url: str) -> str:
    """CDN object key of a note image URL, e.g. ``1040g2sg…`` or ``spectrum/1040g0k0…``."""
    if not url:
        return ""
    parts = urlsplit(url).path.lstrip("/").split("/")
    if len(parts) > 2 and parts[0].isdigit() and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
        parts = parts[2:]
    return "/".join(parts).split("!")[0]


def clean_desc(text: str) -> str:
    text = re.sub(r"#([^#\[\]\n]+?)\[话题\]#", r"#\1", text or "")
    text = re.sub(r"\[([^\[\]\n]{1,12})R\]", r"[\1]", text)
    return re.sub(r"[ \t]*\n[ \t]*\n\s*", "\n\n", text).strip()


def _image(item: dict) -> NoteImage | None:
    scenes = {info.get("imageScene"): info.get("url") for info in item.get("infoList") or [] if isinstance(info, dict)}
    page_url = (item.get("urlDefault") or scenes.get("WB_DFT") or scenes.get("H5_DTL") or item.get("url")
                or item.get("urlPre") or scenes.get("WB_PRV") or scenes.get("H5_PRV") or "")
    token = image_token(page_url)
    if not token:
        return None
    preferred = f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
    live = ""
    if item.get("livePhoto"):
        streams = (item.get("stream") or {})
        for codec in ("h264", "h265"):
            for entry in streams.get(codec) or []:
                live = live or entry.get("masterUrl", "")
    return NoteImage(preferred, page_url.replace("http://", "https://", 1), live)


def _video(note: dict) -> tuple[str, list[str]]:
    video = note.get("video") or {}
    if not isinstance(video, dict):
        return "", []
    urls: list[str] = []
    key = (video.get("consumer") or {}).get("originVideoKey")
    if key:
        urls.append(f"https://sns-video-bd.xhscdn.com/{key}")
    stream = ((video.get("media") or {}).get("stream") or {})
    for codec in ("h264", "h265", "av1"):
        for entry in stream.get(codec) or []:
            urls += [entry.get("masterUrl", "")] + list(entry.get("backupUrls") or [])
    urls = [u.replace("http://", "https://", 1) for u in dict.fromkeys(u for u in urls if u)]
    return (urls[0], urls[1:]) if urls else ("", [])


def extract_note(state: dict, note_id: str, xsec_token: str = "") -> Note | None:
    raw = _find_note_dict(state, note_id)
    if raw is None:
        return None
    user = raw.get("user") or {}
    counts = raw.get("interactInfo") or {}
    desc = clean_desc(raw.get("desc") or "")
    tags = [str(tag.get("name")).strip() for tag in raw.get("tagList") or [] if isinstance(tag, dict) and tag.get("name")]
    if not tags:
        tags = list(dict.fromkeys(re.findall(r"#([^#\s\[\]]{1,30})", desc)))
    images = [image for image in (_image(item) for item in raw.get("imageList") or [] if isinstance(item, dict))
              if image]
    video_url, fallbacks = _video(raw) if raw.get("type") == "video" or raw.get("video") else ("", [])
    stamp = raw.get("time")
    return Note(
        id=str(raw.get("noteId") or note_id), title=str(raw.get("title") or "").strip(), desc=desc,
        type=str(raw.get("type") or "normal"), author=str(user.get("nickname") or user.get("nickName") or ""),
        author_id=str(user.get("userId") or ""), tags=tags, likes=str(counts.get("likedCount") or ""),
        collects=str(counts.get("collectedCount") or ""), comments=str(counts.get("commentCount") or ""),
        shares=str(counts.get("shareCount") or ""), time=int(stamp) if isinstance(stamp, (int, float)) else None,
        ip_location=str(raw.get("ipLocation") or ""), images=images, video_url=video_url,
        video_fallbacks=fallbacks, xsec_token=xsec_token or str(raw.get("xsecToken") or ""))


def failure_reason(final_url: str, page: str) -> str:
    path = urlsplit(final_url).path
    if "/login" in path or "website-login" in path:
        return "needs_login"
    if "仅支持在小红书 APP 内查看" in page or "App内打开" in page:
        return "app_only"
    if "/404" in path or "/sec_" in path:
        return "blocked"
    return "no_note_data"


# ---------------------------------------------------------------- fetching


class NoteUnavailable(Exception):
    def __init__(self, reason: str, note_id: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.note_id = note_id


async def _get_page(ctx: Ctx, url: str, user_agent: str, cookie: str) -> tuple[str, str]:
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml",
               "Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://www.xiaohongshu.com/"}
    if cookie:
        headers["Cookie"] = cookie
    body, _, final = await ctx.fetch(url, headers=headers, timeout=20, max_bytes=8 * 1024 * 1024)
    return body.decode("utf-8", "replace"), final


async def fetch_note(ctx: Ctx, url: str, cookie: str = "") -> Note:
    """Resolve a share/note link and parse the note; raises ``NoteUnavailable`` when blocked."""
    ref = note_ref(url)
    reason = "no_note_data"
    tried: set[tuple[str, str]] = set()
    if ref is None:
        page, final = await _get_page(ctx, url, MOBILE_UA, cookie)
        tried.add((final, MOBILE_UA))
        ref = note_ref(final) or note_ref(url)
        if ref is None:
            raise NoteUnavailable(failure_reason(final, page))
        state = parse_initial_state(page) if NOTE_PATH.search(urlsplit(final).path) else None
        note = extract_note(state, *ref) if state else None
        if note:
            return note
        reason = failure_reason(final, page)
    note_id, token = ref
    query = f"?xsec_token={quote(token, safe='')}" if token else ""
    attempts = [
        (f"https://www.xiaohongshu.com/discovery/item/{note_id}{query}"
         + ("&xsec_source=app_share" if token else ""), MOBILE_UA),
        (f"https://www.xiaohongshu.com/explore/{note_id}{query}" + ("&xsec_source=pc_share" if token else ""),
         USER_AGENT),
    ]
    for page_url, agent in attempts:
        if (page_url, agent) in tried:
            continue
        try:
            page, final = await _get_page(ctx, page_url, agent, cookie)
        except FeatureError as error:
            reason = str(error)
            continue
        state = parse_initial_state(page)
        note = extract_note(state, note_id, token) if state else None
        if note:
            return note
        reason = failure_reason(final, page)
    raise NoteUnavailable(reason, note_id)


async def _download(ctx: Ctx, urls: list[str], max_bytes: int, timeout: float) -> tuple[bytes, str] | None:
    for url in urls:
        if not url:
            continue
        try:
            body, info, _ = await ctx.fetch(url, headers={"Referer": "https://www.xiaohongshu.com/"},
                                            max_bytes=max_bytes, timeout=timeout)
        except FeatureError:
            continue
        mime = sniff_mime(body) or info.get("content-type", "").split(";")[0].strip()
        if body:
            return body, mime
    return None


_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
        "image/heic": ".heic", "video/mp4": ".mp4"}


async def archive(ctx: Ctx, note: Note, max_images: int, max_video_bytes: int
                  ) -> tuple[Path, list[tuple[bytes, str]]]:
    """Write note.md/note.json and media; returns the folder and the downloaded images (in order)."""
    folder = ctx.state_dir(FEATURE) / note.id
    folder.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(4)

    async def image(item: NoteImage) -> tuple[bytes, str] | None:
        async with semaphore:
            got = await _download(ctx, [item.url, item.fallback], MAX_IMAGE_BYTES, 30)
        return got if got and got[1].startswith("image/") else None

    async def video() -> tuple[bytes, str] | None:
        if not note.video_url or max_video_bytes <= 0:
            return None
        got = await _download(ctx, [note.video_url, *note.video_fallbacks[:2]], max_video_bytes, 90)
        return got if got and got[0][4:8] == b"ftyp" else None

    results = await asyncio.gather(video(), *(image(item) for item in note.images))
    video_data, images = results[0], [item for item in results[1:] if item]
    files = []
    for index, (body, mime) in enumerate(images, 1):
        name = f"{index:02d}{_EXT.get(mime, '.img')}"
        await asyncio.to_thread((folder / name).write_bytes, body)
        files.append(name)
    video_file = ""
    if video_data:
        video_file = "video.mp4"
        await asyncio.to_thread((folder / video_file).write_bytes, video_data[0])
    (folder / "note.md").write_text(note.markdown(files, video_file), encoding="utf-8")
    (folder / "note.json").write_text(json.dumps(asdict(note), ensure_ascii=False, indent=2), encoding="utf-8")
    return folder, images[:max_images]


def build_forward(note: Note, images: list[tuple[bytes, str]], total_images: int) -> Reply:
    nodes = [{"name": BOT_NAME, "actions": [{"type": "text", "text": note.card()}]}]
    budget = MAX_REPLY_TOTAL_BYTES
    for body, mime in images:
        if len(body) <= min(MAX_REPLY_IMAGE_BYTES, budget):
            budget -= len(body)
            nodes.append({"name": BOT_NAME, "actions": [{"type": "image", "data": base64.b64encode(body).decode(),
                                                         "mime": mime}]})
    shown = len(nodes) - 1
    if total_images > shown:
        nodes.append({"name": BOT_NAME, "actions": [{"type": "text", "text": (
            f"原笔记共 {total_images} 张图，这里放了 {shown} 张，完整内容见原链接。")}]})
    return Reply().forward(nodes)


# ---------------------------------------------------------------- observer


def _recent_hit(conversation_id: str, key: str, now: float) -> bool:
    for stale in [k for k, at in _recent.items() if now - at > DEDUPE_SECONDS]:
        del _recent[stale]
    full = f"{conversation_id}|{key}"
    if full in _recent:
        return True
    _recent[full] = now
    return False


async def _handle(ctx: Ctx, url: str, config: dict, short_link: bool) -> Reply | None:
    cookie = str(config.get("cookie") or "")
    max_images = int(config.get("max_images", MAX_IMAGES))
    max_video = int(float(config.get("max_video_mb", 50)) * 1024 * 1024)
    try:
        note = await fetch_note(ctx, url, cookie)
    except NoteUnavailable as error:
        _record_error(ctx, url, error.note_id, error.reason)
        return None
    except FeatureError as error:
        _record_error(ctx, url, "", str(error))
        return None
    # Short links are only keyed by their own URL until resolved; dedupe by note id now.
    if short_link and _recent_hit(ctx.inbound.conversation_id, note.id, time.monotonic()):
        return None
    folder, images = await archive(ctx, note, max_images, max_video)
    ctx.kv_set(FEATURE, f"note:{note.id}", {"title": note.heading, "author": note.author, "url": note.url,
                                             "path": str(folder), "images": len(note.images),
                                             "video": bool(note.video_url), "archived_at": int(time.time())})
    return build_forward(note, images, len(note.images))


def _record_error(ctx: Ctx, url: str, note_id: str, reason: str) -> None:
    entry = {"url": url, "note_id": note_id, "reason": reason, "at": int(time.time()),
             "conversation_id": ctx.inbound.conversation_id}
    log.info("xiaohongshu %s unavailable: %s", note_id or url, reason)
    ctx.kv_set(FEATURE, "last_error", entry)
    ctx.kv_set(FEATURE, f"error:{note_id or url}", entry)


async def xhs_archive(ctx: Ctx) -> Reply | None:
    config = ctx.config(FEATURE)
    now = time.monotonic()
    urls: list[tuple[str, bool]] = []
    for link in message_links(ctx.inbound):
        if len(urls) >= int(config.get("max_links", MAX_LINKS)):
            break
        if not is_xhs_link(link.url):
            continue
        ref = note_ref(link.url)
        if _recent_hit(ctx.inbound.conversation_id, ref[0] if ref else link.url.split("?")[0], now):
            continue
        urls.append((link.url, ref is None))
    if not urls:
        return None
    outcomes = await asyncio.gather(*(asyncio.wait_for(_handle(ctx, url, config, short), LINK_TIMEOUT)
                                      for url, short in urls), return_exceptions=True)
    reply = Reply()
    for (url, _), outcome in zip(urls, outcomes):
        if isinstance(outcome, BaseException):
            _record_error(ctx, url, "", f"{type(outcome).__name__}: {outcome}"[:200])
        elif outcome:
            reply.actions.extend(outcome.actions)
    return reply or None


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "小红书归档", "群里分享小红书笔记时自动归档正文和无水印图片，并合并转发出来",
                       aliases=("小红书", "xhs", "xiaohongshu")))
    registry.observer(Observer(TASK, xhs_archive, order=21))
