# 采购知识工具输入输出日志

新增事件保存在原有会话事件日志中（经 journal.emit 加 voice. 前缀），不写浏览器控制台，不记录 API Key 或 Authorization。

- `voice.knowledge.tool_input`：工具执行前的原始 `input.query`、工具名称、时间与 `tool_id`。
- `voice.knowledge.tool_output`：与 input 相同的 `tool_id`、检索 `request_id`、实际返回给模型的完整 JSON 字符串 `output`、SHA-256 和耗时。
- `voice.knowledge.tool_cancelled` / `voice.knowledge.tool_failed`：取消或异常，不伪造成功输出。异常仅记录类别。
- 原有 `voice.knowledge.started/completed` 保留展开后的检索词、来源正文及来源哈希。
- 原有 `voice.wire_tool_output` 是实际发送时点及提供方 call_id；新增 output 记录的是工具返回边界，不等于提供方已接收确认。

通过同一会话事件接口查看。真实查询及资料可能敏感，完整输入输出沿用受保护的会话日志权限，不自动发布到公开 GitHub。

## 上一通实际样本（历史日志摘录，不冒充新增日志）

会话：`1a9f8d6d-1a30-4143-b41f-32da7966b5f6`。

输入：`Phoenix 1600 滚筒筛 筛筒长度 直径`。

检索编号：`f2d7a1c90bce91f4`；耗时 308ms；status=ok。

结果来源：`viking://resources/persona_voice_procurement_demo/procurement-expansion/04-phoenix1600/公开参考_Phoenix_1600_滚筒筛_1.md`。

正文包含“筛筒长度 4.9 m，直径 1.54 m，筛分面积 19 m²”，同时包含料斗、动力、运输尺寸、应用及采购边界。查询只需要两个尺寸，返回却含多类参数；尚不能据此量化其对模型首音频延迟的影响。本轮仅补日志，不修改召回、裁剪或回答行为。

## 修改与验证

修改 services/agent/procurement_knowledge.py；测试 tests/test_procurement_knowledge.py。8 项测试通过，包括原始输入、返回字符串一致性、哈希、关联编号和取消不产生成功输出。未拨打新电话。
