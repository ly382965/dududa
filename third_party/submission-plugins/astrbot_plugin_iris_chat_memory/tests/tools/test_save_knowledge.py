"""SaveKnowledgeTool 测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock

from iris_memory.tools import SaveKnowledgeTool
from iris_memory.l3_kg import L3KGAdapter


@pytest.fixture
def tool():
    return SaveKnowledgeTool()


@pytest.fixture
def mock_adapter():
    adapter = MagicMock(spec=L3KGAdapter)
    adapter._is_available = True
    adapter.add_node = AsyncMock(return_value=True)
    adapter.add_edge = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def mock_component_manager(mock_adapter):
    manager = MagicMock()
    manager.get_component = MagicMock(return_value=mock_adapter)
    return manager


@pytest.fixture
def mock_context():
    context = Mock()
    event = Mock()
    inner_context = Mock()
    inner_context.event = event
    context.context = inner_context
    return context


@pytest.mark.asyncio
async def test_save_knowledge_basic(
    tool, mock_context, mock_component_manager, monkeypatch
):
    monkeypatch.setattr(
        "iris_memory.tools.save_knowledge.get_component_manager",
        lambda: mock_component_manager,
    )
    monkeypatch.setattr("iris_memory.utils.sanitize_input", lambda x, source="": x)

    mock_platform_adapter = Mock()
    mock_platform_adapter.get_group_id = Mock(return_value="group_1")
    monkeypatch.setattr(
        "iris_memory.platform.get_adapter", Mock(return_value=mock_platform_adapter)
    )
    mock_config = Mock()
    mock_config.get = Mock(return_value=False)
    monkeypatch.setattr("iris_memory.config.get_config", lambda: mock_config)

    nodes = [
        {
            "label": "Person",
            "name": "Alice",
            "content": "Alice is a software engineer",
            "confidence": 0.9,
        }
    ]

    result = await tool.call(mock_context, nodes=nodes, edges=[])

    assert "成功保存" in result
    assert "1 个节点" in result


@pytest.mark.asyncio
async def test_save_knowledge_with_edges(
    tool, mock_context, mock_component_manager, monkeypatch
):
    monkeypatch.setattr(
        "iris_memory.tools.save_knowledge.get_component_manager",
        lambda: mock_component_manager,
    )
    monkeypatch.setattr("iris_memory.utils.sanitize_input", lambda x, source="": x)

    mock_platform_adapter = Mock()
    mock_platform_adapter.get_group_id = Mock(return_value="group_1")
    monkeypatch.setattr(
        "iris_memory.platform.get_adapter", Mock(return_value=mock_platform_adapter)
    )
    mock_config = Mock()
    mock_config.get = Mock(return_value=False)
    monkeypatch.setattr("iris_memory.config.get_config", lambda: mock_config)

    nodes = [
        {
            "label": "Person",
            "name": "Alice",
            "content": "Alice is a software engineer",
            "confidence": 0.9,
        },
        {
            "label": "Event",
            "name": "Conference",
            "content": "AI Conference 2024",
            "confidence": 0.8,
        },
    ]

    edges = [
        {
            "source_name": "Alice",
            "target_name": "Conference",
            "relation_type": "ATTENDED",
            "confidence": 0.85,
        }
    ]

    result = await tool.call(mock_context, nodes=nodes, edges=edges)

    assert "成功保存" in result
    assert "2 个节点" in result
    assert "1 条边" in result


@pytest.mark.asyncio
async def test_save_knowledge_empty_nodes(
    tool, mock_context, mock_component_manager, monkeypatch
):
    monkeypatch.setattr(
        "iris_memory.tools.save_knowledge.get_component_manager",
        lambda: mock_component_manager,
    )
    monkeypatch.setattr("iris_memory.utils.sanitize_input", lambda x, source="": x)

    result = await tool.call(mock_context, nodes=[], edges=[])

    assert "未提供任何节点" in result


@pytest.mark.asyncio
async def test_save_knowledge_adapter_unavailable(tool, mock_context, monkeypatch):
    mock_manager = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter._is_available = False
    mock_manager.get_component = MagicMock(return_value=mock_adapter)

    monkeypatch.setattr(
        "iris_memory.tools.save_knowledge.get_component_manager", lambda: mock_manager
    )
    monkeypatch.setattr("iris_memory.utils.sanitize_input", lambda x, source="": x)

    result = await tool.call(
        mock_context,
        nodes=[{"label": "Person", "name": "Alice", "content": "Test"}],
        edges=[],
    )

    assert "知识图谱不可用" in result
