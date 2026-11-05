# 豆包 Seeduplex：专用 Key 与首轮真实公网验收

日期：2026-11-05。独立路线：`doubao-realtime`；模型 `1.2.6.1`；音色 `zh_male_xiaotian_jupiter_bigtts`。跟踪 [Issue #8](https://github.com/bseazh/persona-voice/issues/8)。

## 结果

通过真实火山服务与腾讯云公网 LiveKit 房间完成音频输入、语音识别、模型生成、音频输出、文字持久化、结束语播放及房间释放。两次有效测试分别覆盖自然告别与操作员结束，后者包含连续两个问题。不是 SIM 电话验收，也不是真人麦克风听感验收。

用户通过官方 CLI 登录授权后，使用 `ve speechsaasprod CreateAPIKey` 在默认项目创建专用语音凭据，保存到现有 HTTPS 工作台的独立豆包配置。Key 只在进程内传递并在服务器加密保存，不回显、不写仓库、不使用云账号 AK/SK 作为语音 Key。

## 接口与使用入口

公网入口：https://phone.hehaizhao.site/consult 。语音配置内豆包 Key 已保存，用户不必再次填写。

|用途|已有接口|边界|
|---|---|---|
|查看配置状态|GET `/api/consult/doubao`|登录后仅返回配置状态、音色、测试结果，不返回 Key|
|测试连接/合成|POST `/api/consult/test-doubao`，JSON `{}`|需要工作台登录 Cookie、同源请求及 `X-Consultation: 1`；返回测试 WAV 的 Base64；6 次/10 分钟限流|
|完整语音测试|新建语音咨询，`voiceRoute=doubao-realtime`，再通过 `voice-token` 接入 LiveKit|真实问答走实时音频，不把合成试听当 ASR 通过|
|结束|POST `/api/consult/voice-end`，传本次 id|播放一次结束语后释放房间；电话释放仍需单独实机验收|

继续使用 HTTPS 443 和现有鉴权，不新增匿名模型代理或公开管理端口。供应商费用按实际调用计。

## 测试记录

|测试|结果|证据与计时|
|---|---|---|
|独立连接与合成|通过|HTTP 200；返回 133252 字节 WAV；整次 API 耗时 3.414s。包含连接、整段合成、收集、关闭及 HTTP，不是首响应时延|
|首次房间尝试 `d304d9ab-c279-4812-b0ef-dfce1a56e658`|失败，保留|供应商会话已连接；适配器在实际音频事件处理时失败，房间被故障结束流程释放|
|重启后尝试 `0e551d41-33f0-453f-8ece-396bc3794bf3`|无有效问答，保留|08:33:27.837 UTC 创建，worker 08:33:29.646 UTC 才注册；无 voice.started 或供应商连接事件，0 条消息，探针超时后清理。不把它算成模型失败或有效性能样本|
|自然结束 `91e21f23-e3dd-466d-bff7-5971c4b7266f`|通过|一天有多少小时 → 正确回答 24；客户端 844 个有声音频帧；5 条文字；结束语 1 次；room_release.confirmed=true；报告 ready|
|操作员结束 `9b3b80cc-bd0f-4f1e-87df-781ceb75cf75`|通过|一天有多少小时 → 24；连续追问 2+2 → 4；客户端 1523 个有声音频帧；6 条文字；结束语 1 次；room_release.confirmed=true|

测试输入是通过现有 Qwen TTS 生成的标准问题音频，随后作为用户音轨送入 LiveKit；豆包识别和普通回答均由真实 Seeduplex 生成，没有预设问题答案。开场和告别是系统规定的短句，通过豆包语音合成。

自然结束计时为“开始发送告别音频 → 客户端断开” **7.620s**，包含用户整句话的播放时间；操作员结束计时为“调用结束接口 → 客户端断开” **3.344s**。两者起点不同，不能相减得出策略收益，也都不是普通问答首响应时延。本轮不计算提速百分比。

两通有效房间的 `voice.error` / `voice.farewell_failed` 均为 0；删除房间时 RTC 原生层仍有 data channel closed 日志，不将业务事件无错误扩大为全系统无日志错误。

## 根因与修复

官方示例中音频 delta 带 response_id，但真实服务返回的 `response.output_audio.delta` 只包含 type、delta、event_id；response_id 在之前的 `response.output_audio.started` 与最后的 done 事件中提供。旧适配器要求每个 delta 都带 ID，于是触发 `missing_response_id`。

现在依据收到的音频 started 边界关联无 ID 分块；没有有效边界时丢弃，取消时清空关联，被取消/完成的 ID 不会再次开启；新响应不被迟到的取消确认关闭。WebSocket 有序消息是此关联的前提，不能给无边界音频随意猜一个活动回复。

另将安全错误码加入 `voice.provider_failure`，便于区分协议字段问题、输入背压或供应商错误，不记录密钥或完整上游错误负载。新增真实事件形状回归；本地 WebSocket 集成用例也改成“started 带 ID、delta 不带 ID”，避免仅验证理想化文档示例。

修改文件：

- `services/agent/doubao_realtime.py`：音频边界绑定、取消隔离、安全错误码。
- `tests/test_doubao_realtime.py`：实际事件形状和迟到音频用例，共 8 项适配器测试。
- `scripts/probe-doubao-wire.py`：stdin 凭据、仅输出事件形状与音频长度的真实服务诊断。
- `scripts/probe-qwen-room.py`：保留其他路线，增加豆包选择、连续第二个问题、房间释放核验。
- `docs/DOUBAO_DUPLEX.md`：更新已配置与真实验收状态。

## 下一步与限制

公网可以直接选择豆包路线开始体验。仍需真人连续对话、插话残留、长句/噪声、长时间保活，以及统一计时口径的性能对照；本轮没有证明长期稳定性，也没有验证 SIM 手机自动挂断。第一次普通问题后模型仍可能解释较长，不因端到端模型就假定回复自然或简短。

每次后续测试继续追加 Issue #8，保留失败与改动版本，不覆盖历史。
