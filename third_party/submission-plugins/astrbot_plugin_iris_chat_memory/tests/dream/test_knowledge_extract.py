"""
KnowledgeExtractPhase 知识提取测试

测试核心功能：
- 未处理记忆筛选
- 记忆分组
- 实体关系提取
- L3 写入
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from iris_memory.dream.knowledge_extract import KnowledgeExtractPhase


def _mock_config():
    mock = Mock()
    mock.get = Mock(
        side_effect=lambda key, default=None: {
            "dream_knowledge_extract_min_unprocessed": 10,
            "dream_knowledge_extract_batch_size": 20,
            "isolation_config.enable_group_memory_isolation": False,
        }.get(key, default)
    )
    return mock


class TestKnowledgeExtractPhase:
    @pytest.fixture
    def phase(self):
        return KnowledgeExtractPhase()

    @pytest.mark.asyncio
    async def test_execute_l3_unavailable(self, phase):
        l2 = Mock()
        l2.is_available = True
        l3 = Mock()
        l3.is_available = False
        llm = Mock()

        with patch(
            "iris_memory.dream.knowledge_extract.get_config",
            return_value=_mock_config(),
        ):
            result = await phase.execute(l2, l3, llm)

        assert result["memories_processed"] == 0
        assert result["nodes_extracted"] == 0

    @pytest.mark.asyncio
    async def test_execute_no_llm(self, phase):
        l2 = Mock()
        l2.is_available = True
        l3 = Mock()
        l3.is_available = True
        llm = None

        with patch(
            "iris_memory.dream.knowledge_extract.get_config",
            return_value=_mock_config(),
        ):
            result = await phase.execute(l2, l3, llm)

        assert result["memories_processed"] == 0
        assert result["nodes_extracted"] == 0

    @pytest.mark.asyncio
    async def test_execute_no_unprocessed(self, phase):
        l2 = Mock()
        l2.is_available = True
        l2.get_unprocessed_count = AsyncMock(return_value=3)
        l3 = Mock()
        l3.is_available = True
        llm = Mock()

        with patch(
            "iris_memory.dream.knowledge_extract.get_config",
            return_value=_mock_config(),
        ):
            result = await phase.execute(l2, l3, llm)

        assert result["memories_processed"] == 0
