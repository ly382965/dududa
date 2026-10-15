"""
Iris Chat Memory - OneBot11 平台适配器

实现 QQ 平台（OneBot11 协议）的适配器，从 AstrMessageEvent 提取平台信息。

OneBot11 协议参考：
- https://github.com/botuniverse/onebot-11

实现要点（AstrBot v4.x）：
- 用户ID：event.message_obj.sender.user_id
- 用户昵称：event.message_obj.sender.nickname（群聊时优先使用 sender.card）
- 群ID：event.message_obj.group_id（私聊为空字符串）
- 群名称：从 raw_message 提取（如果可用）
- 用户角色：event.message_obj.sender.role（owner/admin/member）
"""

from typing import Any, List, TYPE_CHECKING

from iris_memory.core import get_logger
from iris_memory.platform.base import PlatformAdapter, ReplyInfo

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from iris_memory.image.models import ImageInfo

logger = get_logger("platform.qq")


class OneBot11Adapter(PlatformAdapter):
    """OneBot11 平台适配器

    实现 QQ 平台（OneBot11 协议）的消息信息提取。

    特性：
    - 支持群聊/私聊识别
    - 群聊时优先返回群名片
    - 支持角色识别（owner/admin/member）
    - 提供原始消息访问

    Examples:
        >>> adapter = OneBot11Adapter()
        >>> user_id = adapter.get_user_id(event)
        >>> group_id = adapter.get_group_id(event)
        >>> is_group = adapter.is_group_message(event)
    """

    def get_user_id(self, event: Any) -> str:
        """获取用户ID（QQ号）

        Args:
            event: AstrBot 消息事件对象

        Returns:
            QQ号字符串
        """
        try:
            return str(event.message_obj.sender.user_id)
        except AttributeError:
            logger.error("无法获取用户ID：event.message_obj.sender.user_id 不存在")
            raise

    def get_user_name(self, event: Any) -> str:
        """获取用户显示名称

        群聊时优先返回群名片（如果有），否则返回昵称。

        Args:
            event: AstrBot 消息事件对象

        Returns:
            用户显示名称
        """
        try:
            sender = event.message_obj.sender

            if self.is_group_message(event):
                card = getattr(sender, "card", "")
                if card:
                    return str(card)

            return str(sender.nickname)
        except AttributeError:
            logger.error("无法获取用户名称：event.message_obj.sender 结构异常")
            raise

    def get_user_nickname(self, event: Any) -> str:
        """获取用户原始昵称

        不考虑群名片，始终返回原始昵称。

        Args:
            event: AstrBot 消息事件对象

        Returns:
            用户昵称
        """
        try:
            return str(event.message_obj.sender.nickname)
        except AttributeError:
            logger.error("无法获取用户昵称：event.message_obj.sender.nickname 不存在")
            raise

    def get_group_id(self, event: Any) -> str:
        """获取群聊ID（群号）

        Args:
            event: AstrBot 消息事件对象

        Returns:
            群号字符串，私聊时返回空字符串
        """
        try:
            group_id = getattr(event.message_obj, "group_id", "")
            return str(group_id) if group_id else ""
        except AttributeError:
            logger.error("无法获取群ID：event.message_obj.group_id 不存在")
            raise

    def get_group_name(self, event: Any) -> str:
        """获取群聊名称

        尝试从原始消息中提取群名称信息。
        OneBot11 协议中，群名称通常不在消息事件中提供，
        需要通过专门的 API 调用获取。

        Args:
            event: AstrBot 消息事件对象

        Returns:
            群名称字符串，无法获取时返回空字符串
        """
        try:
            raw_msg = self.get_raw_message(event)

            if "group_name" in raw_msg:
                return str(raw_msg["group_name"])

            sender = event.message_obj.sender
            if hasattr(sender, "group_name"):
                return str(sender.group_name)

            return ""
        except Exception as e:
            logger.debug(f"无法获取群名称: {e}")
            return ""

    def get_user_role(self, event: Any) -> str:
        """获取用户在群聊中的角色

        Args:
            event: AstrBot 消息事件对象

        Returns:
            角色字符串：owner、admin、member、private
        """
        try:
            if not self.is_group_message(event):
                return "private"

            role = getattr(event.message_obj.sender, "role", "member")
            return str(role)
        except AttributeError:
            logger.error("无法获取用户角色：event.message_obj.sender.role 不存在")
            raise

    def get_raw_message(self, event: Any) -> dict[str, Any]:
        """获取平台原始消息对象

        Args:
            event: AstrBot 消息事件对象

        Returns:
            原始消息字典，解析失败时返回空字典
        """
        try:
            raw_msg = getattr(event.message_obj, "raw_message", None)

            if raw_msg is None:
                logger.debug("原始消息对象为空")
                return {}

            if isinstance(raw_msg, dict):
                return raw_msg

            if hasattr(raw_msg, "__dict__"):
                return raw_msg.__dict__

            logger.debug(f"无法解析原始消息对象: {type(raw_msg)}")
            return {}
        except Exception as e:
            logger.error(f"获取原始消息失败: {e}")
            return {}

    def is_group_message(self, event: "AstrMessageEvent") -> bool:
        """判断是否为群聊消息

        Args:
            event: AstrBot 消息事件对象

        Returns:
            True 表示群聊消息，False 表示私聊消息
        """
        try:
            group_id = self.get_group_id(event)
            return bool(group_id)
        except Exception:
            return False

    def get_images(self, event: Any) -> List["ImageInfo"]:
        """获取消息中的图片列表

        从 OneBot11 消息段中提取图片信息。
        支持提取：
        - 当前消息中的图片
        - 引用/回复消息中的图片

        Args:
            event: AstrBot 消息事件对象

        Returns:
            图片信息列表
        """
        from iris_memory.image.models import ImageInfo

        images: List[ImageInfo] = []

        try:
            raw_msg = self.get_raw_message(event)
            if not raw_msg:
                return images

            images.extend(self._extract_images_from_message(raw_msg, "user"))

            images.extend(self._extract_reply_images(raw_msg))

            logger.debug(f"从消息中提取到 {len(images)} 张图片")
            return images

        except Exception as e:
            logger.error(f"提取图片信息失败: {e}")
            return images

    def get_reply_info(self, event: Any) -> ReplyInfo:
        """获取回复/引用消息的关联信息

        从 OneBot11 消息段中提取 reply 类型的消息段信息。
        OneBot11 协议中 reply 消息段包含：
        - id: 被回复消息的ID
        - user_id: 被回复消息的发送者ID（go-cqhttp 扩展）
        - content: 被回复消息的内容（go-cqhttp 扩展）
        - sender.nickname: 被回复消息的发送者昵称（go-cqhttp 扩展）

        Args:
            event: AstrBot 消息事件对象

        Returns:
            ReplyInfo 实例，非回复消息时返回空 ReplyInfo
        """
        try:
            raw_msg = self.get_raw_message(event)
            if not raw_msg:
                return ReplyInfo()

            message_segments = raw_msg.get("message", [])

            if isinstance(message_segments, str):
                return self._parse_reply_from_cq(message_segments)

            if not isinstance(message_segments, list):
                return ReplyInfo()

            for segment in message_segments:
                if not isinstance(segment, dict):
                    continue

                if segment.get("type") == "reply":
                    data = segment.get("data", {})

                    reply_info = ReplyInfo(
                        message_id=str(data.get("id", "")),
                        user_id=str(data.get("user_id", ""))
                        if data.get("user_id")
                        else "",
                        user_name="",
                        content="",
                    )

                    if "sender" in data and isinstance(data["sender"], dict):
                        reply_info.user_name = str(data["sender"].get("nickname", ""))

                    if "content" in data:
                        content = data["content"]
                        if isinstance(content, str):
                            reply_info.content = content
                        elif isinstance(content, list):
                            reply_info.content = self._extract_text_from_segments(
                                content
                            )

                    logger.debug(
                        f"提取回复信息：message_id={reply_info.message_id}, "
                        f"user_id={reply_info.user_id}"
                    )
                    return reply_info

            return ReplyInfo()

        except Exception as e:
            logger.error(f"提取回复信息失败: {e}")
            return ReplyInfo()

    def _parse_reply_from_cq(self, message_str: str) -> ReplyInfo:
        """从 CQ 码字符串格式中提取回复信息

        Args:
            message_str: CQ 码格式的消息字符串

        Returns:
            ReplyInfo 实例
        """
        import re

        reply_match = re.search(r"\[CQ:reply,id=(\d+)\]", message_str)
        if reply_match:
            message_id = reply_match.group(1)
            logger.debug(f"从 CQ 码提取回复信息：message_id={message_id}")
            return ReplyInfo(message_id=message_id)

        return ReplyInfo()

    def _extract_text_from_segments(self, segments: list[Any]) -> str:
        """从消息段列表中提取纯文本内容

        Args:
            segments: 消息段列表

        Returns:
            拼接后的纯文本内容
        """
        text_parts = []
        for seg in segments:
            if isinstance(seg, dict) and seg.get("type") == "text":
                text_parts.append(seg.get("data", {}).get("text", ""))
        return "".join(text_parts)

    def _extract_images_from_message(
        self, raw_msg: dict[str, Any], source: str = "user"
    ) -> List["ImageInfo"]:
        """从消息段中提取图片

        Args:
            raw_msg: 原始消息字典
            source: 图片来源（user/forward）

        Returns:
            图片信息列表
        """
        from iris_memory.image.models import ImageInfo

        images: List[ImageInfo] = []

        message_segments = raw_msg.get("message", [])

        if isinstance(message_segments, str):
            logger.debug("消息为 CQ 码格式，暂不支持图片提取")
            return images

        if not isinstance(message_segments, list):
            return images

        for segment in message_segments:
            if not isinstance(segment, dict):
                continue

            if segment.get("type") == "image":
                data = segment.get("data", {})

                image_info = ImageInfo(
                    url=data.get("url"),
                    file_path=data.get("file"),
                    format=self._detect_image_format(data.get("url", "")),
                    size_kb=0,
                    source=source,
                    message_id=raw_msg.get("message_id", ""),
                )

                images.append(image_info)

        return images

    def _extract_reply_images(self, raw_msg: dict[str, Any]) -> List["ImageInfo"]:
        """提取引用/回复消息中的图片

        Args:
            raw_msg: 原始消息字典

        Returns:
            图片信息列表
        """
        from iris_memory.image.models import ImageInfo

        images: List[ImageInfo] = []

        message_segments = raw_msg.get("message", [])

        if not isinstance(message_segments, list):
            return images

        for segment in message_segments:
            if not isinstance(segment, dict):
                continue

            if segment.get("type") == "reply":
                data = segment.get("data", {})

                if "content" in data:
                    content = data["content"]
                    if isinstance(content, list):
                        images.extend(
                            self._extract_images_from_message(
                                {"message": content}, "forward"
                            )
                        )

                break

        return images

    def _detect_image_format(self, url: str) -> str:
        """检测图片格式

        从 URL 或文件名推断图片格式。

        Args:
            url: 图片 URL 或文件路径

        Returns:
            图片格式（jpg/jpeg/png/gif/webp）
        """
        if not url:
            return ""

        url_lower = url.lower()

        if ".jpg" in url_lower or ".jpeg" in url_lower:
            return "jpg"
        elif ".png" in url_lower:
            return "png"
        elif ".gif" in url_lower:
            return "gif"
        elif ".webp" in url_lower:
            return "webp"

        return ""

    async def get_msg_by_id(self, event: Any, message_id: str) -> ReplyInfo:
        """通过消息ID获取消息内容（OneBot11 get_msg API）

        调用 OneBot11 的 get_msg API 获取指定消息的详细内容。
        需要事件对象中包含 bot（CQHttp 实例）属性。

        Args:
            event: AstrBot 消息事件对象，需包含 bot 属性
            message_id: 消息ID

        Returns:
            ReplyInfo 实例，包含消息内容和发送者信息；
            获取失败时返回空 ReplyInfo

        Notes:
            - 依赖 aiocqhttp 的 call_action 方法
            - 不同 OneBot11 实现对 get_msg 支持程度不同
            - Lagrange.OneBot 不支持此 API
            - NapCat / go-cqhttp 通常支持此 API
        """
        import asyncio

        if not message_id:
            return ReplyInfo()

        bot = getattr(event, "bot", None)
        if bot is None:
            logger.debug("event.bot 不存在，无法调用 get_msg API")
            return ReplyInfo()

        try:
            result = await asyncio.wait_for(
                bot.call_action("get_msg", message_id=int(message_id)),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.debug(f"get_msg API 超时：message_id={message_id}")
            return ReplyInfo()
        except AttributeError:
            logger.debug("bot.call_action 方法不存在，无法调用 get_msg API")
            return ReplyInfo()
        except Exception as e:
            err_str = str(e)
            if "API_NOT_FOUND" in err_str or "api not found" in err_str.lower():
                logger.debug(f"get_msg API 不可用：message_id={message_id}")
            else:
                logger.debug(
                    f"get_msg API 调用失败：message_id={message_id}, error={e}"
                )
            return ReplyInfo()

        if not result or not isinstance(result, dict):
            return ReplyInfo()

        sender = result.get("sender", {})
        user_id = str(sender.get("user_id", "")) if sender else ""
        user_name = ""
        if sender:
            card = sender.get("card", "")
            nickname = sender.get("nickname", "")
            user_name = card or nickname

        message_segments = result.get("message", [])
        content = ""

        if isinstance(message_segments, str):
            content = message_segments
        elif isinstance(message_segments, list):
            content = self._extract_text_from_segments(message_segments)

        if not content:
            raw_message = result.get("raw_message", "")
            if isinstance(raw_message, str) and raw_message:
                content = raw_message

        if not content and not user_id:
            return ReplyInfo()

        return ReplyInfo(
            message_id=message_id,
            user_id=user_id,
            user_name=user_name,
            content=content,
        )
