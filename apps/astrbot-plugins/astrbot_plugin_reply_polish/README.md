# astrbot_plugin_reply_polish

这是 Dududa 1.0 遗留的 QQ 输出兼容层，Dududa 2.0 默认关闭。插件只处理
`aiocqhttp` 群消息，并且只有事件明确携带 `dududa.answer_profile=long`、纯文本
长度超过配置阈值时，才会切分为合并转发。SHORT、MEDIUM、缺失或未知
AnswerProfile 始终保持普通消息；包含图片或其他非文本组件的回复也保持原样。

Dududa 2.0 的正式路径由 Runtime 的 ResponsePlan 和 Output Adapter 决定投递形态，
本插件不再根据字符数猜测回答档位。所有阈值、显示名称和 Bot QQ 号均通过
AstrBot 插件配置设置，仓库默认配置不包含真实 QQ 号。
