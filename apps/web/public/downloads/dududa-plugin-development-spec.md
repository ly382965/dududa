# Dududa 2.0 插件开发规范

> 规范标识：`DUDUDA-PLUGIN-SPEC 1.0.0`  
> 目标环境：Dududa 2.0、AstrBot 4.26.2、QQ 个人号适配器 `aiocqhttp`  
> 文档用途：供插件作者、代码审查者和生成插件代码的 AI 共同使用

## 1. 如何使用本规范

本文同时规定 AstrBot 的可加载格式和 Dududa 的接入边界。一个插件满足 AstrBot 格式，
只能说明它可以被安装和加载；这不等于它已经成为 Dududa Agent 可以自动选择的能力。

本文中的关键词含义如下：

- **必须（MUST）**：不满足时，插件不得作为合格的 Dududa 插件交付。
- **禁止（MUST NOT）**：任何情况下都不能这样实现。
- **应该（SHOULD）**：默认遵守；偏离时应在 README 中说明理由。
- **可以（MAY）**：按功能需要选用。

本规范优先保证插件能被实际安装、热加载和使用，不要求为普通插件额外建立哈希、冻结
Contract、全仓 Baseline 或新的发布 Gate。认证、凭据、不可逆操作和真实外部副作用仍按项目
既有边界处理。

## 2. 核心原则

### 2.1 AstrBot 插件与 Dududa 能力是两层概念

插件安装后分为两类：

1. **普通 AstrBot 扩展**：由 AstrBot 接收事件、执行命令或被动行为，在 WebUI 中显示安装、
   启用和加载状态。
2. **Dududa 受治理能力**：除插件本体外，还必须在 Dududa 主仓拥有明确的 Capability 或
   Policy mapping，才能进入 Agent 的合法候选集合。

插件 **禁止** 通过自己的代码给自己授予 Dududa Capability、管理员身份、群 Scope 或发送
权限。安装成功也 **禁止** 自动把 `policyManaged`、`auto`、`on` 或 `locked` 写入会话策略。

### 2.2 分权边界

Dududa 是受治理的群体情境适应 Runtime：

- 模型或 Agent 可以提出候选动作；
- 确定性代码拥有身份、Scope、权限、预算和副作用；
- WebUI 超级管理员设置会话初值和允许范围；
- Agent 可以在允许范围内自适应，但管理员明确锁定的值除外；
- 插件实现具体能力，不复制 Model Router、Memory、Persona、Scheduler 或权限控制面。

### 2.3 默认行为

- 自动发送、被动触发、定时任务和主动探测 **必须** 默认关闭。
- 命令插件 **应该** 使用独有的命令组，避免与 `/help`、`/status` 等核心命令冲突。
- 外部请求失败时 **必须** 返回有限、可理解的错误，不向聊天或 WebUI 输出凭据、Cookie、
  Token、完整上游响应或堆栈。
- 插件停用或热重载时 **必须** 关闭自己创建的客户端、后台任务和文件句柄。

## 3. 版本与稳定标识

### 3.1 插件标识

插件目录名、`metadata.yaml` 中的 `name` 和 `@register()` 的第一个参数 **必须完全一致**：

```text
astrbot_plugin_example
```

名称 **必须**：

- 以 `astrbot_plugin_` 开头；
- 只使用小写英文字母、数字和下划线；
- 是合法的 Python 标识符；
- 不含空格、连字符、斜杠或反斜杠；
- 发布后保持稳定，不能通过普通升级隐式改名。

改名会同时影响插件配置文件、运行数据目录和已保存策略，因此只能通过明确的数据迁移完成。

### 3.2 插件版本

- `metadata.yaml` 的版本 **必须** 使用 `vMAJOR.MINOR.PATCH`，例如 `v0.1.0`。
- `@register()` 的版本 **必须** 使用相同版本，可省略前导 `v`，例如 `0.1.0`。
- 两处版本去掉前导 `v` 后 **必须一致**。
- 破坏命令、配置键、数据格式或公开响应语义时 **必须** 升级主版本。
- 新增向后兼容功能时 **应该** 升级次版本；修复兼容 Bug 时 **应该** 升级修订版本。

### 3.3 AstrBot 兼容范围

面向当前 Dududa 环境的新插件 **应该** 声明：

```yaml
astrbot_version: ">=4.26.2,<5"
```

如果插件实际只使用更早版本已存在的公开 API，可以降低最低版本，但必须经过对应版本验证。
`astrbot_version` 遵循 PEP 440，不能添加 `v` 前缀。

## 4. 标准目录

推荐的完整插件目录如下：

```text
astrbot_plugin_example/
├── __init__.py
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── policy.py
├── service.py
├── requirements.txt
├── README.md
├── LICENSE                    # 推荐；复用第三方代码时必须保留相应许可
├── logo.png                   # 可选，1:1，推荐 256x256
└── tests/
    ├── __init__.py
    ├── test_policy.py
    └── test_service.py
```

规则：

- `main.py`、`metadata.yaml` 和 `README.md` **必须存在**。
- 有用户配置时，`_conf_schema.json` **必须存在**。
- 有第三方 Python 运行依赖时，`requirements.txt` **必须存在**。
- `main.py` **应该** 只保留 AstrBot 注册、事件转换、权限入口和结果转换。
- 可独立测试的规则与外部访问 **应该** 分别放入 `policy.py`、`service.py` 等模块。
- 持久数据 **禁止** 写入插件源码目录。
- 发布包 **禁止** 包含 `.git`、`.venv`、`__pycache__`、`node_modules`、真实配置、数据库、
  日志、Cookie 或凭据。

小型纯命令插件可以省略 `policy.py` 和 `service.py`，但不能因此把凭据、复杂网络访问和大量
业务逻辑全部堆进 Handler。

## 5. `metadata.yaml` 模板

以下模板可以直接修改。除 `help` 外的字段均应保留：

```yaml
name: astrbot_plugin_example
display_name: 示例查询
desc: 通过只读接口查询示例数据，并以适合群聊的形式返回结果。
short_desc: 只读查询示例数据。
help: |
  /example help 查看帮助。
  /example query <关键词> 执行查询。
  /example status 查看插件状态。
version: v0.1.0
author: your_name
repo: https://github.com/your_name/astrbot_plugin_example
astrbot_version: ">=4.26.2,<5"
support_platforms:
  - aiocqhttp
```

字段规则：

| 字段 | 级别 | 规则 |
| --- | --- | --- |
| `name` | MUST | 与目录名及 `@register()` ID 完全一致 |
| `display_name` | MUST | 面向管理员的人类可读中文名称 |
| `desc` | MUST | 一句话说明真实能力，不宣传尚未实现的功能 |
| `short_desc` | SHOULD | 用于紧凑列表，保持一句话 |
| `help` | SHOULD | 与实际命令逐项一致 |
| `version` | MUST | `vMAJOR.MINOR.PATCH` |
| `author` | MUST | 稳定作者或组织标识 |
| `repo` | MUST | 可访问的源码仓库地址；本地原型可先写计划中的正式仓库地址 |
| `astrbot_version` | MUST | PEP 440 兼容范围，不加 `v` |
| `support_platforms` | MUST | Dududa QQ 插件至少包含 `aiocqhttp` |

`metadata.yaml` 可以包含 AstrBot 支持的其他字段，但 **禁止** 发明一个未被 Dududa 或 AstrBot
读取的字段并宣称它已经生效。

## 6. `main.py` 参考模板

下面是默认关闭、默认拒绝未授权 Scope、支持热重载资源释放的只读命令插件模板：

```python
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .policy import access_error
from .service import ExampleService, ExampleServiceError


PLUGIN_ID = "astrbot_plugin_example"
PLUGIN_VERSION = "0.1.0"


@register(
    PLUGIN_ID,
    "your_name",
    "通过只读接口查询示例数据",
    PLUGIN_VERSION,
)
class ExamplePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        config = config or {}
        self.config = config
        self.enabled = bool(config.get("enabled", False))
        self.group_whitelist = {
            str(item).strip()
            for item in config.get("group_whitelist", [])
            if str(item).strip()
        }
        self.private_user_whitelist = {
            str(item).strip()
            for item in config.get("private_user_whitelist", [])
            if str(item).strip()
        }

        endpoint = str(config.get("endpoint", "") or "").strip()
        timeout_seconds = max(3, min(int(config.get("timeout_seconds", 15)), 60))
        self.service = (
            ExampleService(endpoint, timeout_seconds=timeout_seconds)
            if endpoint
            else None
        )
        logger.info(
            "%s loaded: enabled=%s configured=%s",
            PLUGIN_ID,
            self.enabled,
            self.service is not None,
        )

    def _access_error(self, event: AstrMessageEvent) -> str | None:
        return access_error(
            enabled=self.enabled,
            group_id=str(event.get_group_id() or ""),
            sender_id=str(event.get_sender_id() or ""),
            group_whitelist=self.group_whitelist,
            private_user_whitelist=self.private_user_whitelist,
        )

    @filter.command_group("example")
    def example(self):
        """示例查询命令组"""
        pass

    @example.command("help", alias={"帮助"})
    async def example_help(self, event: AstrMessageEvent):
        """查看示例插件帮助"""
        yield event.plain_result(
            "/example query <关键词> - 查询示例数据\n"
            "/example status - 查看插件状态"
        )

    @example.command("status", alias={"状态"})
    async def example_status(self, event: AstrMessageEvent):
        """查看示例插件状态"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            return
        state = "已配置" if self.service is not None else "缺少 endpoint 配置"
        yield event.plain_result(f"示例查询：{state}")

    @example.command("query", alias={"查询"})
    async def example_query(self, event: AstrMessageEvent, query: GreedyStr):
        """查询示例数据"""
        if error := self._access_error(event):
            yield event.plain_result(error)
            return
        if self.service is None:
            yield event.plain_result("示例查询尚未配置 endpoint。")
            return

        normalized_query = str(query).strip()
        if not normalized_query:
            yield event.plain_result("请提供查询关键词。")
            return

        try:
            summary = await self.service.query(normalized_query)
        except ExampleServiceError as exc:
            logger.warning("%s query failed: %s", PLUGIN_ID, exc)
            yield event.plain_result("查询暂时失败，请稍后重试。")
            return
        except Exception:
            logger.exception("%s unexpected query error", PLUGIN_ID)
            yield event.plain_result("查询发生内部错误。")
            return

        yield event.plain_result(summary)

    async def terminate(self) -> None:
        """插件停用或热重载时释放资源。"""
        if self.service is not None:
            await self.service.close()
            self.service = None
```

实现规则：

- 插件类 **必须** 继承 `Star`，并调用 `super().__init__(context)`。
- Handler **必须** 定义在插件类中，前两个参数为 `self` 和 `event`。
- `main.py` 的构造函数 **必须** 允许 `config=None`，因为无 `_conf_schema.json` 时 AstrBot
  只传入 `context`。
- Handler 使用 `GreedyStr`、`int`、`float` 或 `bool` 等命令参数时，`main.py`
  **禁止** 开启 `from __future__ import annotations`。AstrBot 4.26.2 依据运行时类型对象解析命令参数，
  字符串注解会破坏多词和数值参数解析。纯 `policy.py`、`service.py` 和测试文件仍可使用该 future。
- Handler **应该** 写简短 docstring，便于 AstrBot 生成可见说明。
- 日志 **必须** 使用 `astrbot.api.logger`，不能打印凭据或完整私有响应。
- 同一结果 **必须** 只走一条发送路径：使用 `yield event.*_result()` 或 `await event.send()`，
  不要重复发送。
- 只有确实需要阻止后续插件处理时才调用 `event.stop_event()`。
- 资源释放函数 **必须** 可重复调用，不因重复关闭导致异常。
- 不要直接依赖 `raw_message` 的平台私有字段，除非 `support_platforms` 已限制平台且 README
  明确说明该依赖。

## 7. 纯策略与服务模板

### 7.1 `policy.py`

把可独立测试的 Scope 规则从 AstrBot Event 中分离：

```python
from __future__ import annotations

from collections.abc import AbstractSet


def access_error(
    *,
    enabled: bool,
    group_id: str,
    sender_id: str,
    group_whitelist: AbstractSet[str],
    private_user_whitelist: AbstractSet[str],
) -> str | None:
    if not enabled:
        return "插件当前未启用。"
    if group_id:
        if not group_whitelist or group_id not in group_whitelist:
            return "当前群未启用此插件。"
        return None
    if not private_user_whitelist or sender_id not in private_user_whitelist:
        return "当前私聊用户无权使用此插件。"
    return None
```

这只是普通 AstrBot 插件的本地入口限制，不替代 Dududa 的 Capability 授权。涉及管理员操作、
跨群发送或真实副作用时，插件还 **必须** 使用项目已有的身份和授权 Adapter，不能只相信用户
输入的 QQ 号、昵称或 Prompt。

### 7.2 `service.py`

网络访问使用异步客户端，并把上游错误转换为有限的插件错误：

```python
from __future__ import annotations

from typing import Any

import httpx


class ExampleServiceError(RuntimeError):
    pass


class ExampleService:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=endpoint.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )
        self._closed = False

    async def query(self, query: str) -> str:
        try:
            response = await self._client.get("/search", params={"q": query})
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExampleServiceError("upstream request failed") from exc

        if not isinstance(payload, dict):
            raise ExampleServiceError("unexpected upstream response")
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ExampleServiceError("missing summary")
        return summary.strip()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._client.aclose()
```

网络插件 **禁止** 使用阻塞事件循环的 `requests`。应该使用 `httpx.AsyncClient` 或
`aiohttp.ClientSession`，并设置有限超时。重试只在接口明确幂等且确有需要时添加，不能默认
堆叠重试、熔断、哈希或额外 Gate。

## 8. `_conf_schema.json` 模板

```json
{
  "enabled": {
    "description": "启用插件",
    "type": "bool",
    "default": false,
    "hint": "安装后默认关闭；配置允许的群或私聊用户后再启用。"
  },
  "endpoint": {
    "description": "只读服务地址",
    "type": "string",
    "default": "",
    "hint": "填写 HTTPS 服务根地址，不要在 URL 中携带 Token。"
  },
  "group_whitelist": {
    "description": "允许使用的 QQ 群",
    "type": "list",
    "items": {
      "type": "string"
    },
    "default": [],
    "hint": "留空时不允许任何群使用。"
  },
  "private_user_whitelist": {
    "description": "允许使用的私聊用户",
    "type": "list",
    "items": {
      "type": "string"
    },
    "default": [],
    "hint": "留空时不允许任何私聊用户使用。"
  },
  "timeout_seconds": {
    "description": "请求超时秒数",
    "type": "int",
    "slider": {
      "min": 3,
      "max": 60,
      "step": 1
    },
    "default": 15
  }
}
```

Schema 规则：

- 每个配置项 **必须** 有 `type`、`description` 和类型正确的 `default`。
- 支持 `string`、`text`、`int`、`float`、`bool`、`object`、`list`、
  `template_list` 和当前 AstrBot 支持的 `file`。
- 数值区间 **应该** 使用 `slider`；固定选项 **应该** 使用 `options`。
- 选择模型 Provider 时 **应该** 使用 `_special: "select_provider"`，不能让用户手写一个
  与 WebUI 已配置 Provider 无关的第二套模型配置。
- 嵌套 `object` 必须通过 `items` 定义子项；复杂重复项可以使用 `template_list`。
- 密码、Token、Cookie 和 API Key **禁止** 出现在 `default`、Git、README 示例或日志中。
- 发布后的配置键是兼容标识，不能直接改名。需要改名时，必须提供明确配置迁移。

AstrBot 会将实例配置保存到：

```text
/AstrBot/data/config/astrbot_plugin_example_config.json
```

插件文件数据应写到：

```text
/AstrBot/data/plugin_data/astrbot_plugin_example/
```

小型状态可以使用 AstrBot 的插件 KV API。插件 **禁止** 把缓存、数据库或生成文件写入自己的
安装目录，因为更新和重装可能覆盖该目录，内建插件目录在 Dududa 中也可能是只读挂载。

## 9. `requirements.txt` 模板

仅写运行时真正 import 的第三方依赖：

```text
httpx>=0.28,<1
```

依赖规则：

- 标准库、AstrBot 自身和 Dududa 镜像已提供的内部包不能重复写入依赖。
- 版本范围 **应该** 有明确上界，避免未来主版本破坏兼容。
- 不要把 `pytest`、`ruff` 等开发工具放进生产 `requirements.txt`。
- 复用代码时 **必须** 核对许可证并保留对应 NOTICE 或 LICENSE。
- 导入新增第三方包后 **必须** 同步更新依赖；删除最后一个 import 后 **应该** 删除无用依赖。

如果插件不需要第三方运行依赖，可以省略 `requirements.txt`，不要保留空文件制造误解。

## 10. 最小测试模板

插件测试应聚焦真实行为，不要求复制 AstrBot 或 Dududa 的全仓测试。

### 10.1 `tests/test_policy.py`

```python
from __future__ import annotations

import unittest

from astrbot_plugin_example.policy import access_error


class AccessPolicyTests(unittest.TestCase):
    def test_allows_an_enabled_whitelisted_group(self) -> None:
        self.assertIsNone(
            access_error(
                enabled=True,
                group_id="10001",
                sender_id="20001",
                group_whitelist={"10001"},
                private_user_whitelist=set(),
            )
        )

    def test_denies_when_plugin_is_disabled(self) -> None:
        self.assertEqual(
            access_error(
                enabled=False,
                group_id="10001",
                sender_id="20001",
                group_whitelist={"10001"},
                private_user_whitelist=set(),
            ),
            "插件当前未启用。",
        )


if __name__ == "__main__":
    unittest.main()
```

### 10.2 `tests/test_service.py`

```python
from __future__ import annotations

import unittest

import httpx

from astrbot_plugin_example.service import ExampleService


class ExampleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_summary_from_a_valid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/search")
            self.assertEqual(request.url.params.get("q"), "测试")
            return httpx.Response(200, json={"summary": "查询成功"})

        service = ExampleService(
            "https://example.invalid",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )
        try:
            self.assertEqual(await service.query("测试"), "查询成功")
        finally:
            await service.close()


if __name__ == "__main__":
    unittest.main()
```

最低验收只要求：

1. 元数据和配置 Schema 能解析；
2. Python 能编译；
3. 一个主要成功路径；
4. 一个禁用、权限拒绝或上游失败路径；
5. AstrBot 热加载后无 traceback，命令能完成一次人工调用。

只有插件涉及真实写入、跨群发送、账户操作或数据迁移时，才应扩大测试范围。

## 11. `README.md` 模板

```markdown
# astrbot_plugin_example

只读查询示例插件。

## 命令

- `/example help`
- `/example status`
- `/example query <关键词>`

## 配置

- `enabled`：总开关，默认关闭。
- `endpoint`：只读服务根地址。
- `group_whitelist`：允许使用的群。
- `private_user_whitelist`：允许使用的私聊用户。
- `timeout_seconds`：请求超时。

## Dududa 接入声明

- Runtime：AstrBot
- 执行类型：显式命令
- 外部副作用：无，只读请求
- 自动发送：无
- Dududa Capability mapping：未提供；安装后仅作为普通 AstrBot 扩展

## 数据与凭据

插件不在源码目录保存数据。真实 Token、Cookie 或密码不得提交到仓库。

## 验证

运行聚焦单元测试并在 AstrBot 中执行一次热加载和命令调用。
```

README **必须** 描述真实命令、配置、数据位置、外部副作用和 Dududa 接入状态。未完成的
Capability mapping 必须写“未提供”，不能写成“Agent 已可自动调用”。

## 12. Dududa 治理接入规则

### 12.1 安装不等于授权

WebUI 安装按钮完成的是 AstrBot 扩展安装。安装完成后：

- 插件可以出现在“已安装扩展”列表；
- 管理员可以查看加载、启用和配置状态；
- 插件不会自动进入 Dududa Agent 的 Capability 候选；
- 插件不会自动获得任何群、用户、模型、Memory、MCP 或主动发送权限。

需要 Agent 自动选择插件时，主仓还 **必须** 提供显式 mapping，至少说明：

| 项目 | 说明 |
| --- | --- |
| 稳定 Policy/Capability ID | 例如 `example.read`，发布后保持稳定 |
| Runtime Target | `astrbot` 或 `web_agent`，只能有一个正式执行入口 |
| Execution Kind | Agent Capability、显式命令或被动行为 |
| Scope | 允许的账号、群聊或私聊范围 |
| Required Role | 谁能配置和直接调用 |
| Side Effects | 只读、发送、写入或外部变更 |
| Default Mode | 新 Scope 默认 `off` |
| Input/Output Contract | 结构化参数、结果和有限错误 |

当前项目没有一个可以由任意插件自行声明并立即获权的通用 Dududa Manifest。AI **禁止**
虚构 Manifest、Capability Registry 写入或“自动注册成功”的结果。新增 mapping 应作为 Dududa
主仓内独立、可审查的 Adapter 变更完成。

### 12.2 管理员初值与 Agent 自适应

WebUI 超级管理员设置的是初始服务和合法候选范围。插件 **禁止** 把管理员的普通偏好解释成
永久锁定：

- `off`：不得调用；
- `auto`：Agent 可在合法候选中选择是否调用；
- `on`：管理员偏好启用，但不要求每轮调用；
- `locked`：保持在管理员指定的允许状态，Agent 不得自行越界改变。

具体状态含义由 Dududa Policy Runtime 决定，普通 AstrBot 插件不能自行修改这些状态。

### 12.3 外部能力与副作用

- 只读插件也必须准确声明自己是否会触发登录、刷新、探测上游或写缓存。
- 写入、删除、广播、跨群发送和账户操作必须由确定性授权代码执行。
- LLM 输出不能直接成为工具参数或发送目标；必须经过类型、Scope 和权限检查。
- 插件不得读取与当前 Scope 无关的个人 Memory 或聊天记录。
- 插件不得在安装或 import 阶段执行网络请求、发送消息或迁移数据。

## 13. SHORT / MEDIUM / LONG 输出规则

AnswerProfile 与模型 Tier、推理深度和 Persona 相互正交。插件不能因为使用了专业模型就自动
输出 LONG，也不能仅按字符数猜测回答档位。

### 13.1 SHORT

适用于日常聊天、确认、简短事实和单步结果：

- **必须** 使用普通消息；
- **禁止** 打包为 QQ 合并转发；
- 应只保留完成当前交流所需的信息；
- 不重复人格口头禅，不附加模板式总结。

### 13.2 MEDIUM

适用于一般解释、少量步骤或带必要上下文的结果：

- **必须** 使用普通消息；
- **禁止** 仅因文本较长就打包为合并转发；
- 可以分自然段，但不应机械拆成多个节点；
- Persona 应融入措辞和节奏，不刻板重复设定。

### 13.3 LONG

适用于深度分析、复杂计划和多部分研究结果：

- 可以在 QQ 群聊中使用合并转发；
- 只有纯文本结果确实包含至少两个有意义部分时才应该合并；
- 包含图片、文件、明确目标用户或其他非文本组件时，应交给 Output Adapter 选择普通消息链；
- 合并节点必须保持原有顺序，不得改变事实或引用关系。

### 13.4 插件职责

接入 Dududa Runtime 的插件 **应该** 返回结构化事实、Observation 或中性内容，让 Composer、
Persona 和最终 Validator 共同决定表达。插件 **禁止**：

- 根据 `len(text)` 把 SHORT 或 MEDIUM 强制转换成合并转发；
- 在每次输出中重复固定人格介绍、口头禅或卖萌模板；
- 把模型推理过程、系统 Prompt 或内部路由原因发到群里；
- 绕过 ResponsePlan 自己重新选择模型 Tier 或思考深度。

例外：像 `/sub2api overview` 这样在命令契约中明确规定“多面板合并转发”的确定性命令，可以
直接构造多节点结果。该例外必须在 README 和测试中写明，不能扩展为所有长文本的通用规则。

## 14. 打包规范

AstrBot 支持 ZIP 根目录直接放插件文件，也支持 ZIP 内只有一个顶层插件目录。推荐使用单一
顶层目录，便于人工检查：

```text
astrbot_plugin_example-v0.1.0.zip
└── astrbot_plugin_example/
    ├── metadata.yaml
    ├── main.py
    └── ...
```

在插件父目录执行：

```bash
zip -r astrbot_plugin_example-v0.1.0.zip astrbot_plugin_example \
  -x '*/.git/*' '*/.venv/*' '*/__pycache__/*' '*.pyc' '*.log' '*.db' '*.sqlite*'
```

规则：

- ZIP **必须** 小于或等于 16 MiB，这是当前 Dududa Web 安装器的上传上限。
- ZIP 内 **必须** 只有一个插件加载单元，不能捆绑第二个插件。
- ZIP 内的 `metadata.yaml` **必须** 能在解压后的插件根直接找到。
- 不得打包真实运行配置、凭据、缓存、测试输出和本地数据库。
- WebUI 安装后会由 AstrBot 安装依赖并热加载；普通安装 **不需要** 重启 AstrBot、NapCat 或
  整个 Compose。
- Dududa 内建只读挂载插件不能通过上传 ZIP 覆盖，应通过主仓代码变更升级。

## 15. 最小验证命令

在插件父目录执行以下聚焦验证即可：

```bash
python -m json.tool astrbot_plugin_example/_conf_schema.json >/dev/null
python -c "import yaml; yaml.safe_load(open('astrbot_plugin_example/metadata.yaml', encoding='utf-8'))"
python -m compileall -q astrbot_plugin_example
ruff check astrbot_plugin_example
PYTHONPATH=. python -m unittest discover -s astrbot_plugin_example/tests -v
```

随后在 WebUI 中：

1. 选择 ZIP 并安装；
2. 确认列表显示插件 ID、版本和“已加载”；
3. 打开配置，填写测试 Scope 并启用；
4. 执行一次 `/example status` 和一次主要命令；
5. 热重载插件，确认没有 traceback，客户端和任务未重复运行。

如果插件没有配置 Schema、第三方依赖或网络服务，应删除不适用的验证项，不要为了形式添加
空文件和空测试。

## 16. 交付前一致性清单

### 16.1 格式

- [ ] 目录名、`metadata.name`、`@register` ID 完全一致。
- [ ] `metadata.version` 与 `@register` 版本归一化后完全一致。
- [ ] `metadata.yaml` 至少包含所有 MUST 字段。
- [ ] `_conf_schema.json` 是合法 JSON，字段类型与代码读取类型一致。
- [ ] README 命令、配置和实现一致。
- [ ] `requirements.txt` 与第三方 import 一致。

### 16.2 行为

- [ ] 自动行为默认关闭。
- [ ] 群聊、私聊和管理员 Scope 语义明确。
- [ ] 外部副作用准确声明。
- [ ] 热重载会释放客户端、任务和文件句柄。
- [ ] 错误响应不泄露私有数据或堆栈。
- [ ] 命令不会与 Dududa 核心命令冲突。

### 16.3 Dududa

- [ ] README 准确写明“普通 AstrBot 扩展”或已有的 Dududa mapping。
- [ ] 未把“安装成功”描述成“Agent 已可自动调用”。
- [ ] 未复制 Router、Memory、Persona 或权限控制面。
- [ ] SHORT、MEDIUM 保持普通消息。
- [ ] LONG 或明确多面板契约才考虑合并转发。
- [ ] Persona 是自然融入，不是固定前后缀。

### 16.4 验证

- [ ] 元数据和 Schema 解析通过。
- [ ] Python 编译和 Ruff 通过。
- [ ] 一个成功路径与一个拒绝或失败路径通过。
- [ ] AstrBot 安装、人工调用和热重载通过。

## 17. 可直接复制给 AI 的 Prompt

将下面 Prompt 中尖括号内容替换为实际需求，再与本规范一起提供给 AI：

```text
你正在为 Dududa 2.0 开发一个 AstrBot 4.26.2 插件。严格遵守随附的
《Dududa 2.0 插件开发规范》（DUDUDA-PLUGIN-SPEC 1.0.0）。

插件信息：
- 插件短 ID：<例如 campus_notice>
- 展示名称：<中文名称>
- 功能：<只描述真实要实现的功能>
- 命令组：<例如 campus>
- 命令：<逐条列出命令和参数>
- 数据来源：<本地、公开 HTTP、需要登录的 HTTP、MCP 或其他>
- 外部副作用：<无/发送/写入/删除/账户操作>
- 允许范围：<群聊、私聊、白名单或管理员>
- 是否需要 LLM：<否/是；若是，说明用途，不指定第二套 Provider>
- 是否需要 Dududa Agent 自动选择：<否/是；若是，仅生成接入需求，不虚构已完成 mapping>
- 期望 AnswerProfile：<SHORT/MEDIUM/LONG/由 Runtime 决定>

生成要求：
1. 插件目录必须命名为 astrbot_plugin_<短 ID>，metadata.name 和 @register ID 与目录完全一致。
2. 使用 v0.1.0 作为首版 metadata 版本，@register 使用归一化后的 0.1.0。
3. 输出完整目录树，以及每个必要文件的完整内容，不使用“省略”“同上”或伪代码。
4. 至少生成 metadata.yaml、main.py、README.md；有配置时生成 _conf_schema.json；有第三方依赖
   时生成 requirements.txt；复杂规则和网络访问分别拆到 policy.py、service.py。
5. 自动发送、被动触发和定时行为默认关闭。凭据不得写入源码、默认值、README 或日志。
6. 使用 AstrBot 的公开 API、astrbot.api.logger 和异步 HTTP 客户端。不要使用 requests，不要在
   import 或安装阶段访问网络、发送消息或迁移数据。
   `main.py` 的 config 参数必须可选；有类型化命令参数时不得开启 future annotations。
7. 不复制 Dududa Model Router、Memory、Persona、权限或 Scheduler。普通插件安装不等于获得
   Dududa Capability；需要 Agent 调度时，只列出主仓需要新增的稳定 ID、Scope、执行类型和
   Adapter mapping，不声称已经注册。
8. SHORT 和 MEDIUM 必须使用普通消息；LONG 只有在 QQ 群聊、纯文本且至少两个有意义部分时
   才可交由 Output Adapter 合并转发。不要仅按字符数转换，不要机械重复人格设定。
9. 生成最小测试：一个主要成功路径和一个禁用、权限拒绝或上游失败路径。优先测试纯 policy
   和 service，不复制 AstrBot 全框架。
10. 最后给出聚焦验证命令、ZIP 打包命令，以及人工安装/热重载检查步骤。不要增加 hash、冻结
    contract、全仓 baseline 或与本插件风险无关的 gate。

开始生成前先检查输入是否缺少会改变插件行为的必要信息。若不缺少，直接输出成品，不要先写
长篇方案。
```

## 18. 参考边界

- 新的确定性命令插件可以参考 Dududa 的 Sub2API 只读插件在命令、访问控制、客户端与格式层
  的拆分方式。
- 新的被动事件插件可以参考自动复读插件的群级状态与配置方式，但自动行为仍必须默认关闭。
- 不应以 Dududa 1.0 的 Target Talk、自动表情包或其他已废弃自动社交插件作为新插件模板。
- 需要校园数据时，优先接入现有统一 MCP/Capability 基础设施，不在 AstrBot 插件中复制一套
  MCP Client、Session 和权限控制面。
