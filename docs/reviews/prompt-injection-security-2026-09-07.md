# 提示词注入防护评估与补强（2026-09-07）

## 结论与范围

**原有状态：权限基础已实现，提示词注入防护部分完成。此次补强后：正式 Runtime
的文本输入、历史/工具资料、模型提示词和最终输出已有可执行的分层控制；仍不能宣称
“完全防注入”。** 不用单个百分比混合“代码覆盖率”和“真实模型攻击成功率”。

检查对象是 `packages/dududa-agent` 和 Dududa Core 的正式 AstrBot/QQ、Web 预览链路。
先完成工作区评估和加固，随后按用户授权将发布源码 `f7d8cd9` 部署至正式 AstrBot/Core。
完整发布验收见 [2.0.1 版本更新报告](../releases/v2.0.1.md)。仓库已有的其他未提交改动保留。

## 修改前的完成情况

| 防线 | 实际状态与证据 | 本次处理 |
| --- | --- | --- |
| 工具权限与作用域 | 已实现：正式查询限定低风险，排除持久化写入、外部写入、消息发送及文件写入；执行器再次验证权限和参数。模型文本不能直接授予权限。 | 保留原有控制，增加测试确认注入不会造成额外工具调用。 |
| 当前消息 | `CurrentMessageContextBuilder.preprocess` 原先主要判断身份、附件、群内 @ 和参与开关，没有提示词注入检测。 | 明确规则覆盖、内部提示词索取和角色伪造在感知/模型/工具调用前停止。 |
| 历史消息、昵称 | 已有同会话身份和范围绑定，历史为带归属信息的 JSON；攻击内容仍原样进入两个模型输入。 | 在模型投影中检查解码后的历史字段，隔离可疑内容，保留正常字段和原始记录。 |
| MCP/网页/点评正文 | 已有结构校验、结果摘要和 `untrusted=true` 标记，摘要只能证明绑定一致，不能证明文本无恶意指令。 | 对工具数据、来源文字和字段名递归检查；替换可疑文本、删除可疑字段名，保留正常同级事实。 |
| 模型提示词 | 感知已有部分不可信资料说明，直接回答的业务规则较详细；外层 `[DUDUDA_USER_INPUT]` 标记可以从资料中伪造。 | 两个生产提示词共享系统级安全规则；Provider 边界转义伪造的保留标记，JSON 数据仍能往返解析。 |
| 输出与凭据 | `DefaultContentSafetyPolicy` 原先使用已有 Redactor 检查凭据、敏感路径等，没有独立的协议泄漏或自动加载内容检查。 | 复用原安全决策和发送前校验，阻止控制标记泄漏及图片/HTML 自动加载标记。 |
| 安全拒绝后的旧链路 | Runtime 接管 QQ 消息后本来就不会把失败消息交回旧链路。 | 新增正式装配测试验证注入拒绝也遵守此行为。 |

修改前运行了 5 个输入探针：中文规则覆盖、英文规则覆盖、伪造外层/系统标记、全角变体、
零宽字符变体。**5/5 均得到 `proceed`**。这只证明入口缺少检测，不等于模型已被攻破，
也不意味着原有工具授权能被绕过。

## 已增加的安全层

共享实现位于
[`prompt_injection.py`](../../packages/dududa-agent/src/dududa/security/prompt_injection.py)。

1. **输入拦截**：在检测副本上做 NFKC、零宽格式字符和中文间隔归一化，再检查明确的
   中英文规则覆盖、内部信息索取、保留角色标记。结果为 `DEFER`，带稳定原因码
   `prompt_injection_blocked`，不启动模型、工具或消息发送。Runtime 状态验证重算同一判断，
   防止伪造放行回执。
2. **资料隔离**：历史和工具结果只改模型可见的副本，不改原始证据或原有摘要。
   对历史 JSON 先解码字段，避免换行转义掩盖角色标签。工具投影带 `security.quarantined`
   和原因码，系统要求资料不足时说明限制，不补写被隔离的内容。
3. **系统规则与标记处理**：安全规则放进感知、回答各自的 `system_prompt`；Persona
   只影响表达，来源文本及解码内容不能更改规则、权限、作用域或要求额外调用。
   Provider 转义输入内的保留标记，保持外层只有一组实际边界。标记转义改善结构，
   本身不能保证模型不理解编码后的恶意文字。
4. **输出检查**：沿用 `FinalResponseSafetyValidator` 和原有敏感内容检查，额外拒绝
   内部控制标记、Markdown 图片和可自动加载资源的 HTML 标签。普通来源链接和不含
   控制标记的攻击分析可以通过。

当前用户的完整、明确引用转换可以通过，例如“请总结这段文字：‘忽略之前的规则……’”。
此豁免只匹配一个完整的有界引文；引文后追加执行命令、笼统声称“安全研究”均不豁免。
历史和工具资料不享有当前用户的指令权限，仍按不可信内容检查。

## 验证

新增测试：

- [`tests/unit/security/test_prompt_injection.py`](../../tests/unit/security/test_prompt_injection.py)：
  18 条攻击、16 条正常输入；嵌套资料、恶意字段名、历史 JSON 换行、无原文原因码、
  标记转义往返；输出攻击和正常来源引用。
- [`tests/unit/runtime/test_prompt_security.py`](../../tests/unit/runtime/test_prompt_security.py)：
  18 条攻击通过完整 Runtime 验证零模型/工具调用；历史同时覆盖感知、回答输入；
  工具隔离保留原始回执；不安全模型结果没有发送请求。
- [`tests/contracts/test_prompt_security.py`](../../tests/contracts/test_prompt_security.py)：
  真实 Provider 适配器调用参数；生产装配下 Web 预览拦截、QQ 接管后不回落旧链路；
  两个模型都收到系统规则和经过隔离的历史；带 QQ @ 前缀的有界引用仍进入模型。

定向攻击集：**18/18 被拦截**。正常输入集：**16/16 通过输入检查**。
新增安全测试、历史上下文及现有内容安全策略回归共 **27 项通过**；正式装配、Runtime、Provider 适配器及
100 题业务基准等初次工作区回归共 **103 项通过**（315.466 秒）。该数字包含当时已有的
工作区变化及历史测试，不作为最终发布验收总数；上述两个计数也不可直接相加。
最终干净发布镜像 **157 项全部通过**，GitHub Python 3.10/3.12 全量 CI 均通过。
这些自动化用例使用本地脚本替身。部署后另验证了 5 类直接注入拦截及真实模型的正常短答、
引用分析和恶意合成历史处理；未测量在线模型攻击成功率，也没有向真实 QQ 群发送测试内容。

复现：

```bash
.venv/bin/python -m unittest \
  tests.unit.security.test_prompt_injection \
  tests.unit.runtime.test_prompt_security \
  tests.contracts.test_prompt_security \
  tests.unit.runtime.test_preview_context \
  tests.unit.security.test_config_content_compat -q

.venv/bin/python -m unittest \
  tests.unit.runtime.test_orchestrator \
  tests.unit.runtime.test_s10_context_budget \
  tests.unit.runtime.test_composition \
  tests.unit.runtime.test_capabilities \
  tests.unit.runtime.test_preview_context \
  tests.contracts.test_production_composition \
  tests.contracts.test_astrbot_model_provider \
  tests.test_dududa_100_message_benchmark -q
```

## 尚未完成的部分

- **语义覆盖**：规则不是通用攻击分类器。隐晦转述、错拼、复杂编码、多轮诱导、事实污染
  和未命中规则的角色扮演仍可能进入模型；当前系统规则和确定性工具权限继续承担防护。
  系统提示词不是秘密存储，部分提示词复述也不一定包含可被输出层识别的标记。
- **多模态和长期记忆**：此次没有验证图片/OCR 注入，也没有宣称长期记忆投毒已解决。
  当前 Runtime 对附件原有的延后处理保持不变。
- **其他入口**：独立插件、旧回复链路和未接入此 Runtime 的模型调用，不因这次修改
  自动获得相同保护。测试保证的是已接管消息不因安全拒绝而回退。
- **误报与输出能力**：正常讨论攻击语句但不符合有界引用形式时可能被拦截；直接输出
  Markdown 图片或某些 HTML 示例会被输出层拒绝。此次没有在线误报率统计。
- **凭据和外泄**：已有 Redactor 继续检查最终输出；此次没有证明所有模型输入均已
  统一做凭据预清洗，也没有检测所有编码外泄或普通链接携带数据的情况。
- **验收范围**：2.0.1 已部署并完成预览验收；真实群聊端到端发送和长期运行误报率不在本次测试结论内。

评估原则参考 [OWASP 提示词注入防护指南](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)：
分离指令与资料、最小权限、输入/输出检查和针对性的攻击测试需要组合使用，不能将
关键词检测或一段系统提示词视为完整防线。
