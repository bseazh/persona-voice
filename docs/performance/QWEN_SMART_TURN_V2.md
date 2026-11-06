# Qwen 语义轮次：减少附和声误打断

2026-11-06。基线真实电话：16条助手发言中13条 interrupted=true，不把所有打断都认定为误打断。

## 修改

- services/agent/qwen_realtime.py：默认 QWEN_TURN_MODE=smart_turn_v2；在传输适配层替换 OpenAI SDK 的声学模式，避免向 SDK 传入不支持的枚举。保留 server_vad 配置回退。手动 turn_detection=null 与局部 session.update 不受影响。
- 同文件：turn_invalid 清除 server_turn_pending，避免等待不会生成的自动回复；仍向 SDK 传递停说事件以关闭说话状态。ambient_audio_transcription 仅写审计，不触发用户轮次或结束命令。记录实际请求和服务端确认的 turn_detection 及停说 reason。
- services/agent/realtime_voice.py：benchmark_config 记录实际模式，语义模式不再误报声学500ms。
- .env.example：回退配置；tests/test_qwen_realtime_bridge.py：新增模式、局部更新、无效轮次、附和事件测试。
- scripts/probe-qwen-turn-mode.py：真实提供方、合成音频、两模式各两轮对照，无电话呼叫。

不关闭麦克风，不取消有效插话，不改变知识库检索、音色或语速。语义模式的 silence_duration_ms 按官方文档不生效，服务端回显3000也不能解读成实测固定等待3秒。

## 验证

本地27项实时相关测试通过。真实 Qwen + OpenViking 适配器集成成功，服务端确认 smart_turn_v2，正确回答 Phoenix2100 的6.45m/1.94m，28个音频帧、无模型错误。该集成为文字触发，不能证明音频轮次效果。

另用同一组合成音频，AI长回答期间输入“嗯”，再输入“停一下，我想问另外一个问题”，原始记录：BigApple输出/qwen-validation/turn-mode-1793950983426505000.json。

| 模式 | 轮次 | 附和阶段触发 speech_started | 附和阶段取消原回答 | 真正插话触发 speech_started |
|---|---:|---|---|---|
| server_vad 500ms | 1 | 是 | 是 | 是 |
| server_vad 500ms | 2 | 是 | 是 | 是 |
| smart_turn_v2 | 1 | 否 | 否 | 是 |
| smart_turn_v2 | 2 | 否 | 否 | 是 |

新模式两轮均在明确插话后取消原回答并回复“好的，请讲”或类似短句。服务端仍可能返回附和转录；未观察到附和阶段触发轮次，不代表所有附和都会返回 ambient 事件。合成“嗯”被识别为日文“うん”，结果不能外推为所有中文附和已解决。

限制：这是提供方协议层的合成音频测试，无手机回声、蜂窝编码和真实口音；不提供手机端打断延迟结论。仍需两通真人验收：普通附和、明确插话、型号分段报读、主动告别、定时结束。测试没有修改主动收尾控制。

官方依据：https://docs.bailian.console.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api

https://docs.bailian.console.aliyun.com/zh/model-studio/fun-audiochat-client-events

## 回退

服务端 .env 设置 QWEN_TURN_MODE=server_vad 并在无活动通话时重启 Agent。重新开会话后核对 voice.wire_session 与 voice.benchmark_config；旧会话不会被动态切换。
