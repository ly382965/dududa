"""LLM status alert parsers and alert state machine (inline fixtures, no network)."""

import asyncio
import unittest
from unittest.mock import patch

from dududa_v3.features import status_alerts as sa

ANTHROPIC_DOWN = {
    "page": {"id": "x", "name": "Claude", "url": "https://status.claude.com"},
    "status": {"indicator": "major", "description": "Partial System Outage"},
    "components": [{"name": "Claude API (api.anthropic.com)", "status": "partial_outage", "group": False},
                   {"name": "claude.ai", "status": "operational", "group": False},
                   {"name": "Group", "status": "partial_outage", "group": True}],
    "incidents": [{"id": "inc1", "name": "Elevated errors on Claude Opus", "status": "investigating",
                   "impact": "major", "shortlink": "https://stspg.io/abc",
                   "components": [{"name": "Claude API (api.anthropic.com)"}],
                   "incident_updates": [{"body": "We are investigating elevated errors."}]}],
    "scheduled_maintenances": [{"id": "m1", "name": "Planned DB work", "status": "scheduled", "impact": "maintenance"}],
}

OPENAI_SUMMARY = {"page": {"name": "OpenAI"}, "status": {"indicator": "none", "description": "All Systems Operational"},
                  "components": [{"name": "Login", "status": "operational"}, {"name": "Login", "status": "operational"}]}
OPENAI_INCIDENTS = {"incidents": [
    {"id": "01OLD", "name": "Old thing", "status": "resolved", "impact": "minor"},
    {"id": "01NEW", "name": "Codex degraded", "status": "identified", "impact": "minor",
     "components": [{"name": "Codex Web"}], "incident_updates": [{"body": "Fix in progress"}]},
]}

DEEPSEEK_ACTIVE = {"request_id": "r", "data": {"page": {"name": "DeepSeek"}, "active_changes": [
    {"change_id": 7116348214287, "type": "incident", "title": "DeepSeek API 部分中断", "status": "investigating",
     "description": "正在排查", "affected_components": [
         {"name": "DeepSeek V4 Pro API服务(API Service)", "status": "partial_outage"},
         {"name": "对话服务(Chat Service)", "status": "degraded"}]},
    {"change_id": 1, "type": "incident", "title": "done", "status": "resolved", "affected_components": []},
]}}


class ParserTests(unittest.TestCase):
    def test_statuspage_summary(self):
        snap = sa.parse_statuspage(ANTHROPIC_DOWN, None, "https://status.claude.com/")
        self.assertEqual(snap["indicator"], "major")
        self.assertEqual(snap["components"], [{"name": "Claude API (api.anthropic.com)", "status": "partial_outage"}])
        [incident] = snap["incidents"]   # Scheduled (not in-progress) maintenance is ignored.
        self.assertEqual((incident["id"], incident["status"], incident["url"]),
                         ("inc1", "investigating", "https://stspg.io/abc"))
        self.assertEqual(incident["update"], "We are investigating elevated errors.")

    def test_openai_merges_incident_list(self):
        snap = sa.parse_statuspage(OPENAI_SUMMARY, OPENAI_INCIDENTS, "https://status.openai.com/")
        self.assertEqual([i["id"] for i in snap["incidents"]], ["01NEW"])
        self.assertEqual(snap["incidents"][0]["url"], "https://status.openai.com/incidents/01NEW")
        self.assertEqual(snap["indicator"], "minor")   # Raised from "none" by the active incident.
        self.assertEqual(snap["components"], [])

    def test_flashcat(self):
        snap = sa.parse_flashcat(DEEPSEEK_ACTIVE, "https://status.deepseek.com/")
        self.assertEqual(snap["indicator"], "major")
        self.assertEqual([i["id"] for i in snap["incidents"]], ["7116348214287"])
        self.assertEqual(len(snap["components"]), 2)
        self.assertEqual(sa.parse_flashcat({"data": {"active_changes": []}}, "u")["indicator"], "none")


class FakeCtx:
    def __init__(self, targets):
        self.kv, self.pushed, self.targets = {}, [], targets

    def config(self, feature):
        return {"targets": self.targets}

    def kv_get(self, feature, key, default=None):
        return self.kv.get((feature, key), default)

    def kv_set(self, feature, key, value):
        self.kv[(feature, key)] = value

    def push(self, scope, reply, *, dedupe=None):
        if any(d == dedupe for _, _, d in self.pushed):
            return False
        self.pushed.append((scope, reply.plain_text, dedupe))
        return True


OK = {"indicator": "none", "description": "", "components": [], "incidents": []}


class JobTests(unittest.TestCase):
    def tick(self, ctx, anthropic):
        snaps = {"openai": OK, "anthropic": anthropic, "deepseek": {"error": "网络请求失败：URLError"}}
        with patch.object(sa, "fetch_all", return_value=snaps):
            asyncio.run(sa.alert_job(ctx))

    def test_baseline_alert_update_and_recovery(self):
        ctx = FakeCtx(["qq-1/qq-1:group:100"])
        down = sa.parse_statuspage(ANTHROPIC_DOWN, None, "https://status.claude.com/")
        self.tick(ctx, down)
        self.assertEqual(ctx.pushed, [])                       # First run records the baseline only.
        self.assertNotIn(("status_alerts", "state:deepseek"), ctx.kv)  # Fetch errors never become state.
        self.tick(ctx, OK)
        [(scope, text, dedupe)] = ctx.pushed
        self.assertEqual(scope, "qq-1/qq-1:group:100")
        self.assertIn("Anthropic 服务恢复", text)
        self.assertIn("已解决：Elevated errors on Claude Opus", text)
        self.assertEqual(dedupe, "status:anthropic:inc1:resolved@qq-1/qq-1:group:100")
        self.tick(ctx, down)
        self.assertIn("新事件：Elevated errors on Claude Opus（调查中）", ctx.pushed[-1][1])
        self.assertIn("影响：Claude API (api.anthropic.com)", ctx.pushed[-1][1])
        monitoring = {**down, "incidents": [{**down["incidents"][0], "status": "monitoring"}]}
        self.tick(ctx, monitoring)
        self.assertIn("事件进展：Elevated errors on Claude Opus → 观察中", ctx.pushed[-1][1])
        count = len(ctx.pushed)
        self.tick(ctx, monitoring)
        self.assertEqual(len(ctx.pushed), count)               # No change, no message.

    def test_indicator_only_degradation(self):
        events = sa.diff_events("openai", OK, {**OK, "indicator": "minor"})
        self.assertEqual([e["kind"] for e in events], ["degraded"])
        events = sa.diff_events("openai", {**OK, "indicator": "minor"}, OK)
        self.assertEqual([e["kind"] for e in events], ["recovered"])
        self.assertEqual(sa.diff_events("openai", {**OK, "indicator": "minor"}, {**OK, "indicator": "major"}), [])

    def test_no_targets_still_tracks_state(self):
        ctx = FakeCtx([])
        self.tick(ctx, OK)
        self.tick(ctx, sa.parse_statuspage(ANTHROPIC_DOWN, None, "u"))
        self.assertEqual(ctx.pushed, [])
        self.assertEqual(ctx.kv[("status_alerts", "state:anthropic")]["indicator"], "major")


if __name__ == "__main__":
    unittest.main()
