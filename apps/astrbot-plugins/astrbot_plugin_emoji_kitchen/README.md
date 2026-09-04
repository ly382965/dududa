# astrbot_plugin_emoji_kitchen

独立的 Emoji Kitchen 表情合成插件。

使用：

```text
/emoji 😀 😭
/表情合成 😀 😭
```

插件仅接受 Unicode Emoji，使用参考项目指定的官方 metadata 和静态合成图片，不调用 AI
图像模型。metadata 会在首次使用或缓存过期时同步，并保存到 AstrBot 私有数据目录；合成图
按需下载并缓存。

如果 AstrBot 容器不能直连 GitHub，可在私有 `.env` 中设置
`DUDUDA_EMOJI_KITCHEN_HTTP_PROXY`；仅接受 HTTP(S) 代理。
