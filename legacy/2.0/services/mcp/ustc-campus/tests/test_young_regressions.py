from __future__ import annotations

import asyncio
import sys
import unittest
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from ustc_campus_mcp.young import YoungClient


class Client(YoungClient):
    @asynccontextmanager
    async def _service(self):
        yield


class YoungRegressions(unittest.TestCase):
    def test_detail_supplies_data_for_singleton_constructor(self):
        seen = []

        class Activity:
            def __init__(self, identifier, *, data):
                seen.append((identifier, data))
                self.id = identifier
                self.data = {"itemName": "固定讲座", "itemStatus": 26}

            update = AsyncMock()
            get_children = AsyncMock(return_value=[])
            status = SimpleNamespace(text="报名中")

        module = ModuleType("pyustc.young")
        module.SecondClass = Activity
        with patch.dict(sys.modules, {"pyustc.young": module}):
            result = asyncio.run(
                Client("user", "secret").get_activity("activity-1", True)
            )
        self.assertEqual(seen, [("activity-1", {})])
        self.assertTrue(result["ok"])
        self.assertEqual(result["activity"]["name"], "固定讲座")

    def test_department_tree_is_bounded_without_claiming_complete_coverage(self):
        children = [
            SimpleNamespace(id=str(i), name=f"部门{i}", level=1, children=[])
            for i in range(162)
        ]
        root = SimpleNamespace(id="root", name="学校", level=0, children=children)
        module = ModuleType("pyustc.young")
        module.Department = SimpleNamespace(get_root_dept=AsyncMock(return_value=root))
        module.Module = module.Label = object
        with patch.dict(sys.modules, {"pyustc.young": module}):
            result = asyncio.run(Client("user", "secret").list_facets("department"))
        self.assertEqual(len(result["items"]), 100)
        self.assertEqual(result["total"], 163)
