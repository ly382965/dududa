# S14 Memory Retrieval 合成评测数据卡

状态：固定生成、仅合成数据、尚未完成人工评审。

- Bundle：`memory-retrieval-synthetic-v1`
- 数据来源：本地确定性生成器；不含真实 QQ、用户或 Memory 数据
- 策略：M0 no-memory、M1 recency、M2 CJK BM25
- 网络与模型调用：禁止，计数为 0
- 人工相关性评审：未完成
- 真实中文检索质量：未建立

所有策略使用同一份 JSON v2 状态、同一 UTC 参考时间和同一候选上限。
这里的 JSON v2 只是 S14 reference Adapter 的派生测试镜像，不是稳定的 Eval
Domain DTO；未来存储格式迁移必须显式重生成并重新验证 golden。
安全分母来自 fixture 中实际存在的跨 Scope、未来创建、已过期、tombstone
和 Restricted 记录，而不是来自返回结果。安全事件必须为 0；零事件的单侧
95% 上界只描述本合成覆盖，不是对真实流量的统计保证。

tombstone stratum 证明固定 v2 状态中的已删 ID 不会被检索或复活；它不替代
删除事务、崩溃恢复和 restore fence 的 lifecycle Contract Test。

预注册 lexical subset 只验证固定词法目标上 M2 相对 M1 的回归改善。它不证明
真实中文体验、长期记忆有效性、生产 Iris、Embedding/Hybrid 增益或 Runtime
启用条件；这些仍需授权数据、人工标注和后续外部门禁。
