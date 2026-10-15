# Arcaea 命令兼容与本地 B50 资产（v2.1）

插件有两个独立入口：默认关闭的 Dududa 本地 B50 Capability，以及默认关闭、需显式
配置授权群和固定上游的旧版 QQ 命令兼容通道。开启其中一个不会开启另一个。
v2.0 曾移除 QQ 代理；v2.1 应运营方迁移要求恢复必要旧命令，不能将兼容通道误标为
只读 Capability，也不能用本地渲染替代真实旧命令后宣称完成迁移。

本次发布按用户要求**先跳过 Arc 查分**：`b50_enabled` 独立默认关闭。
可使用 `compatibility_enabled=true`、`b50_enabled=false` 部署绑定/曲目信息/谱面；
已授权群调用 `/arc b50` 会明确提示“查分暂未启用”，不读取绑定、不入队、不联系上游。
B50 协议代码和假客户端测试保留，但真实查分验收标为 deferred，并非已上线通过。

## 旧命令迁移映射

| 旧版命令 | v2.1 对应行为 | 副作用与依赖 |
| --- | --- | --- |
| `/arc bind 九位好友码` | 原命令；验证输入后保存调用者自己的绑定 | 外部目录同结构 SQLite；不联系上游、不回显好友码 |
| `/arc b50` | 本次独立关闭并明确提示；另行启用后保留串行解绑/绑定/查询与图片回传 | 固定上游 Bot；真实查分验收 deferred，非只读能力 |
| `/arc info 曲目` | 原命令；支持 ID、名称、别名、首字母查询 | 外部曲目索引/曲绘；不联网 |
| `/arc chart 曲目 [难度]` | 原命令；默认最高难度，支持 pst/prs/ftr/byd/etr 和 0–4 | 外部谱面/渲染资产；加密谱面明确提示不可渲染 |

仅 aiocqhttp 的白名单群显式命令有效；空白名单拒绝所有群，私聊不能触发这些命令。
本地绑定沿用 `bindings(user_id TEXT PRIMARY KEY, friend_code TEXT NOT NULL)`；
迁移不会注册新账号、重置凭据或调用上游。导入插件与启动也不会打开绑定数据或发送 QQ。

`/arc b50` 保留旧上游协议 `/a unbind` → `/a bind <friend_code>` → `/ab50`，
仅同一 Bot 账号收到固定上游的私聊才推进。失败/错误/无效绑定等文本暂停队列；图片不会
被当作解绑/绑定回执。原协议没有请求关联 ID 和已文档化的成功回执结构，因此不能宣称
可完全辨别所有无关文本或任意迟到的重复图；正常完成仍沿用两秒结果宽限。

队列总容量默认 8（最多 32），活动请求默认最长 600 秒（最多 3600），单次发送默认
15 秒（最多 60）。配额等待仍受活动请求总超时约束。超时、上游报告失败或发送结果
不确定时，清空队列并暂停本进程的 B50，**不自动执行下一请求**；管理员必须先确认
上游已经空闲，再重新开启 B50。本次仅迁移非查分命令，不再追加上游空闲核查；
旧服务重启可能取消原排队请求，不能称为无损查分迁移。新版 B50 保持关闭，
不自动恢复旧请求。日志与失败提示只含固定原因，不含好友码、QQ 号或原始异常/上游文字。

## 私有配置与状态迁移

AstrBot 从 `_conf_schema.json` 注入以下配置；提交到仓库的默认值都保持未授权状态：

```json
{
  "enabled": false,
  "compatibility_enabled": false,
  "b50_enabled": false,
  "allowed_group_ids": [],
  "upstream_bot_id": "",
  "state_root": "/var/lib/dududa/arc",
  "assets_root": "",
  "catalog_root": "",
  "renderer_assets_root": "",
  "queue_capacity": 8,
  "request_timeout_seconds": 600,
  "transport_timeout_seconds": 15
}
```

部署方仅在私有配置中将 `compatibility_enabled` 打开，保留 `b50_enabled=false`，
并原样迁移已授权群列表和上游 QQ；不扩大群范围。路径必须为绝对路径，三个资产路径
可留空使用状态目录默认值：

```text
state_root/                     # 仓库外，保留旧目录权限
  bindings.sqlite3              # 原数据库，无需导出记录或改变 schema
  songs.sqlite3                 # 由现有索引重建的派生数据
  import/                       # assets_root
    songlist
    packlist
    <song_id>/...                # 曲绘、*.aff 或 *.aff.pre
  catalog/                      # catalog_root；仅以下四个文件
    chart_stats_base.json
    chart_overrides.json
    aliases_base.json
    extra_aliases.json
  renderer-assets/              # renderer_assets_root
    img/
    models/
    Fonts/
  rendered/                     # 本地谱面缓存
```

保留旧 `plugin_data/astrbot_plugin_arc_proxy` 作为状态根即可；旧插件 `data/` 中的四个
曲目索引文件由部署方迁移至 `catalog/` 或设置 `catalog_root` 指向专用资产目录。
不要整体复制旧 `data/`，其中可能还有无关的操作配置；不要将数据库、QQ 配置、好友码、
游戏资产或渲染图片提交 Git。既有 `import/`、`renderer-assets/` 可直接沿用，缺失时
相应命令明确返回本地资产不可用，不阻止插件加载或其他命令。

发布方负责安装 `requirements.txt` 中的依赖；插件不在启动时自动下载/安装任何包。
谱面代码复用旧版 vendor，保留 `vendor/render/README.md` 中的上游出处和完整 LICENSE。
其 `616 SB License` 除保留版权/许可通知，还包含额外使用条件：
`The person should speak loudly with "616 SB!", before using this Software.`
游戏资产不随本仓库分发。插件测试使用假框架/假客户端与临时合成 SQLite，发布时另行
确认实际 AstrBot 加载、原配置迁移和旧版冻结；不能把这些隔离测试写成已经线上验收。

## Dududa 2.0 本地 Capability 边界（不变）

- 稳定 Provider ID：`plugin.arc-b50`
- 建议 Capability ID：`arcaea.b50.render.v1`
- 执行类型：本地 Capability
- 默认模式：`off`
- 本地 Capability 的消息 handler：无（兼容通道单独管理）
- 本地 Capability 的网络请求和第三方 Bot：无
- 本地 Capability 的自动发送、私聊和群转发：无
- 本地 Capability 的用户绑定和 SQLite：无
- 生产 Composition：尚未接入

`ArcB50CapabilityProvider` 实现 Dududa 通用 `CapabilityProvider` Port；
`LocalB50Renderer` 是框架无关的执行 Adapter，通过仓内
`apps/b50-renderer/b50_renderer.py` 纯本地生成 PNG。插件不会查询玩家成绩，调用方必须提供
结构化的 `player` 和 `scores`。

## 输入与输出

输入示例：

```json
{
  "player": {"name": "PLAYER", "user_id": "123456789"},
  "scores": [
    {
      "title": "Testify",
      "song_id": "testify",
      "difficulty": "BYD",
      "constant": 12.0,
      "score": 10000123,
      "potential": 13.1
    }
  ]
}
```

输出为结构化结果，包含 PNG artifact 路径、媒体类型、字节数、B50 统计、`generated_at`
和 renderer/assets provenance。插件只写入由 Runtime 构造时显式传入的 artifact 目录；不会
从模型参数接受任意输出目录，也不会自行发送生成文件。

## Runtime 装配

生产接入时需要由 Core：

1. 在 Capability Catalog 增加准确声明本地文件产物的 definition；
2. 通过受控配置提供曲绘素材目录和 artifact 输出目录；
3. 注册 `plugin.arc-b50` Provider factory；
4. 由 Output Adapter 决定是否以及向哪里发送 artifact。

本地 Capability 仍未接 production composition；兼容插件装载不能冒充这项装配已完成。

## 验证

```bash
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins \
  uv run python -m unittest discover -s tests -p 'test_arc*.py' -v
```
