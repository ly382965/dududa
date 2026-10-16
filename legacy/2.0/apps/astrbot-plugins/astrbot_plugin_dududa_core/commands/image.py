from __future__ import annotations

import base64
from typing import Any

import httpx
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image
from astrbot.core.star.filter.command import GreedyStr

from ..config import load_astrbot_config


class ImageGenerationError(RuntimeError):
    def __init__(self, user_message: str, log_message: str | None = None):
        super().__init__(log_message or user_message)
        self.user_message = user_message


class CoreImageCommands:
    async def image(self, event: AstrMessageEvent, prompt: GreedyStr):
        """生成图片"""
        if not self.perms.is_trusted(event):
            yield event.plain_result("gpt-image-2 可用但较慢，当前只开放给 trusted/admin。")
            event.stop_event()
            return
        text = str(prompt).strip()
        if not text:
            yield event.plain_result("请给我一段图片描述。")
            event.stop_event()
            return
        blocked = self._image_prompt_block_reason(text)
        if blocked:
            yield event.plain_result(blocked)
            event.stop_event()
            return
        yield event.plain_result("开始生成图片，gpt-image-2 可能会慢一点。")
        try:
            image_component = await self._generate_image(text)
        except ImageGenerationError as exc:
            logger.warning("Dududa image generation failed: %s", exc)
            yield event.plain_result(f"图片生成失败：{exc.user_message}")
            event.stop_event()
            return
        except httpx.TimeoutException as exc:
            logger.warning("Dududa image generation timed out: %s", exc)
            yield event.plain_result("图片生成超时：gpt-image-2 这次等太久了，可以稍后重试，或把描述写短一点。")
            event.stop_event()
            return
        except Exception as exc:
            logger.warning("Dududa image generation failed unexpectedly: %s", exc)
            yield event.plain_result(f"图片生成失败：{type(exc).__name__}")
            event.stop_event()
            return
        self.audit.write(event, "image_generate", {"chars": len(text)})
        yield event.chain_result([image_component])
        event.stop_event()

    def _openai_source(self) -> tuple[str, str, dict[str, str]]:
        cfg = load_astrbot_config()
        for source in cfg.get("provider_sources", []):
            if source.get("id") != "openai":
                continue
            raw_key = source.get("key")
            if isinstance(raw_key, list):
                keys = [str(item) for item in raw_key if str(item).strip()]
            elif raw_key:
                keys = [str(raw_key)]
            else:
                keys = []
            if not keys:
                raise RuntimeError("openai provider has no api key")
            custom_headers = {
                str(key): str(value)
                for key, value in (source.get("custom_headers") or {}).items()
                if str(key).strip() and str(value).strip()
            }
            return str(source.get("api_base", "")).rstrip("/"), keys[0], custom_headers
        raise RuntimeError("openai provider source not found")

    async def _generate_image(self, prompt: str) -> Image:
        base_url, api_key, custom_headers = self._openai_source()
        model = str(self.config.get("image_model_id", "gpt-image-2") or "gpt-image-2")
        timeout_seconds = self._clamp_int(self.config.get("image_timeout_seconds", 420), 420, 60, 900)
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **custom_headers}
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{base_url}/images/generations", headers=headers, json=payload)
        if response.status_code >= 400:
            raise self._image_api_error(response)
        data = response.json()
        item = (data.get("data") or [{}])[0]
        if item.get("b64_json"):
            raw = item["b64_json"]
            base64.b64decode(raw)
            return Image.fromBase64(raw)
        if item.get("url"):
            return Image.fromURL(item["url"])
        raise RuntimeError("image api returned no image data")

    @staticmethod
    def _image_api_error(response: httpx.Response) -> ImageGenerationError:
        status = response.status_code
        code = ""
        message = response.text[:200]
        try:
            data = response.json()
        except ValueError:
            data = {}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "")
            message = str(error.get("message") or message).strip()
        log_message = f"image api status {status}: {code or 'unknown'}: {message[:200]}"
        if code == "content_policy_violation":
            return ImageGenerationError(
                "请求被图像模型安全策略拒绝。当前服务商对低龄角色、性化、暴力和伪造类描述很敏感；"
                "可以把“小女孩/小男孩”改成“Q版小精灵/卡通角色”后重试。",
                log_message,
            )
        if status in {401, 403}:
            return ImageGenerationError("图像模型鉴权失败，请检查 openai 账号组和图像模型权限。", log_message)
        if status == 429:
            return ImageGenerationError("图像模型当前限流了，稍后再试。", log_message)
        if status >= 500:
            return ImageGenerationError("图像模型服务端暂时异常，稍后再试。", log_message)
        return ImageGenerationError(f"图像模型返回 {status}，这次请求没有被接受。", log_message)

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _image_prompt_block_reason(prompt: str) -> str | None:
        lowered = prompt.lower()
        unsafe_terms = [
            "色情",
            "裸",
            "nsfw",
            "性化",
            "擦边",
            "未成年",
            "儿童",
            "孩子",
            "小孩",
            "小女孩",
            "小男孩",
            "幼女",
            "萝莉",
            "正太",
            "证件",
            "成绩单",
            "官方通知",
            "伪造",
        ]
        if any(term in lowered for term in unsafe_terms):
            return "这个图片请求不适合生成，我不能帮忙做色情、低龄角色、擦边或伪造证件/成绩单/官方通知类图片。可以改成 Q版小精灵、卡通角色或原创吉祥物。"
        return None
