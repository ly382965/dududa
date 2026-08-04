from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .commands.admin import CoreAdminCommands
from .commands.basic import CoreBasicCommands
from .commands.compatibility import CoreCompatibilityCommands
from .commands.course import CoreCourseCommands
from .commands.image import CoreImageCommands, ImageGenerationError  # noqa: F401
from .commands.memory import CoreMemoryCommands
from .composition import initialize_plugin
from .lifecycle import CoreLifecycleMixin, PendingAction  # noqa: F401


@register(
    "astrbot_plugin_dududa_core",
    "mmdustc",
    "嘟嘟哒统一命令、权限、课程查询和管理骨架",
    "0.1.0",
)
class DududaCorePlugin(
    CoreLifecycleMixin,
    CoreCourseCommands,
    CoreBasicCommands,
    CoreMemoryCommands,
    CoreAdminCommands,
    CoreCompatibilityCommands,
    CoreImageCommands,
    Star,
):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        initialize_plugin(self, config)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def controlled_rollout(self, event: AstrMessageEvent):
        """受控执行显式提及的 shadow/canary。"""
        await self._handle_controlled_rollout(event)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=8)
    async def natural_course_query(self, event: AstrMessageEvent):
        """把明确的自然语言评课请求路由到 icourse MCP。"""
        async for result in CoreCourseCommands.natural_course_query(self, event):
            yield result

    @filter.command("help")
    async def help(self, event: AstrMessageEvent, module: str | None=None):
        """查看嘟嘟哒帮助"""
        async for result in CoreBasicCommands.help(self, event, module):
            yield result

    @filter.command_group("dududa", alias={"嘟嘟哒"})
    def dududa(self):
        """嘟嘟哒核心命令组"""
        pass

    @dududa.command("help")
    async def dududa_help(self, event: AstrMessageEvent, module: str | None=None):
        """查看嘟嘟哒帮助"""
        async for result in CoreBasicCommands.dududa_help(self, event, module):
            yield result

    @filter.command("about")
    async def about(self, event: AstrMessageEvent):
        """查看嘟嘟哒介绍"""
        async for result in CoreBasicCommands.about(self, event):
            yield result

    @filter.command("ping")
    async def ping(self, event: AstrMessageEvent):
        """测试在线状态"""
        async for result in CoreBasicCommands.ping(self, event):
            yield result

    @filter.command("status")
    async def status(self, event: AstrMessageEvent):
        """查看可见运行状态"""
        async for result in CoreBasicCommands.status(self, event):
            yield result

    @filter.command("privacy")
    async def privacy(self, event: AstrMessageEvent):
        """查看隐私说明"""
        async for result in CoreBasicCommands.privacy(self, event):
            yield result

    @filter.command("remember")
    async def remember(self, event: AstrMessageEvent, content: GreedyStr):
        """让嘟嘟哒记住一件事"""
        async for result in CoreMemoryCommands.remember(self, event, content):
            yield result

    @filter.command("forget")
    async def forget(self, event: AstrMessageEvent, keyword: GreedyStr):
        """删除自己的相关记忆"""
        async for result in CoreMemoryCommands.forget(self, event, keyword):
            yield result

    @filter.command("memory")
    async def memory(self, event: AstrMessageEvent, action: str | None=None):
        """查看或管理自己的记忆"""
        async for result in CoreMemoryCommands.memory(self, event, action):
            yield result

    @filter.command("style")
    async def style(self, event: AstrMessageEvent, mode: str):
        """设置回复偏好"""
        async for result in CoreMemoryCommands.style(self, event, mode):
            yield result

    @filter.command_group("course")
    def course(self):
        """课程与评课命令组"""
        pass

    @course.command("stats")
    async def course_stats(self, event: AstrMessageEvent):
        """查看课程缓存规模"""
        async for result in CoreCourseCommands.course_stats(self, event):
            yield result

    @course.command("search")
    async def course_search(self, event: AstrMessageEvent, query: GreedyStr):
        """搜索课程"""
        async for result in CoreCourseCommands.course_search(self, event, query):
            yield result

    @course.command("review")
    async def course_review(self, event: AstrMessageEvent, query: GreedyStr):
        """总结公开评课"""
        async for result in CoreCourseCommands.course_review(self, event, query):
            yield result

    @course.command("compare")
    async def course_compare(self, event: AstrMessageEvent, query: GreedyStr):
        """比较两个课程或老师"""
        async for result in CoreCourseCommands.course_compare(self, event, query):
            yield result

    @course.command("refresh")
    async def course_refresh(self, event: AstrMessageEvent, course_id: int):
        """刷新单门课程缓存"""
        async for result in CoreCourseCommands.course_refresh(self, event, course_id):
            yield result

    @filter.command_group("admin")
    def admin(self):
        """管理员命令组"""
        pass

    @admin.command("status")
    async def admin_status(self, event: AstrMessageEvent):
        """查看管理状态"""
        async for result in CoreAdminCommands.admin_status(self, event):
            yield result

    @admin.command("plugins")
    async def admin_plugins(self, event: AstrMessageEvent):
        """查看插件列表"""
        async for result in CoreAdminCommands.admin_plugins(self, event):
            yield result

    @admin.command("mcp")
    async def admin_mcp(self, event: AstrMessageEvent, action: str='list', name: str | None=None):
        """管理 MCP"""
        async for result in CoreAdminCommands.admin_mcp(self, event, action, name):
            yield result

    @admin.command("group")
    async def admin_group(self, event: AstrMessageEvent, action: str, value: str | None=None):
        """设置群模式和概率"""
        async for result in CoreAdminCommands.admin_group(self, event, action, value):
            yield result

    @admin.command("user")
    async def admin_user(self, event: AstrMessageEvent, action: str, qq: str):
        """限制或解除用户"""
        async for result in CoreAdminCommands.admin_user(self, event, action, qq):
            yield result

    @admin.command("memory")
    async def admin_memory(self, event: AstrMessageEvent, action: str):
        """管理记忆"""
        async for result in CoreAdminCommands.admin_memory(self, event, action):
            yield result

    @admin.command("logs")
    async def admin_logs(self, event: AstrMessageEvent, action: str='errors', value: str | None=None):
        """查看脱敏日志摘要"""
        async for result in CoreAdminCommands.admin_logs(self, event, action, value):
            yield result

    @admin.command("backup")
    async def admin_backup(self, event: AstrMessageEvent, action: str='create'):
        """创建配置备份"""
        async for result in CoreAdminCommands.admin_backup(self, event, action):
            yield result

    @admin.command("restart")
    async def admin_restart(self, event: AstrMessageEvent, service: str):
        """重启服务提示"""
        async for result in CoreAdminCommands.admin_restart(self, event, service):
            yield result

    @admin.command("model")
    async def admin_model(self, event: AstrMessageEvent, action: str='route', scene: str | None=None, model: str | None=None):
        """查看模型路由"""
        async for result in CoreAdminCommands.admin_model(self, event, action, scene, model):
            yield result

    @admin.command("permission")
    async def admin_permission(self, event: AstrMessageEvent, action: str, qq: str, role: str):
        """修改全局权限"""
        async for result in CoreAdminCommands.admin_permission(self, event, action, qq, role):
            yield result

    @admin.command("broadcast")
    async def admin_broadcast(self, event: AstrMessageEvent, content: GreedyStr):
        """申请群发"""
        async for result in CoreAdminCommands.admin_broadcast(self, event, content):
            yield result

    @filter.command("confirm")
    async def confirm(self, event: AstrMessageEvent, token: str):
        """确认高风险操作"""
        async for result in CoreAdminCommands.confirm(self, event, token):
            yield result

    @filter.command("cancel")
    async def cancel(self, event: AstrMessageEvent, token: str):
        """取消高风险操作"""
        async for result in CoreAdminCommands.cancel(self, event, token):
            yield result

    @filter.command("remind")
    async def remind(self, event: AstrMessageEvent, text: GreedyStr):
        """提醒入口"""
        async for result in CoreCompatibilityCommands.remind(self, event, text):
            yield result

    @filter.command("reminders")
    async def reminders(self, event: AstrMessageEvent):
        """查看提醒入口"""
        async for result in CoreCompatibilityCommands.reminders(self, event):
            yield result

    @filter.command("summary")
    async def summary(self, event: AstrMessageEvent, scope: str | None=None):
        """群聊总结入口"""
        async for result in CoreCompatibilityCommands.summary(self, event, scope):
            yield result

    @filter.command("meme")
    async def meme(self, event: AstrMessageEvent, keyword: str | None=None):
        """表情包入口"""
        async for result in CoreCompatibilityCommands.meme(self, event, keyword):
            yield result

    @filter.command("image")
    async def image(self, event: AstrMessageEvent, prompt: GreedyStr):
        """生成图片"""
        async for result in CoreImageCommands.image(self, event, prompt):
            yield result

    @filter.command("fortune")
    async def fortune(self, event: AstrMessageEvent):
        """今日运势"""
        async for result in CoreCompatibilityCommands.fortune(self, event):
            yield result

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent, topic: GreedyStr):
        """抽签"""
        async for result in CoreCompatibilityCommands.draw(self, event, topic):
            yield result

    @filter.command("poke")
    async def poke(self, event: AstrMessageEvent):
        """戳一戳入口"""
        async for result in CoreCompatibilityCommands.poke(self, event):
            yield result

    @filter.command("reread")
    async def reread(self, event: AstrMessageEvent):
        """复读入口"""
        async for result in CoreCompatibilityCommands.reread(self, event):
            yield result
