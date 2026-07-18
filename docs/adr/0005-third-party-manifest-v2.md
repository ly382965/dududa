# ADR 0005：使用第三方 Manifest v2 统一 lock、vendor、patch 和镜像声明

- 状态：已接受，计划在 Phase 8 实施
- 日期：2026-07-18
- 决策范围：第三方插件、vendor、patch、容器镜像及其依赖和许可证证据

## 背景

当前第三方插件由根目录 `plugins.lock.json` 声明。五个插件按完整 Git commit 克隆，其中 Meme Manager 使用 sparse checkout，Iris 额外应用一个 patch；Better Reminder 从 `vendor/` 复制。AstrBot 和 NapCat 只以镜像 digest 出现在 `.env.example`，`THIRD_PARTY_NOTICES.md` 另行维护来源。

安装器已经具备 staging、commit 格式检查、patch `--check` 和替换回滚，但当前模型存在以下缺口：

- Git、vendor 和 patch 依赖目录位置和 `source` 分支决定，缺少统一 install mode；
- 除 Better Reminder 外，插件条目没有许可证；
- vendor 没有上游 commit、内容 hash 和本地修改清单；
- patch 只记录路径，不记录 hash、顺序和目标 commit；
- `.dududa-lock.json` 只记录选择字段，patch 或 vendor 内容变化不会使 receipt 失效；
- Git 插件的 requirements 和系统依赖不在 lock 中，版本也没有统一固定；
- 镜像 digest、源码、许可证和 SBOM 没有关联；
- 安装器不校验插件 metadata 版本、许可证文件或安装后内容；
- `THIRD_PARTY_NOTICES.md` 可以与实际安装内容漂移。

许可证审计还发现，Iris 的当前固定提交没有可识别许可证文件。来源公开不等于获得复制、修改或再分发许可；本地 patch 也不能补足上游授权。

## 决策

### 1. 单一权威文件

目标权威文件为：

```text
third_party/manifest.json
```

它使用 `schema_version: 2`，统一声明所有直接第三方运行组件：

- AstrBot 第三方插件；
- 必要的 vendored 源码；
- 本地应用的 patch；
- AstrBot、NapCat 等直接容器镜像；
- 直接 Python/system 依赖集合及其不可变 lock/SBOM 引用。

生态系统的详细传递依赖继续使用适合该生态的锁文件，例如带 hash 的 Python lock 和 OCI SBOM。Manifest 必须引用这些锁文件及其摘要，不能用一份手写 JSON 重复并漂移整个传递依赖图。

根 `plugins.lock.json` 在迁移窗口内保留为 compatibility 输入或由 v2 确定性生成；所有消费者迁移后删除。安装器不得长期同时接受两个可独立编辑的权威源。

### 2. 顶层 Schema

```json
{
  "schema_version": 2,
  "components": [],
  "policy": {
    "allowed_git_schemes": ["https"],
    "require_pinned_git_commit": true,
    "require_oci_digest": true,
    "require_integrity": true,
    "require_verified_license": true
  }
}
```

文件必须通过版本化 JSON Schema。未知字段默认报错，避免拼写错误被静默忽略。

### 3. Component Schema

```json
{
  "id": "astrbot-plugin.iris-chat-memory",
  "kind": "astrbot_plugin",
  "name": "astrbot_plugin_iris_chat_memory",
  "version": "0.1.1+privacy.1",
  "source": {
    "type": "git",
    "url": "https://github.com/owner/repository.git",
    "commit": "40-character-lowercase-commit",
    "source_tree_sha256": "sha256-of-canonical-source-tree"
  },
  "install": {
    "mode": "git",
    "target": "astrbot/plugins/astrbot_plugin_iris_chat_memory",
    "sparse_paths": [],
    "expected_tree_sha256": "sha256-after-sparse-checkout-and-patches"
  },
  "patches": [
    {
      "path": "third_party/patches/iris/user-group-isolation.patch",
      "sha256": "sha256-of-patch-file",
      "applies_to_commit": "40-character-lowercase-commit",
      "strip": 1,
      "purpose": "memory_scope_hardening"
    }
  ],
  "license": {
    "expression": "LicenseRef-NOASSERTION",
    "status": "missing",
    "files": [],
    "notice": null,
    "redistribution": "blocked",
    "reviewed_at": "2026-07-18",
    "reviewed_by": "repository-owner"
  },
  "dependencies": {
    "python_lock": "third_party/locks/iris-python.lock",
    "python_lock_sha256": "sha256-of-lock",
    "system": []
  },
  "provenance": {
    "upstream_version": "0.1.1",
    "local_modifications": ["third_party/patches/iris/user-group-isolation.patch"]
  }
}
```

示例中的 `LicenseRef-NOASSERTION` 仅表达当前事实，不能使组件通过发布门禁。生产迁移时必须用实际 hash 和经确认的许可证信息替换示例值。

### 4. Source 与 install mode

支持的 source/install mode：

| mode | 必填证据 | 规则 |
| --- | --- | --- |
| `git` | HTTPS URL、完整 commit、source tree hash | 禁止 branch、tag、`HEAD` 作为最终锁 |
| `git_sparse` | git 证据、sparse paths、安装后 tree hash | path 必须相对且不能逃逸 |
| `vendor` | 上游 URL、版本/commit、vendor tree hash、修改清单 | 仅上游不可稳定获取或有明确归档理由时允许 |
| `oci_image` | registry reference、`sha256:` digest、source/SBOM 引用 | 禁止仅 tag；部署必须使用 digest |
| `python_lock` | 锁文件 hash、每个分发包 hash、Python/平台条件 | 禁止生产仅使用宽松 `>=` |
| `system_package_set` | 发行版、版本快照或镜像层/SBOM | 记录 Chromium 等非 Python 依赖 |

目录位置不再决定安装方式。`install_plugins.py` 只读取 manifest 的 `install.mode`。

### 5. 完整性规则

#### Git

- `commit` 必须是 40 位小写十六进制；
- clone 后验证 `HEAD` 精确等于 commit；
- 对 canonical source tree 计算 SHA-256；
- sparse checkout 后、patch 前可再次验证选定 source tree；
- patch 后验证 `expected_tree_sha256`；
- `.git`、安装 receipt 和运行缓存不参与安装后 hash。

Git commit 是来源定位，不替代 SHA-256 安装证据。

#### Vendor

- vendor 目录必须记录上游 URL、可获得的 commit/tag、导入日期和导入方式；
- 以排序后的 `(mode, relative_path, content_sha256)` 计算 canonical tree hash；
- 绝对或向上逃逸的 symlink 被拒绝；
- 每个本地修改通过 patch 或 `local_modifications` 记录；
- 版本字符串变化但 tree hash 不变，或 tree 变化但 manifest 不变，都使 CI 失败。

#### Patch

- 使用有序 `patches[]`，不再使用单个 `patch` 字段；
- 每个 patch 记录 SHA-256、目标 component/commit、strip 和 purpose；
- 安装时依次执行 `git apply --check` 和 apply；
- patch 文件变化立即改变 component receipt；
- patch 通过不代表行为正确，仍需针对安装后代码运行 contract/privacy 测试。

#### OCI 与 Python

- OCI 只能使用 `name@sha256:digest`，并记录与源码、许可证、SBOM 的关联；
- Python 锁必须固定直接和传递依赖，保留 wheel/sdist hash 和环境 marker；
- 镜像构建使用锁文件，不在容器启动或插件加载时隐式解析最新版；
- 系统依赖和浏览器等运行要求进入 SBOM 和 manifest 引用。

### 6. 许可证规则

每个 component 必须有：

```text
expression       SPDX expression 或内部 LicenseRef
status           verified | unverified | missing
files            安装后必须保留的许可证文件
notice           attribution/notice 文件
redistribution   allowed | conditional | blocked
reviewed_at/by   人工确认记录
```

策略：

1. 新增 component 默认要求 `status=verified`；
2. `missing` 不能因为仓库公开、可以 clone 或作者未反对而视为允许；
3. vendor 必须保留完整许可证和版权声明；
4. sparse checkout 必须显式包含根许可证/NOTICE，安装器验证其存在；
5. GPL/AGPL 等 copyleft 条件进入发行和网络服务检查清单；
6. patch 的仓库内版权归属不改变上游许可证义务；
7. `THIRD_PARTY_NOTICES.md` 由 manifest 验证或生成，人工补充义务但不另立版本事实；
8. `LicenseRef-NOASSERTION` 或 `missing` 默认阻止 vendor、镜像打包和公开发布；
9. 例外必须有单独 ADR、owner、范围、到期时间和可移除方案，不能只在 PR 评论中批准。

Iris 当前条目应先标为 `missing/blocked`，在取得上游明确许可证或替换实现前不得声称其为已验证开源依赖。现有安装不应被设计文档误写成授权结论。

### 7. 依赖和许可证现状迁移

迁移 v2 时至少核对：

| Component | 当前模式 | v2 补齐项 |
| --- | --- | --- |
| Better Reminder | vendor v1.4 | 上游 commit/导入证据、vendor tree hash、本地修改、AGPL 文件和依赖 lock |
| ChatSummary | git commit | AGPL 表达式、tree hash、`html2image` lock、Chromium 系统依赖 |
| Iris | git + patch | 缺失许可证处置、patch hash/list、tree hash、Python lock |
| PokePro | git commit | GPL 表达式、tree hash、依赖证据 |
| Reread | git commit | MIT 表达式、tree hash、依赖证据 |
| Meme Manager | sparse git | MIT 文件、sparse 与安装 tree hash、Python lock |
| AstrBot image | OCI digest | digest 到 source/license/SBOM 的映射 |
| NapCat image | OCI digest | wrapper 与内部组件的 source/license/SBOM 映射 |

不得凭名称或 README 推测许可证；所有结论指向固定提交或镜像 digest 的证据。

### 8. Installer v2 流程

```text
load manifest
 -> JSON Schema + policy validation
 -> duplicate/path/source/license checks
 -> resolve exact source in staging
 -> verify commit/digest/source integrity
 -> materialize sparse/vendor content
 -> verify and apply ordered patches
 -> verify installed tree integrity
 -> verify metadata, license files and dependency lock
 -> write installation receipt
 -> atomic replace target
 -> run post-install contract/smoke
```

Installer 必须：

- 拒绝重复 ID/name/target、未知 mode 和路径逃逸；
- 对 Git 使用 HTTPS allowlist，不把 manifest 值拼接到 shell；
- 以 argv 调用外部命令；
- staging 与 target 位于同一文件系统以支持原子 rename；
- 保留旧 target 直到新内容及 receipt 验证完成；
- 失败时恢复旧 target，不留下半安装目录；
- 不读取、写入或记录 GitHub Token、Provider key 和 SSH 私钥；
- 不根据目录里是否有 patch/vendor 猜测动作；
- 不在 `--force` 时跳过完整性和许可证校验。

### 9. Installation Receipt

目标目录中的 `.dududa-install.json` 至少记录：

```json
{
  "receipt_version": 2,
  "component_id": "...",
  "manifest_entry_sha256": "...",
  "source_commit_or_digest": "...",
  "patches": [{"path": "...", "sha256": "..."}],
  "installed_tree_sha256": "...",
  "license_expression": "...",
  "installed_at": "...",
  "installer_version": "..."
}
```

是否需要重装由 canonical manifest entry hash、patch hash 和 installed tree hash 共同决定，不再比较少量选择字段。`installed_at` 不参与 manifest hash。

运行前可执行只读 drift check：target tree 与 receipt 不同则拒绝自动覆盖，提示备份/审查；生产不得静默吞掉手工修改。

### 10. CI 和 Review 门禁

CI 至少执行：

- Manifest JSON Schema 与唯一性；
- 所有相对路径、安全 target 和 source scheme；
- commit、OCI digest、patch/vendor/lock hash 格式与内容；
- 许可证表达式、文件存在和 notice 同步；
- vendor canonical tree hash；
- 在临时目录从空状态安装全部插件；
- 验证 receipt 和二次运行幂等；
- 修改 patch/vendor 后必须检测为需要重装；
- 安装后插件 metadata name/version 与 manifest 一致；
- requirements/system dependency 已锁定或有显式例外；
- Iris 等 privacy patch 的行为测试，不只搜索 patch 字符串；
- 生成 SBOM 并检查无密钥、数据库、登录态或运行数据。

Manifest、patch、vendor、许可证状态和完整性例外变更必须由 CODEOWNERS 显式审阅。

### 11. 渐进迁移

1. 为当前 v1 lock 建立只读转换器和现状报告；
2. 补齐固定提交处的许可证、依赖和上游 metadata；
3. 为 vendor、patch 和当前安装树计算 hash；
4. 创建 `third_party/manifest.json` 和 JSON Schema，但安装入口仍使用 v1；
5. 在 CI 中比较 v1 与 v2 解析出的六个插件集合和安装树；
6. Installer v2 在临时数据根完成全量安装、二次幂等和失败回滚测试；
7. `manage.sh plugins` 切到 v2，保留一个发布周期的显式 compatibility 回滚；
8. 使用 `git mv` 移动 patch/vendor，更新 receipt 和消费者；
9. 所有环境验证后删除 v1 权威输入和目录猜测逻辑；
10. notices、SBOM 和更新自动化只读取 v2。

迁移不得覆盖有未知本地修改的运行插件。运行数据和插件配置不参与源码目录移动。

## 被否决的方案

### 保持 lock、vendor、patch 三套隐式规则

否决原因：安装模式、完整性和许可证证据继续分散，安装器只能根据字段和目录猜测。

### 只给当前 lock 增加 `license` 字段

否决原因：不能解决 vendor/patch 内容漂移、镜像、依赖锁、安装 receipt 和 SBOM。

### 全部 vendor

否决原因：仓库体积、更新和许可证义务显著增加，并丢失上游 commit 拉取的简单性。Vendor 只作为例外。

### 全部运行时 clone 最新版本

否决原因：不可复现、无法回滚，供应链和行为会在无代码 Review 时改变。

### 只依赖 Git commit，不计算 SHA-256

否决原因：commit 能定位来源，但不能证明 patch/vendor/sparse 后最终安装树，也不能让 receipt 感知本地内容变化。

### 许可证未知时继续标为“上游许可证”

否决原因：无法审计，且公开源码不自动授予使用、修改和再分发权利。

## 影响

正面影响：

- 第三方组件只有一个声明和 Review 入口；
- 安装结果可复现、可验证、可回滚；
- patch 和 vendor 修改会可靠触发重装；
- 许可证、notice、SBOM 和实际安装内容可关联；
- 容器、Python/system 依赖和插件进入同一供应链视图；
- Installer 不再靠目录位置猜测行为。

代价：

- 初次迁移需要补齐大量许可证、hash 和依赖证据；
- canonical tree hash 和多平台 Python lock 需要维护工具；
- 许可证未知的现有组件可能阻止发布并要求替换；
- 迁移窗口内需比较 v1/v2，增加短期复杂度；
- 更新 PR 必须同时更新 manifest、hash、notice、SBOM 和测试。

## 回滚

在 Installer v2 切换前，回滚仅删除尚未启用的 v2 文件。切换后保留上一提交、旧安装 receipt 和旧 target backup 的恢复说明；回滚到 v1 必须显式执行 compatibility 命令，不能让两个格式自动竞争。

任何格式回滚都不能降低许可证和完整性检查，也不能删除运行数据、插件配置或用户数据库。

## 重新评估条件

- Git/OCI/Python 生态出现新的标准 provenance 或签名格式；
- 仓库采用统一包管理工具并可直接提供等价证据；
- 组件需要不可由当前 Schema 表达的多平台安装；
- 法律审阅要求更严格的源码提供、NOTICE 或网络服务义务；
- Installer 与外部供应链系统集成后可以减少重复字段但仍保持单一权威源。
