"""Image generation through omp's ``generate_image`` tool (ChatGPT/Codex hosted image generation)."""

from __future__ import annotations

import base64
import re
import tempfile
import time
import uuid
from pathlib import Path

from ..omp import OmpError, OmpTimeout
from .base import Command, Ctx, Registry, Reply, Task

FEATURE = "imagegen"
TASK = "image_generation"
TIMEOUT = 240
MAX_PROMPT = 1000
OVERLAY = "generate_image:\n  enabled: true\ntools:\n  approvalMode: yolo\n"
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
USAGE = "用法：嘟嘟哒 画图 <画面描述>（可以附带或引用一张参考图）"
REFUSAL = ("这个我不能画哦：色情擦边、未成年人性化、血腥暴力，以及伪造证件、成绩单、公章或官方通知都不行。"
           "换成原创角色、Q版小动物之类的试试吧～")
SYSTEM = """你是嘟嘟哒的画图助手，只负责把用户的画图需求交给 generate_image 工具。
- 把需求整理成清晰具体的画面描述（subject 必填，可补充 scene、style、composition、lighting、aspect_ratio），只调用一次 generate_image。
- 若提供了参考图文件，在 input 中用 path 传入，并在 subject 里用 Image 1、Image 2 指代各参考图的作用。
- 安全边界：不生成色情或擦边内容、未成年人性化、血腥暴力或仇恨内容、伪造证件/成绩单/公章/官方通知、真实人物的不实或侮辱性图片。遇到这类需求不要调用工具，直接用一句中文婉拒。
- 生成完成后只用一句不超过 20 字的中文给图片起个说明，不要输出文件路径、模型名或其他内容。"""

SEXUAL = ("色情", "黄图", "涩图", "色图", "瑟图", "裸", "露点", "nsfw", "porn", "hentai", "nude", "naked", "性化",
          "擦边", "性感内衣", "情趣", "做爱", "性交", "r18", "r-18", "lewd", "sexy", "开房", "胸部特写")
FORGERY = ("伪造", "假证", "证件", "身份证", "护照", "驾照", "驾驶证", "学生证", "成绩单", "毕业证", "学位证", "录取通知书",
           "官方通知", "红头文件", "公章", "营业执照", "发票", "病历", "诊断证明", "fake id", "forged")
MINORS = ("未成年", "儿童", "孩子", "小孩", "小女孩", "小男孩", "幼女", "幼童", "萝莉", "正太", "小学生", "初中生",
          "loli", "shota", "child", "kid")
GORE = ("血腥", "断肢", "肢解", "开膛", "爆头", "虐杀", "gore")

_busy: set[str] = set()


def blocked(prompt: str) -> bool:
    """Deterministic guard; the model's system prompt enforces the rest of the persona's boundaries."""
    text = re.sub(r"\s+", "", prompt.lower())
    if any(term in text for term in SEXUAL) or any(term in text for term in GORE):
        return True
    if any(term in text for term in FORGERY):
        return True
    # Minors alone are fine ("小孩放风筝"); together with revealing/romantic wording they are not.
    suggestive = ("泳装", "比基尼", "内衣", "暴露", "诱惑", "亲吻", "恋爱", "约会", "床上", "bikini", "lingerie")
    return any(term in text for term in MINORS) and any(term in text for term in suggestive)


def caption(text: str) -> str:
    line = next((item.strip() for item in text.splitlines() if item.strip()), "")
    line = re.sub(r"(/[\w.\-]+)+\.(png|webp|jpe?g)|https?://\S+", "", line).strip(" `*")
    return line[:40] if line else "画好啦～"


def overlay_path(ctx: Ctx):
    path = ctx.state_dir(FEATURE) / "omp-image.yml"
    if not path.exists() or path.read_text(encoding="utf-8") != OVERLAY:
        path.write_text(OVERLAY, encoding="utf-8")
    return path


def discard_tool_files(images: list[dict], since: float) -> None:
    """omp saves every generated image as ``$TMPDIR/omp-image-*``; delete this run's copies."""
    sizes = {len(base64.b64decode(image["data"])) for image in images}
    for path in Path(tempfile.gettempdir()).glob("omp-image-*"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= since and stat.st_size in sizes:
            path.unlink(missing_ok=True)


async def draw_command(ctx: Ctx) -> Reply | str:
    request = ctx.args.strip()
    if not request:
        return USAGE
    if len(request) > MAX_PROMPT:
        return f"描述太长啦，压缩到 {MAX_PROMPT} 字以内再来吧。"
    if blocked(request):
        return REFUSAL
    scope = ctx.inbound.scope
    if scope in _busy:
        return "这边已经有一张图在画啦，等它画完再来～"
    _busy.add(scope)
    references = []
    try:
        images = await ctx.download_images(limit=3)
        directory = ctx.state_dir(FEATURE) / "refs"
        directory.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(images, 1):
            path = directory / f"{uuid.uuid4().hex}-{index}.{EXTENSIONS.get(image['mimeType'], 'png')}"
            path.write_bytes(base64.b64decode(image["data"]))
            references.append(path)
        prompt = f"画图需求：{request}"
        if references:
            prompt += "\n参考图文件（按顺序为 Image 1、Image 2…）：\n" + "\n".join(str(path) for path in references)
        started = time.time() - 1
        try:
            result = await ctx.agent_once(prompt, service="image", builtin_tools=("generate_image",), system=SYSTEM,
                                          config_overlay=overlay_path(ctx), images=images, timeout=TIMEOUT)
        except OmpTimeout:
            return "画太久啦，这次超时了……换个简单点的描述再试试吧。"
        except OmpError as error:
            detail = str(error).lower()
            if "policy" in detail or "safety" in detail or "moderation" in detail:
                return "这次的描述被图像模型的安全策略拦下了，换个说法试试吧。"
            return "生图服务暂时出错了，稍后再试试吧。"
    finally:
        _busy.discard(scope)
        for path in references:
            path.unlink(missing_ok=True)
    discard_tool_files(result.images, started)
    if not result.images:
        text = result.text.strip()
        return text[:200] if text else "这次没画出来……换个描述再试试吧。"
    reply = Reply().text(caption(result.text))
    for image in result.images[:4]:
        reply.actions.append({"type": "image", "data": image["data"], "mime": image.get("mimeType", "image/png")})
    return reply


def register(registry: Registry) -> None:
    registry.task(Task(TASK, "生图", "用 ChatGPT 图像生成按描述画图（画图 <描述>，可附参考图）", aliases=("imagegen", "画图")))
    registry.command(Command(("生图", "画图", "draw", "image gen", "img", "imggen", "img gen"), draw_command,
                             "画图 / 生图 <描述>：AI 画图，可附带或引用参考图（较慢，约 1–3 分钟）", task=TASK))
