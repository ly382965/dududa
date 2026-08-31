# Arcaea B50 本地渲染资产

该插件只保留 Dududa 2.0 可治理的本地 B50 渲染能力。旧版“绑定 QQ 好友码、私聊
第三方 Bot 查分、监听回复并转发到群”的代理链路已经删除，因为它把身份、队列、外部通信
和发送权放进了插件，不符合 2.0 Runtime 的分权边界。

## Dududa 2.0 边界

- 稳定 Provider ID：`plugin.arc-b50`
- 建议 Capability ID：`arcaea.b50.render.v1`
- 执行类型：本地 Capability
- 默认模式：`off`
- AstrBot 消息 handler：无
- 网络请求和第三方 Bot：无
- 自动发送、私聊和群转发：无
- 用户绑定和 SQLite：无
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

本提交不接 production composition，也不修改安装脚本。

## 验证

```bash
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins \
  uv run --with pytest python -m pytest -q tests/test_arc_proxy_plugin.py
```
