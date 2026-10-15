"""Run real social/statistics handlers against synthetic recording events."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.test_group_plugin_controls import (
    REREAD,
    SUB2,
    GroupPluginControlsTests,
    Plain,
)


async def main():
    harness = GroupPluginControlsTests("runTest")
    await harness.asyncSetUp()
    try:
        harness.set_policy("on")
        plugin = REREAD.RereadPlugin(
            object(),
            {
                "enabled": True,
                "group_whitelist": [],
                "need_different": True,
                "thresholds": {"Plain": 3},
                "reread_prob": 1,
                "interrupt_prob": 0,
            },
        )
        text = "一起聊天，一起变好！"
        counts = []
        for i in range(3):
            event = harness.event(sender=str(201 + i), message=text)
            event.get_messages = lambda: [Plain(text)]
            await plugin.reread_handle(event)
            counts.append(event.send.await_count)
        assert counts == [0, 0, 1]
        reply = event.send.await_args.args[0][0].text
        assert reply == text
        stats = SUB2.Sub2APIReadonlyPlugin(
            object(), {"enabled": True, "group_whitelist": ["101"]}
        )
        stats.client = SimpleNamespace(
            get_system_version=AsyncMock(return_value={"version": "recording-sample"}),
            get_stats=AsyncMock(
                return_value={
                    "stats_stale": False,
                    "stats_updated_at": "2026-09-06 09:00:00",
                    "active_users": 4,
                    "normal_accounts": 3,
                    "total_accounts": 3,
                    "rpm": 8,
                    "tpm": 12000,
                    "average_duration_ms": 850,
                }
            ),
        )
        event = harness.event(message="/sub2api status")
        responses = [x async for x in stats.status(event)]
        assert len(responses) == 1 and "recording-sample" in responses[0]
        result = {
            "passed": True,
            "reread": {
                "mode": "synthetic_events_real_handler",
                "inputs": 3,
                "replyCounts": counts,
                "reply": reply,
            },
            "sub2api": {
                "mode": "synthetic_statistics_real_handler",
                "command": "/sub2api status",
                "reply": responses[0],
            },
        }
        p = ROOT.parent / "dududa-recording-state/reports/plugin-samples.json"
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"passed": True, "report": str(p)}, ensure_ascii=False))
    finally:
        await harness.asyncTearDown()
        harness.doCleanups()


if __name__ == "__main__":
    asyncio.run(main())
