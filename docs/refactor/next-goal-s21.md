# 下一次 `/goal`：S21 Bot Control Plane

## 目标与顺序

下一次 Goal 只完成不依赖外部数据的 S21：

```text
Alignment / Tree revision 4
  -> S21A Control Plane Foundation
  -> S21B Group Onboarding
  -> S21C Governed Operations
  -> S21 Completion Audit
  -> 暂停，等待另行授权 S23
```

S21 完成后，S23 才按以下顺序恢复：

```text
外部数百群长期记录：历史 no-send Shadow
  -> 小样本人工质量评测
  -> 单群实时 no-send Shadow
  -> 明确 @ Canary
  -> 手动日报
  -> 定时日报
  -> 低频 Probe
  -> 3-5 群与长时间 Debug
```

本机当前嘟嘟哒账号记录可以在开发期间运行私有 replay；旧账号排除，精确账号映射只在运行时
提供。外部长期记录不在本 Goal 中读取或等待。

## 可直接使用的 Prompt

```text
/goal

在主仓 `/home/mmdustc/Code/dududa` 持续开发，沿既有 Sxx 路线完成 S21 Bot Control Plane 的全部
离线工程工作。不要进入 S23，不发送 QQ 消息，不等待或读取外部数百群长期聊天记录。

先核对当前 Git、TreeWork revision 3、Requirements、Project Spec、
`docs/design/bot-control-plane.md`、`docs/refactor/implementation-plan.md` 和
`docs/refactor/napcat-development-replay-2026-08-14.md`。用户已经确认：Web 是一等 Bot Control
Plane；Bot 入群后由授权 Bot 管理员选择初始 `GroupServiceProfile`；本机当前嘟嘟哒账号数据
可以用于私有开发回放，旧账号排除，精确账号 ID/日志标签仅通过本机参数或环境变量提供；外部
数百群长期记录只在 S23 真实测试环境中提供。

使用 TreeWork 先完成一次小型 Alignment Review，然后将 Tree 更新为 revision 4：在现有
`agent-expansion` 下插入 `S21A -> S21B -> S21C -> S21 Audit`，并让现有暂停的 S23 依赖
S21 Audit。不得重建第二套路线或改写 S01-S20/S22 的既有完成结论。

执行范围：

1. S21A Control Plane Foundation
   实现 framework-neutral `GroupServiceProfile`、`GroupServiceAssignment`、join/pending、typed
   Query/Command Envelope、operator session/RBAC、Command Gateway、Projector、Audit/Receipt 和
   Fake Group Join/Fake Service Catalog。Profile 只给初值，不授予 Capability。

2. S21B Group Onboarding
   实现 pending inbox、Profile Catalog、Desired/Effective diff、Preview、Activate、Update、
   Pause、Resume、Rollback、immutable Runtime snapshot 和 LKG。新群缺 Profile 时保持零 Agent
   服务；激活失败保持 pending 或 LKG。

3. S21C Governed Operations
   接入 Run、Model、MCP、Plugin、Memory、Proactive 的只读投影；只有已有专用 Core Command 的
   操作才能进入写路径。UI 不自行推导权限、健康或 Effective 状态。

4. S21 Completion Audit
   移除 Agent Draft 直发 NapCat 和浏览器本地 permission/config 假成功；验证跨 Bot/account/group
   隔离、并发 revision、重复命令、重启/LKG、回滚和构建。真人 QQ 操作路径与 Agent Output 保持
   分离。

数据边界：

- S21 的主证据使用 Fake join、Fake services、固定 Profile Catalog 和合成 Scope。
- 本机 `嘟嘟哒` 私有 replay 只在 Connector、历史、Perception 或会话投影受影响时运行；正文和
  原始身份不进入 Git、文档或测试输出。
- 旧账号消息不得进入回放；仅允许按日志账号标签过滤并丢弃。不要读取外部数百群语料，不调用
  真实模型 Endpoint，不抓取实时来源，不启用 Memory 自动写入、Bandit Worker 或在线探索。
- 不修改、重启或替换当前 NapCat/AstrBot 容器；允许启动独立开发 Web 端口进行必要验证。

执行纪律：

- 单开发者 WIP=1；每个 S21 子阶段完成聚焦验证和本地提交后再进入下一阶段，禁止 push。
- 优先实现可运行的纵向切片。默认不新增 hash、冻结 contract、baseline 或 gate；只有能指出具体
  事故，并说明 Git、版本、主键、事务、唯一约束、类型和现有测试为什么不足时才允许增加。
- 不删除已有安全措施；认证、敏感数据、外部写入和不可逆操作继续使用现有边界。
- 测试按风险抽样：分支内运行受影响 Python/Web 测试；S21 Audit 再统一运行相关 Python、Web
  unit/server、typecheck/build 和少量 E2E。不要在每个小改动后重复全仓矩阵。
- Web 是控制后台，但 Domain/Core Command/Runtime snapshot 是权威；不得让浏览器、模型、Group
  Context、Plugin 或 Bandit 开服务、扩权或取得发送权。
- 每个 TreeWork 分支同步 Spec、Task Plan、Progress、Findings 和 Verification，并形成独立本地
  Git 提交。

完成条件：

S21A、S21B、S21C 和 S21 Audit 均完成、验证、合并；管理员能够在 Fake 入群后选择初始服务，
Desired/Effective 可解释，Runtime 只消费不可变 Assignment；所有写操作有 Actor/Scope、revision、
幂等、Audit 和 Receipt；浏览器直写与 Agent 直发 NapCat 路径消失；工作区干净。完成后停止，
准确列出 S23 仍需的外部长期语料、Provider/Source/Projection/Output 适配、人工评测和逐行为授权，
不得自行进入真实群测试。
```
