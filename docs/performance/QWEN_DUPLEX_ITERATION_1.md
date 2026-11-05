# Qwen 全双工：首次实现的验证与修正

关联 Issue #6，2026-11-05。以下均为腾讯云上的真实模型 + LiveKit AgentSession，使用合成通用语音、按时长消费的测试 sink；没有拨号、没有实际播放到听筒。

1. 首次结束控制已进入唯一结束语及房间释放记录器，但整体失败：助手历史回放错误地使用 `text`，供应商要求 `output_text`。已取消错误转换。
2. 修正后的问答/插话/结束测试通过：SDK 错误 0，记录 4 个被打断 speech handle，结束语 1 次，房间释放请求 1 次。尚未独立记录输入/播放重叠，因此这次不单独作为全双工验收。
3. 增加严格观测后的下一次测试失败：输入与播放重叠为 true，结束前 3 个 speech handle 被中断；普通问题样本发送完到首块测试 sink 音频 1.448 秒。但供应商将“今天就聊到这里吧，再见，请挂断电话。”合为一个最终转录，旧的完整单句匹配未覆盖，25 秒结束超时。未假装自动挂断通过。

最新修正：明确结束指令允许 1～3 个连续告别/挂断短句，仍采用整段匹配，不对子串“再见”直接触发。新增否定、引用、假设与复合结束句回归。后续重新跑两轮完整测试；本次失败保留。

涉及 `services/agent/qwen_realtime.py`、`realtime_control.py`、`realtime_voice.py`、`scripts/probe-qwen-agent-session.py` 以及 `tests/test_realtime_control.py` / `test_realtime_ending.py`。
