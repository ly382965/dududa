# ADR 0001：迁移期间保持 AstrBot 插件加载契约

- 状态：已接受
- 日期：2026-07-18
- 决策范围：嘟嘟哒自研 AstrBot 插件的目录、加载、依赖和数据兼容

## 背景

当前仓库有三套独立自研插件：

- `astrbot_plugin_dududa_core`
- `astrbot_plugin_reply_polish`
- `astrbot_plugin_target_talk`

Compose 将每套源码分别只读挂载到 `/AstrBot/data/plugins/<plugin-name>`。AstrBot 从各插件根读取 `main.py`、`metadata.yaml` 和 `_conf_schema.json`，代码通过 `@register` 注册。Core 使用相对 import，并通过当前文件深度推导 `/AstrBot/data`；Target Talk 依赖 AstrBot aiocqhttp 的内部类型。

目标架构希望把 AstrBot 变成薄适配层，并把 Agent 核心放入独立 Python package。若机械地把三个插件塞进一个父目录、改变容器路径深度，或在镜像安装 package 前切换 import，插件会在启动阶段失效。现有 CI 的语法编译不能发现这类错误。

## 决策

### 1. 保留三个加载单元

目标源码路径采用：

```text
apps/astrbot-plugins/astrbot_plugin_dududa_core
apps/astrbot-plugins/astrbot_plugin_reply_polish
apps/astrbot-plugins/astrbot_plugin_target_talk
```

迁移源码后，Compose 仍将它们分别挂载到原有容器目标：

```text
/AstrBot/data/plugins/astrbot_plugin_dududa_core
/AstrBot/data/plugins/astrbot_plugin_reply_polish
/AstrBot/data/plugins/astrbot_plugin_target_talk
```

不假设 AstrBot 会递归扫描 `apps/`，也不让 AstrBot 直接加载 monorepo 父目录。

### 2. 保持稳定标识

在专门的数据迁移发布前，以下标识保持不变：

- 插件目录名和 `@register` 名称
- AstrBot 插件配置文件名
- `/AstrBot/data/plugin_data/<plugin-name>` 运行数据目录
- 现有命令名和 Event filter 行为
- `metadata.yaml` 与 `_conf_schema.json` 的关联

宿主源码路径可以改变，容器内加载契约不能随目录美化一起改变。

### 3. 核心 package 由镜像安装

`packages/dududa-agent` 必须声明为可安装 Python package，并由 AstrBot 派生镜像安装。插件只 import 已安装的 `dududa` package。生产运行不依赖仓库根进入 `PYTHONPATH`，也不复制核心 package 到每个插件目录。

镜像构建、package 安装和插件 import smoke test 完成前，旧插件继续调用旧实现。兼容模块必须标记为 `compatibility` 或 `legacy`，并记录删除条件。

### 4. 分别迁移插件职责

- Core 逐步只保留命令注册、Event 转换、Runtime 组装和 Response 转换。
- Reply Polish 在 Response Adapter 能完整覆盖 QQ 合并转发前保持独立插件。
- Target Talk 在 Social Decision 能覆盖其概率、群白名单、冷却和 LLM 调用行为前保持独立插件。

不以合并目录替代行为迁移。

### 5. 真实加载测试是切换门槛

任何插件路径或 import 变更必须通过：

1. 从派生 AstrBot 镜像导入三套插件。
2. 验证 `@register` 和配置 schema 可被 loader 发现。
3. 以只读源码挂载启动，确认没有尝试写入插件目录。
4. 验证插件数据路径、配置和已有命令兼容。
5. 启动失败时可将 Compose 源路径切回旧提交，无数据迁移才能回滚。

## 被否决的方案

### 立即合并为单一 `astrbot_plugin_dududa`

否决原因：三套插件使用不同生命周期钩子和配置 schema，当前没有足够的行为测试证明合并等价。

### 将 Agent Core 继续放在插件目录

否决原因：核心逻辑会继续依赖 AstrBot 的加载和 import 环境，无法脱离 AstrBot 测试，也违反目标依赖方向。

### 通过全局 `PYTHONPATH` 暴露整个仓库

否决原因：路径依赖隐式、开发与镜像环境容易漂移，并将不需要的部署和第三方目录暴露给运行时。

### 同时改变插件名和运行数据目录

否决原因：会触发配置丢失、重复插件、状态分叉和不可逆的数据迁移，超出目录重构范围。

## 影响

正面影响：

- 新核心 package 可以独立测试，AstrBot 适配层可渐进变薄。
- 现有插件配置、命令和数据路径保持稳定。
- 每个插件可以分别迁移和回滚。

代价：

- 迁移期间会存在旧入口和新 package 的兼容层。
- Compose 仍需维护三条显式挂载。
- 派生镜像构建必须加入 package 安装和真实 import smoke test。

## 重新评估条件

只有当三个独立插件的行为已由 Runtime/Adapter 测试覆盖、生产入口已使用新 Runtime、配置迁移和回滚已验证，且无外部安装依赖旧插件名时，才可提出合并加载单元的新 ADR。
