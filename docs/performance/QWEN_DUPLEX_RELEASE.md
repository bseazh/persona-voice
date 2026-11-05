# 全双工新路线上线与公网房间验收 2

日期：2026-11-05。独立讨论：[Issue #6](https://github.com/bseazh/persona-voice/issues/6)。生产实现提交 `1243803704087bae7161738d4a68beb6adc32b57`；GitHub Actions `41980575229` 成功完成测试、依赖审计、构建、同步、服务重启及公网检查。

## 已交付

公网 `https://phone.hehaizhao.site/consult` 的新建语音与拨号页面均增加“语音路线”。默认仍为原 ASR + DeepSeek + TTS；选择“Qwen 原生全双工（试用）”才使用新路线。每通会话固定路线；重复拨号 ID 与不同路线/号码不匹配时拒绝。

新路线使用现有千问语音配置中的密钥。普通回答不调用独立 ASR/DeepSeek/TTS。结束语也由 Qwen Realtime 生成，独立限时请求用于隔离取消竞态，保存的是实际返回的文字，不用假定文案替代真实转录。

明确结束语、后台结束请求、时长限制走幂等状态机；停止当前输出，一次告别播完后，按当前会话 ID 请求电话通道释放并删除房间。无法确认手机端释放时不会标记已确认。

## 真实房间测试 2：后台结束

会话 `b760bc0a-d3c7-46da-9b0c-8c55aeaa493b`。从公网工作台真实创建会话、领取令牌、进入自建 LiveKit 房间，通过真实 Qwen 回答样本问题，再调用页面结束按钮对应的 `voice-end` 接口。

|项目|结果|
|---|---|
|实际会话路线|qwen-realtime|
|保存的回答|一天有24个小时。|
|保存的结束语|好的，再见。|
|farewell_played|1 次|
|客户端有声音频帧|1037|
|结束请求 → 客户端断开|3.845 秒，包含最多 2 秒控制轮询、结束语生成/播放与释放|
|客户端收到断开|是|
|room_release.confirmed|true|
|后台归档状态|closed|
|voice.error / voice.farewell_failed|0|
|是否拨打手机|否|

前一真实房间自然结束测试见 `QWEN_DUPLEX_ROOM_1.md`。两种结束都在主动删除房间时出现 RTC 原生层 data channel closed 日志，不能将 `voice.error=0` 扩大为全系统无日志错误。此处确认的是客户端断开和数据库状态，不是 SIM。

## 路线与回归检查

- 未传路线字段的新建网页语音会话仍返回 `pipeline`。
- 不认识的路线返回 HTTP 400。
- 原路线拨号检查包含 console/gateway/idle/agent/asr/tts/llm。
- 新路线检查包含 console/gateway/idle/agent/realtime，不拿旧 ASR/TTS 通过结果冒充实时模型验收。
- 原号码白名单、单通电话限制、SIM 槽位限制与幂等请求逻辑保留；本次没有实际拨号。
- 本地 26 项相关单元/回归测试通过；前端 lint、类型/构建检查通过；CI 部署通过；两个生产服务为 active。
- 新路线两轮严格 AgentSession 测试首块测试 sink 音频指标为 1.170 / 1.084 秒，均确认输入/播放重叠、插话后正确回答和单次结束语。它们不是手机听筒时延。

## 实际涉及文件

运行时：

- `services/agent/agent.py`：按会话持久化路线创建对应 AgentSession，原流水线保留。
- `services/agent/qwen_realtime.py`：Qwen beta 协议转换、采样率转换、空闲显式请求限制、原生结束语、精确识别幂等取消响应。
- `services/agent/realtime_control.py`：按 response/item ID 隔离取消及迟到事件；完整结束指令识别。
- `services/agent/realtime_voice.py`：独立全双工助手和结束状态控制、当前通话释放与确认日志。
- `services/agent/consultation_voice.py`：复用日志挂钩、可覆盖的路线计时配置，区分主动结束与参与者意外断开。
- `web/lib/consultation.ts`：新增兼容旧数据的 voice_route 列、路线校验和就绪判断。
- `web/lib/phone.ts`：按路线提供拨号前检查。
- `web/app/api/consult/[...path]/route.ts`：创建/拨号持久化路线与幂等校验。
- `web/app/api/consult-agent/route.ts`：向 Agent 返回路线，提供受服务端密钥保护的当前 call ID 释放接口。
- `web/app/consult/workspace.tsx`、`phone-dial.tsx`：可选路线入口与当前路线展示。

验证与运维：

- `tests/test_realtime_control.py`、`test_realtime_ending.py`、`test_qwen_realtime_bridge.py`。
- `scripts/probe-qwen-agent-session.py`、`probe-qwen-room.py`：真实供应商探针，后一脚本修正中文数字匹配；不拨号。
- `scripts/publish-realtime-issue.py`：独立 Issue 与按标记去重的测试评论。
- `.github/workflows/deploy.yml`：增加纯 Python 取消/结束路由回归。
- `docs/QWEN_DUPLEX.md` 和 `docs/performance/QWEN_DUPLEX_*.md`：用法、失败历史与逐轮结果。

## 下一阶段与限制

现在可以在公网选择新路线试用。真实手机两通验收尚未执行，下一阶段再核实手机听感、长句、噪声、插话后的转录，以及 SIP/Asterisk/手机 SIM 的最终释放。用户意图不够明确时不会激进挂断，可使用页面结束按钮或明确说“请挂断电话”。不宣称当前为长期无人值守版本。
