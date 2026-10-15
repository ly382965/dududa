"""
Token 统计管理器测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from iris_memory.llm.token_stats import TokenUsage, TokenStatsManager


class TestTokenUsage:
    def test_init_default_values(self):
        usage = TokenUsage()
        assert usage.total_input_tokens == 0
        assert usage.total_output_tokens == 0
        assert usage.total_calls == 0

    def test_total_tokens_property(self):
        usage = TokenUsage(
            total_input_tokens=100, total_output_tokens=50, total_calls=1
        )
        assert usage.total_tokens == 150

    def test_to_dict(self):
        usage = TokenUsage(
            total_input_tokens=100, total_output_tokens=50, total_calls=1
        )
        data = usage.to_dict()
        assert data == {
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_calls": 1,
        }

    def test_from_dict(self):
        data = {"total_input_tokens": 100, "total_output_tokens": 50, "total_calls": 1}
        usage = TokenUsage.from_dict(data)
        assert usage.total_input_tokens == 100
        assert usage.total_output_tokens == 50
        assert usage.total_calls == 1

    def test_from_dict_partial(self):
        data = {"total_input_tokens": 100}
        usage = TokenUsage.from_dict(data)
        assert usage.total_input_tokens == 100
        assert usage.total_output_tokens == 0
        assert usage.total_calls == 0


class TestTokenStatsManager:
    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock()
        storage.get_kv_data = AsyncMock(return_value={})
        storage.put_kv_data = AsyncMock()
        storage.delete_kv_data = AsyncMock()
        return storage

    @pytest.fixture
    def manager(self, mock_storage):
        return TokenStatsManager(mock_storage)

    @pytest.mark.asyncio
    async def test_init(self, manager):
        assert manager._storage is not None
        assert manager._cache is not None

    @pytest.mark.asyncio
    async def test_record_usage_module(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)

        module_stats = manager._cache["l1_summarizer"]
        assert module_stats.total_input_tokens == 100
        assert module_stats.total_output_tokens == 50
        assert module_stats.total_calls == 1

        global_stats = manager._cache["global"]
        assert global_stats.total_input_tokens == 100
        assert global_stats.total_output_tokens == 50
        assert global_stats.total_calls == 1

    @pytest.mark.asyncio
    async def test_record_usage_multiple_times(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)
        await manager.record_usage("l1_summarizer", 200, 100)

        module_stats = manager._cache["l1_summarizer"]
        assert module_stats.total_input_tokens == 300
        assert module_stats.total_output_tokens == 150
        assert module_stats.total_calls == 2

    @pytest.mark.asyncio
    async def test_record_usage_different_modules(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)
        await manager.record_usage("l3_kg_extraction", 200, 100)

        l1_stats = manager._cache["l1_summarizer"]
        assert l1_stats.total_tokens == 150

        l3_stats = manager._cache["l3_kg_extraction"]
        assert l3_stats.total_tokens == 300

        global_stats = manager._cache["global"]
        assert global_stats.total_tokens == 450
        assert global_stats.total_calls == 2

    @pytest.mark.asyncio
    async def test_get_stats(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)

        stats = await manager.get_stats("l1_summarizer")
        assert stats.total_input_tokens == 100
        assert stats.total_output_tokens == 50
        assert stats.total_calls == 1

    @pytest.mark.asyncio
    async def test_get_stats_global(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)

        stats = await manager.get_stats("global")
        assert stats.total_tokens == 150

    @pytest.mark.asyncio
    async def test_reset_stats(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)

        await manager.reset_stats("l1_summarizer")

        stats = await manager.get_stats("l1_summarizer")
        assert stats.total_tokens == 0
        assert stats.total_calls == 0

    @pytest.mark.asyncio
    async def test_get_all_stats(self, manager):
        await manager.record_usage("l1_summarizer", 100, 50)
        await manager.record_usage("l3_kg_extraction", 200, 100)

        all_stats = await manager.get_all_stats()

        assert "l1_summarizer" in all_stats
        assert "l3_kg_extraction" in all_stats
        assert "global" in all_stats

    @pytest.mark.asyncio
    async def test_kv_storage_persistence(self, manager, mock_storage):
        await manager.record_usage("l1_summarizer", 100, 50)

        assert mock_storage.put_kv_data.called

        keys = [call[0][0] for call in mock_storage.put_kv_data.call_args_list]
        assert "token_stats:module:l1_summarizer" in keys
        assert "token_stats:global" in keys
