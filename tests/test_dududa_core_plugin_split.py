from __future__ import annotations

import ast
import asyncio
import importlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "plugins" / "astrbot_plugin_dududa_core" / "main.py"
COMMANDS = ROOT / "plugins" / "astrbot_plugin_dududa_core" / "commands"
COURSE_COMMANDS = COMMANDS / "course.py"


EXPECTED_HANDLERS = (
    ("controlled_rollout", "self, event: AstrMessageEvent", "filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)"),
    ("natural_course_query", "self, event: AstrMessageEvent", "filter.event_message_type(filter.EventMessageType.ALL, priority=8)"),
    ("help", "self, event: AstrMessageEvent, module: str | None=None", "filter.command('help')"),
    ("dududa", "self", "filter.command_group('dududa', alias={'嘟嘟哒'})"),
    ("dududa_help", "self, event: AstrMessageEvent, module: str | None=None", "dududa.command('help')"),
    ("about", "self, event: AstrMessageEvent", "filter.command('about')"),
    ("ping", "self, event: AstrMessageEvent", "filter.command('ping')"),
    ("status", "self, event: AstrMessageEvent", "filter.command('status')"),
    ("privacy", "self, event: AstrMessageEvent", "filter.command('privacy')"),
    ("remember", "self, event: AstrMessageEvent, content: GreedyStr", "filter.command('remember')"),
    ("forget", "self, event: AstrMessageEvent, keyword: GreedyStr", "filter.command('forget')"),
    ("memory", "self, event: AstrMessageEvent, action: str | None=None", "filter.command('memory')"),
    ("style", "self, event: AstrMessageEvent, mode: str", "filter.command('style')"),
    ("course", "self", "filter.command_group('course')"),
    ("course_stats", "self, event: AstrMessageEvent", "course.command('stats')"),
    ("course_search", "self, event: AstrMessageEvent, query: GreedyStr", "course.command('search')"),
    ("course_review", "self, event: AstrMessageEvent, query: GreedyStr", "course.command('review')"),
    ("course_compare", "self, event: AstrMessageEvent, query: GreedyStr", "course.command('compare')"),
    ("course_refresh", "self, event: AstrMessageEvent, course_id: int", "course.command('refresh')"),
    ("admin", "self", "filter.command_group('admin')"),
    ("admin_status", "self, event: AstrMessageEvent", "admin.command('status')"),
    ("admin_plugins", "self, event: AstrMessageEvent", "admin.command('plugins')"),
    ("admin_mcp", "self, event: AstrMessageEvent, action: str='list', name: str | None=None", "admin.command('mcp')"),
    ("admin_group", "self, event: AstrMessageEvent, action: str, value: str | None=None", "admin.command('group')"),
    ("admin_user", "self, event: AstrMessageEvent, action: str, qq: str", "admin.command('user')"),
    ("admin_memory", "self, event: AstrMessageEvent, action: str", "admin.command('memory')"),
    ("admin_logs", "self, event: AstrMessageEvent, action: str='errors', value: str | None=None", "admin.command('logs')"),
    ("admin_backup", "self, event: AstrMessageEvent, action: str='create'", "admin.command('backup')"),
    ("admin_restart", "self, event: AstrMessageEvent, service: str", "admin.command('restart')"),
    ("admin_model", "self, event: AstrMessageEvent, action: str='route', scene: str | None=None, model: str | None=None", "admin.command('model')"),
    ("admin_permission", "self, event: AstrMessageEvent, action: str, qq: str, role: str", "admin.command('permission')"),
    ("admin_broadcast", "self, event: AstrMessageEvent, content: GreedyStr", "admin.command('broadcast')"),
    ("confirm", "self, event: AstrMessageEvent, token: str", "filter.command('confirm')"),
    ("cancel", "self, event: AstrMessageEvent, token: str", "filter.command('cancel')"),
    ("remind", "self, event: AstrMessageEvent, text: GreedyStr", "filter.command('remind')"),
    ("reminders", "self, event: AstrMessageEvent", "filter.command('reminders')"),
    ("summary", "self, event: AstrMessageEvent, scope: str | None=None", "filter.command('summary')"),
    ("meme", "self, event: AstrMessageEvent, keyword: str | None=None", "filter.command('meme')"),
    ("image", "self, event: AstrMessageEvent, prompt: GreedyStr", "filter.command('image')"),
    ("fortune", "self, event: AstrMessageEvent", "filter.command('fortune')"),
    ("draw", "self, event: AstrMessageEvent, topic: GreedyStr", "filter.command('draw')"),
    ("poke", "self, event: AstrMessageEvent", "filter.command('poke')"),
    ("reread", "self, event: AstrMessageEvent", "filter.command('reread')"),
)


def _handler_contract() -> tuple[tuple[str, str, str], ...]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DududaCorePlugin"
    )
    handlers: list[tuple[str, str, str]] = []
    for node in plugin.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(item) for item in node.decorator_list]
        handler_decorators = [
            item
            for item in decorators
            if item.startswith(("filter.", "dududa.", "course.", "admin."))
        ]
        if handler_decorators:
            handlers.append((node.name, ast.unparse(node.args), handler_decorators[0]))
    return tuple(handlers)


class DududaCorePluginSplitTests(unittest.TestCase):
    def test_course_subcommands_gate_before_every_mcp_call(self) -> None:
        tree = ast.parse(COURSE_COMMANDS.read_text(encoding="utf-8"))
        imports_time = any(
            isinstance(node, ast.Import)
            and any(alias.name == "time" for alias in node.names)
            for node in tree.body
        )
        self.assertTrue(imports_time)
        owner = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "CoreCourseCommands"
        )
        methods = {
            node.name: node
            for node in owner.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        for name in (
            "course_stats",
            "course_search",
            "course_review",
            "course_compare",
            "course_refresh",
        ):
            method = methods[name]
            blocked_lines = [
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_blocked"
            ]
            mcp_lines = [
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"call", "_answer_natural_course_query"}
            ]
            self.assertEqual(len(blocked_lines), 1, name)
            self.assertTrue(mcp_lines, name)
            self.assertLess(blocked_lines[0], min(mcp_lines), name)
        refresh = methods["course_refresh"]
        trusted_line = next(
            node.lineno
            for node in ast.walk(refresh)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "is_trusted"
        )
        blocked_line = next(
            node.lineno
            for node in ast.walk(refresh)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_blocked"
        )
        self.assertLess(blocked_line, trusted_line)

    def test_handler_order_signatures_and_decorators_are_stable(self) -> None:
        self.assertEqual(_handler_contract(), EXPECTED_HANDLERS)
        self.assertEqual(len(EXPECTED_HANDLERS), 43)

    def test_plugin_registration_identity_is_stable(self) -> None:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        plugin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DududaCorePlugin"
        )
        self.assertEqual(
            ast.unparse(plugin.decorator_list[0]),
            "register('astrbot_plugin_dududa_core', 'mmdustc', '嘟嘟哒统一命令、权限、课程查询和管理骨架', '0.1.0')",
        )

    def test_main_is_a_thin_wrapper_layer(self) -> None:
        source = MAIN.read_text(encoding="utf-8")
        self.assertLessEqual(len(source.splitlines()), 400)
        self.assertEqual(source.count("async for result in Core"), 39)
        self.assertIn(
            "from .commands.image import CoreImageCommands, ImageGenerationError",
            source,
        )
        self.assertIn(
            "from .lifecycle import CoreLifecycleMixin, PendingAction",
            source,
        )

    def test_command_implementations_do_not_own_astrbot_decorators(self) -> None:
        for path in COMMANDS.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorators = [ast.unparse(item) for item in node.decorator_list]
                self.assertFalse(
                    any(
                        item.startswith(("filter.", "dududa.", "course.", "admin."))
                        for item in decorators
                    ),
                    f"{path.name}:{node.name} owns an AstrBot decorator",
                )

    def test_real_astrbot_registry_keeps_handlers_owned_by_main(self) -> None:
        try:
            from astrbot.core.star.star import star_map
            from astrbot.core.star.star_handler import star_handlers_registry
        except ModuleNotFoundError:
            self.skipTest("AstrBot is only installed in the derived runtime image")

        module = importlib.import_module("astrbot_plugin_dududa_core.main")
        handlers = [
            handler
            for handler in star_handlers_registry
            if handler.handler_module_path == module.__name__
        ]
        self.assertEqual(len(handlers), 43)
        self.assertEqual({handler.handler.__module__ for handler in handlers}, {module.__name__})
        self.assertIn(module.__name__, star_map)
        natural = next(
            handler for handler in handlers if handler.handler_name == "natural_course_query"
        )
        self.assertEqual(natural.extras_configs.get("priority"), 8)
        rollout = next(
            handler for handler in handlers if handler.handler_name == "controlled_rollout"
        )
        self.assertEqual(rollout.extras_configs.get("priority"), 100)

    def test_representative_command_results_and_stop_behavior(self) -> None:
        try:
            module = importlib.import_module("astrbot_plugin_dududa_core.main")
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith("astrbot"):
                self.skipTest("AstrBot is only installed in the derived runtime image")
            raise

        class FakePermissions:
            owners: set[str] = set()
            global_admins: set[str] = set()

            def is_admin(self, event: object) -> bool:
                return False

            def is_owner(self, event: object) -> bool:
                return False

            def is_trusted(self, event: object) -> bool:
                return False

            def is_muted(self, event: object) -> bool:
                return False

            def role(self, event: object) -> str:
                return "user"

        class FakeAudit:
            path = "audit.jsonl"

            def write(self, *args: object) -> None:
                return None

        class FakeEvent:
            message_str = "ordinary text"
            unified_msg_origin = "umo"

            def __init__(self) -> None:
                self.stopped = False

            def get_message_outline(self) -> str:
                return self.message_str

            def get_sender_id(self) -> str:
                return "10001"

            def get_group_id(self) -> str:
                return "20001"

            def plain_result(self, text: str) -> tuple[str, str]:
                return ("plain", text)

            def stop_event(self) -> None:
                self.stopped = True

        plugin = object.__new__(module.DududaCorePlugin)
        plugin.enabled = True
        plugin.perms = FakePermissions()
        plugin.config = {}
        plugin.group_state = {}
        plugin.user_state = {}
        plugin.pending = {}
        plugin.audit = FakeAudit()

        async def invoke(name: str, *args: object) -> tuple[list[object], bool]:
            event = FakeEvent()
            results = [item async for item in getattr(plugin, name)(event, *args)]
            return results, event.stopped

        async def verify() -> None:
            self.assertEqual(
                await invoke("ping"),
                ([("plain", "pong，嘟嘟哒在线。")], True),
            )
            self.assertEqual(
                await invoke("help", "admin"),
                ([("plain", "管理员菜单需要 admin 权限。")], True),
            )
            self.assertEqual(
                await invoke("natural_course_query"),
                ([], False),
            )
            self.assertEqual(
                await invoke("confirm", "NOPE"),
                ([("plain", "没有找到这个确认 token。")], True),
            )
            self.assertEqual(
                await invoke("image", "safe prompt"),
                ([("plain", "gpt-image-2 可用但较慢，当前只开放给 trusted/admin。")], True),
            )

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
