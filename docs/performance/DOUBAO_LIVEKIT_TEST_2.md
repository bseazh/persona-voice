# 豆包：复用 Qwen 全双工架构的 LiveKit 测试

日期：2026-11-05。路线 `doubao-realtime`，模型 `1.2.6.1`。

本次不创建新架构、不操作网页、不拨号。复用 `scripts/probe-qwen-room.py`、LiveKit 房间、Agent、RealtimeController 和转录/报告，只选择现有豆包适配器。普通回答由真实模型生成，测试问题音频由 Qwen TTS 合成。

执行命令（腾讯云项目根目录）：

```sh
.venv-agent/bin/python scripts/probe-qwen-room.py --route doubao-realtime --ending natural --followup
.venv-agent/bin/python scripts/probe-qwen-room.py --route doubao-realtime --ending operator --followup
```

## 结果

|项目|第 1 轮|第 2 轮|
|---|---|---|
|会话 ID|a02de899-6560-4931-a3cc-8a2678ddd872|2a865220-c120-4da6-abfc-9a515b7f9b4e|
|连续问答|24 小时、2+2=4，通过|24 小时、2+2=4，通过|
|数据库创建至关闭|30.903s|28.841s|
|识别最终文字至 Agent 首音频：第 1 问|0.527s|0.576s|
|识别最终文字至 Agent 首音频：第 2 问|0.280s|0.255s|
|客户端有声音频帧|964|994|
|结束方式|自然告别|操作员 API 结束|
|结束动作至断开|7.919s（含告别输入音频）|4.151s|
|结束语次数|1|1|
|房间释放/报告|confirmed / ready|confirmed / ready|
|voice.error / farewell_failed|均 0|均 0|

计时来源：服务端 `voice.realtime_event` 的 input_audio_transcription.completed 与随后 `voice.realtime_first_audio` 的时间戳差；排除开场和告别。该指标不包含识别收尾等待、客户端网络和实际播放，不能称作用户说完至听到回复的完整时延。数据库会话时长也不是供应商计费时长。

房间释放时存在原生 RTC 的 audio_source callback / data channel closed 日志。业务验收通过不等于全部底层日志无错误。未进行真人抢话、手机听感或 SIM 挂断测试。

## 开销边界

这条路线的日常问答由豆包端对端处理，不再分别调用 Qwen ASR、DeepSeek 对话和 Qwen TTS；归档报告仍可能调用配置的报告 LLM，不能算成完全没有其他模型费用。开场在主语音会话内合成，告别使用独立的豆包合成会话，应包含在后续账单核对中。

本次每轮探针额外生成 3 段 Qwen TTS 输入素材（问题、告别、追问；operator 模式也会生成未使用的告别素材），两轮合计 6 次素材合成。这不是正式用户通话所需费用。

两轮业务日志 usage 事件均为 0，未取得供应商计费 token、正式账单金额和账户实际单价，因此费用填 N/A，不填 0，不用客户端音频帧数或会话时长推导金额。下一步需要补供应商用量/账单核对，分别列豆包、报告 LLM、测试素材 TTS、服务器与电话费用。

## 偏离纠正记录

最初误将“不要网页”理解为绕过 LiveKit，执行了两次直连短测试（同一个 Qwen 素材生成 1 次）：输入语音各 2.380s、发送音频含静音 6.220/5.840s、收到合成音频 13.783/10.998s，未返回 usage。用户纠正时这两次已结束，因此仍存在真实调用开销，不能抹去或混入 LiveKit 对比。临时 `scripts/test-doubao-direct.py` 已从本地和服务器删除，未提交 Git。后续沿用 LiveKit 链路。

跟踪：[Issue #8](https://github.com/bseazh/persona-voice/issues/8)。本轮未修改生产语音代码。
