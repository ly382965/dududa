"""测试消息钩子处理模块"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import ExitStack
from datetime import datetime

from iris_memory.core.message_hook import (
    handle_user_message,
    update_l1_buffer,
    _backfill_reply_from_buffer,
)
from iris_memory.l1_buffer.models import ContextMessage
from iris_memory.platform.base import ReplyInfo


def _patch_handle_deps(adapter=None):
    patches = [
        patch("iris_memory.utils.sanitize_input", side_effect=lambda x, **kw: x),
        patch(
            "iris_memory.core.message_hook._update_profile_names",
            new_callable=AsyncMock,
        ),
        patch(
            "iris_memory.core.message_hook._queue_images_to_l1_buffer",
            new_callable=AsyncMock,
        ),
        patch(
            "iris_memory.core.message_hook._parse_images_if_enabled",
            new_callable=AsyncMock,
        ),
    ]
    if adapter:
        patches.append(patch("iris_memory.platform.get_adapter", return_value=adapter))
    return patches


class TestHandleUserMessage:
    """测试用户消息处理主函数"""

    @pytest.mark.asyncio
    async def test_handle_with_available_buffer(self):
        """测试 L1 Buffer 可用时的消息处理"""
        event = MagicMock()
        event.message_str = "你好"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "测试用户"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "999"}
        adapter.get_reply_info.return_value = ReplyInfo()

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["group_id"] == "group123"
        assert call_kwargs["role"] == "user"
        assert call_kwargs["content"] == "你好"
        assert call_kwargs["source"] == "user456"
        assert call_kwargs["metadata"]["user_name"] == "测试用户"
        assert call_kwargs["metadata"]["message_id"] == "999"
        assert "reply_message_id" not in call_kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_handle_with_reply_info(self):
        """测试带回复信息的消息处理"""
        event = MagicMock()
        event.message_str = "我也觉得"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1000"}
        adapter.get_reply_info.return_value = ReplyInfo(
            message_id="6283", user_id="1234567", user_name="张三", content="你好啊"
        )

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["message_id"] == "1000"
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert call_kwargs["metadata"]["reply_user_id"] == "1234567"
        assert call_kwargs["metadata"]["reply_user_name"] == "张三"
        assert call_kwargs["metadata"]["reply_content"] == "你好啊"

    @pytest.mark.asyncio
    async def test_handle_with_reply_no_content(self):
        """测试回复信息无内容时尝试 L1 Buffer 回填和 API 回填"""
        event = MagicMock()
        event.message_str = "是的"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = ""
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1001"}
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        adapter.get_msg_by_id = AsyncMock(return_value=ReplyInfo())

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["message_id"] == "1001"
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert "reply_user_id" not in call_kwargs["metadata"]
        assert "reply_user_name" not in call_kwargs["metadata"]
        assert "reply_content" not in call_kwargs["metadata"]
        adapter.get_msg_by_id.assert_called_once_with(event, "6283")

    @pytest.mark.asyncio
    async def test_handle_with_unavailable_buffer(self):
        """测试 L1 Buffer 不可用时的消息处理"""
        event = MagicMock()
        event.message_str = "你好"

        buffer = MagicMock()
        buffer.is_available = False
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = None

        with ExitStack() as stack:
            for p in _patch_handle_deps():
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_with_empty_content(self):
        """测试消息内容为空时的处理"""
        event = MagicMock()
        event.message_str = ""

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_handle_deps():
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_with_none_content(self):
        """测试消息内容为 None 时的处理"""
        event = MagicMock()
        event.message_str = None

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        with ExitStack() as stack:
            for p in _patch_handle_deps():
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_not_called()


class TestUpdateL1Buffer:
    """测试 L1 Buffer 更新函数"""

    @pytest.mark.asyncio
    async def test_update_with_user_message(self):
        """测试添加用户消息"""
        event = MagicMock()

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"

        with patch("iris_memory.platform.get_adapter", return_value=adapter):
            await update_l1_buffer(event, component_manager, "user", "你好")

        buffer.add_message.assert_called_once_with(
            group_id="group123",
            role="user",
            content="你好",
            source="user456",
            persona_id="default",
        )

    @pytest.mark.asyncio
    async def test_update_with_assistant_message(self):
        """测试添加助手消息"""
        event = MagicMock()

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"

        with patch("iris_memory.platform.get_adapter", return_value=adapter):
            await update_l1_buffer(event, component_manager, "assistant", "你好！")

        buffer.add_message.assert_called_once_with(
            group_id="group123",
            role="assistant",
            content="你好！",
            source="assistant",
            persona_id="default",
        )

    @pytest.mark.asyncio
    async def test_update_with_unavailable_buffer(self):
        """测试 L1 Buffer 不可用时不添加消息"""
        event = MagicMock()

        buffer = MagicMock()
        buffer.is_available = False
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = None

        await update_l1_buffer(event, component_manager, "user", "你好")

        buffer.add_message.assert_not_called()


class TestBackfillReplyFromBuffer:
    """测试从 L1 Buffer 回填回复信息"""

    def test_backfill_found_in_buffer(self):
        """测试从 L1 Buffer 中找到被回复消息并回填"""
        original_msg = ContextMessage(
            role="user",
            content="你好啊",
            timestamp=datetime.now(),
            token_count=3,
            source="1234567",
            metadata={"message_id": "6283", "user_name": "张三"},
        )

        buffer = MagicMock()
        buffer.get_context.return_value = [original_msg]

        metadata = {}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert metadata["reply_content"] == "你好啊"
        assert metadata["reply_user_name"] == "张三"

    def test_backfill_not_found_in_buffer(self):
        """测试 L1 Buffer 中找不到被回复消息时不回填"""
        other_msg = ContextMessage(
            role="user",
            content="其他消息",
            timestamp=datetime.now(),
            token_count=2,
            source="other",
            metadata={"message_id": "9999"},
        )

        buffer = MagicMock()
        buffer.get_context.return_value = [other_msg]

        metadata = {}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert "reply_content" not in metadata
        assert "reply_user_name" not in metadata

    def test_backfill_skips_already_filled(self):
        """测试已有 reply_content 时不覆盖"""
        original_msg = ContextMessage(
            role="user",
            content="你好啊",
            timestamp=datetime.now(),
            token_count=3,
            source="1234567",
            metadata={"message_id": "6283", "user_name": "张三"},
        )

        buffer = MagicMock()
        buffer.get_context.return_value = [original_msg]

        metadata = {"reply_content": "已有内容", "reply_user_name": "已有名字"}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert metadata["reply_content"] == "已有内容"
        assert metadata["reply_user_name"] == "已有名字"

    def test_backfill_no_user_name_in_original(self):
        """测试被回复消息没有 user_name 时不回填 reply_user_name"""
        original_msg = ContextMessage(
            role="user",
            content="你好啊",
            timestamp=datetime.now(),
            token_count=3,
            source="1234567",
            metadata={"message_id": "6283"},
        )

        buffer = MagicMock()
        buffer.get_context.return_value = [original_msg]

        metadata = {}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert metadata["reply_content"] == "你好啊"
        assert "reply_user_name" not in metadata

    def test_backfill_includes_assistant_messages(self):
        """测试匹配 assistant 消息的 message_id（用户可能回复 bot）"""
        assistant_msg = ContextMessage(
            role="assistant",
            content="你好！",
            timestamp=datetime.now(),
            token_count=3,
            source="assistant",
            metadata={"message_id": "6283"},
        )

        buffer = MagicMock()
        buffer.get_context.return_value = [assistant_msg]

        metadata = {}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert metadata["reply_content"] == "你好！"

    def test_backfill_exception_handled(self):
        """测试 get_context 抛异常时不崩溃"""
        buffer = MagicMock()
        buffer.get_context.side_effect = Exception("buffer error")

        metadata = {}
        _backfill_reply_from_buffer(buffer, "group123", "6283", metadata)

        assert "reply_content" not in metadata


class TestHandleWithReplyBackfill:
    """测试回复消息入队时自动回填"""

    @pytest.mark.asyncio
    async def test_handle_reply_backfill_from_buffer(self):
        """测试平台未提供 reply_content 时从 L1 Buffer 回填"""
        event = MagicMock()
        event.message_str = "我也觉得"

        original_msg = ContextMessage(
            role="user",
            content="你好啊",
            timestamp=datetime.now(),
            token_count=3,
            source="1234567",
            metadata={"message_id": "6283", "user_name": "张三"},
        )

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = [original_msg]

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1000"}
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        adapter.get_msg_by_id = AsyncMock(return_value=ReplyInfo())

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert call_kwargs["metadata"]["reply_content"] == "你好啊"
        assert call_kwargs["metadata"]["reply_user_name"] == "张三"
        adapter.get_msg_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_reply_no_backfill_when_content_provided(self):
        """测试平台已提供 reply_content 时不触发回填"""
        event = MagicMock()
        event.message_str = "我也觉得"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1000"}
        adapter.get_reply_info.return_value = ReplyInfo(
            message_id="6283", content="平台提供的内容"
        )

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_content"] == "平台提供的内容"
        buffer.get_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_id_not_stored_when_empty(self):
        """测试 message_id 为空时不存入 metadata"""
        event = MagicMock()
        event.message_str = "你好"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "测试用户"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {}
        adapter.get_reply_info.return_value = ReplyInfo()

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert "message_id" not in call_kwargs["metadata"]


class TestHandleWithApiBackfill:
    """测试 L1 Buffer 回填失败后通过平台 API 回填"""

    @pytest.mark.asyncio
    async def test_api_backfill_success(self):
        """测试 L1 Buffer 无结果但 API 回填成功"""
        event = MagicMock()
        event.message_str = "是的"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1001"}
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        adapter.get_msg_by_id = AsyncMock(
            return_value=ReplyInfo(
                message_id="6283",
                user_id="1234567",
                user_name="张三",
                content="你好啊",
            )
        )

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert call_kwargs["metadata"]["reply_content"] == "你好啊"
        assert call_kwargs["metadata"]["reply_user_name"] == "张三"
        assert call_kwargs["metadata"]["reply_user_id"] == "1234567"
        adapter.get_msg_by_id.assert_called_once_with(event, "6283")

    @pytest.mark.asyncio
    async def test_api_backfill_partial(self):
        """测试 API 只返回部分信息时正确回填"""
        event = MagicMock()
        event.message_str = "是的"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1001"}
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        adapter.get_msg_by_id = AsyncMock(
            return_value=ReplyInfo(
                message_id="6283",
                content="你好啊",
            )
        )

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_content"] == "你好啊"
        assert "reply_user_name" not in call_kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_api_backfill_failure_keeps_degraded(self):
        """测试 API 也失败时 metadata 中只有 reply_message_id"""
        event = MagicMock()
        event.message_str = "是的"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = ""
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1001"}
        adapter.get_reply_info.return_value = ReplyInfo(message_id="6283")
        adapter.get_msg_by_id = AsyncMock(return_value=ReplyInfo())

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_message_id"] == "6283"
        assert "reply_content" not in call_kwargs["metadata"]
        assert "reply_user_name" not in call_kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_api_backfill_does_not_override_existing(self):
        """测试 API 回填不覆盖已有字段"""
        event = MagicMock()
        event.message_str = "是的"

        buffer = MagicMock()
        buffer.is_available = True
        buffer.add_message = AsyncMock()
        buffer.get_context.return_value = []

        component_manager = MagicMock()
        component_manager.get_component.return_value = buffer
        component_manager.get_available_component.return_value = buffer

        adapter = MagicMock()
        adapter.get_group_id.return_value = "group123"
        adapter.get_user_id.return_value = "user456"
        adapter.get_user_name.return_value = "李四"
        adapter.get_group_name.return_value = ""
        adapter.get_raw_message.return_value = {"message_id": "1001"}
        adapter.get_reply_info.return_value = ReplyInfo(
            message_id="6283",
            user_name="平台提供的名字",
        )
        adapter.get_msg_by_id = AsyncMock(
            return_value=ReplyInfo(
                message_id="6283",
                user_name="API返回的名字",
                content="API返回的内容",
            )
        )

        with ExitStack() as stack:
            for p in _patch_handle_deps(adapter=adapter):
                stack.enter_context(p)
            await handle_user_message(event, component_manager)

        buffer.add_message.assert_called_once()
        call_kwargs = buffer.add_message.call_args[1]
        assert call_kwargs["metadata"]["reply_user_name"] == "平台提供的名字"
        assert call_kwargs["metadata"]["reply_content"] == "API返回的内容"
