# Dududa 2.0 回复审校策略

这个目录保留 PR #5 中“回复审校”的可用思想，但不沿用其 Dududa 1.0 执行方式。
当前版本是框架无关、无副作用的策略资产，不是线上消息拦截器。

## 当前边界

- `policy.py` 判定纯文本模型草稿是否适合进入二次审校。
- 图片、合并转发（Nodes）、其他结构化输出、固定插件结果和空文本始终原样保留。
- 策略只构造保守的结构化审校请求，不调用 AstrBot Provider，也不发送消息。
- 只有明确返回 `decision=revise` 且 `certain=true` 的合法 JSON 才允许采用改写。
- 模型失败、返回格式错误、证据不足、结果为空或结果过长时，严格保留原答。

`main.py` 仅向 AstrBot 声明该适配资产已经可加载，并明确标记
`production_wired = false`。它没有注册 `on_decorating_result` 或其他消息监听器，
也不会把图片、引用、合并转发等结构化 chain 替换成 `Plain`。

## 为什么尚未接入生产

Dududa 2.0 要求模型调用经过 Runtime 的路由、预算、可观察性和失败语义。目前 Core
没有独立且预算化的 secondary-review Port。插件不会绕过 Runtime 直接调用 Provider；
等该 Port 存在后，Runtime 可以消费 `ReviewRequest`，再把模型返回交给 `resolve()`。

推荐的未来调用顺序是：

```text
2.0 Runtime 生成结构化输出
  -> ReviewPolicy.classify
  -> Runtime 判断并预留 secondary-review 预算
  -> Runtime 调用审校模型
  -> ReviewPolicy.resolve（失败或不确定时保留原答）
  -> 原有 Output Adapter 投递，保持结构化内容不变
```

配置页中的 `enabled` 目前只记录期望状态，不会启用一条隐藏的生产调用路径。
