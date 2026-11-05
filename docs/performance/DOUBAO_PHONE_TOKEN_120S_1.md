# 豆包 LiveKit 电话：120 秒目标，提前中断与真实 Token

日期：2026-11-05。会话 `b65d19f0-d28e-4703-9007-528f91b55bb5`，路线 `doubao-realtime`，模型 `1.2.6.1`。只拨打一次，没有自动重拨。

## 实测结果

目标接通后 120 秒，实际 **56.576 秒**，未完成两分钟验收。已保存 9 条对话消息。结束原因 `voice_provider_error`，具体本地异常 `input_backpressure`：输入音频队列达到上限。并非供应商返回余额不足或 Token 耗尽。

结束后供应商 session.closed 已确认、LiveKit 房间释放已确认；额外核对 Asterisk 为 0 active channels / 0 active calls。日志的 handset_release_confirmed=false，不能称作独立验证了手机 UI 已挂断。

## 供应商返回的实际 Token

新增安全日志捕获 `response.done.response.usage`。按同一连接中的唯一 event_id 记录 5 条；数据是各 response 的用量，不是按文本字符或通话时长推算。

|event_id|输入音频|输出文字|输出音频|total_tokens|
|---|---:|---:|---:|---:|
|event_19|0|28|139|167|
|event_44|36|35|69|140|
|event_111|72|82|199|353|
|event_167|64|80|215|359|
|event_254|132|127|285|544|
|合计|304|352|907|**1563**|

输入文字及图像 Token 均为 0。合计输出 1259 Token，输入 304 Token。第一条包括开场合成。未收到用量的未完成/取消响应不据此当作免费，未取得完整账户账单，所以这是**已观察到的供应商用量合计**，不保证覆盖异常结束前所有收费。

没有使用测试 TTS 素材，输入来自真实电话。归档报告 LLM、SIM 通话和服务器开销不在这 1563 Token 内。未取得账户单价与账单，不给出实际人民币扣费，也不将本次线性放大为“2 分钟 Token”。

## 本轮修改与验证

- `services/agent/doubao_realtime.py`：捕获主连接与告别连接的 usage，仅存数字；事件字段形状去重记录，不保存原始音频/密钥。
- `tests/test_doubao_realtime.py`：新增嵌套 usage 安全过滤与字段形状去重测试，9 项通过。
- 生产运行时先同步适配器并确认 worker 注册，之后才拨号。未修改音频发送节奏。

下一步应排查 `pump()` 中发送耗时/调度延迟及每包等待造成的输入队列累积，不宜仅扩大队列掩盖延迟。尚未用时间序列证明具体积压来源；本轮不声称已修复。完成修复后另约一次两分钟测试。

原始通话数据保存在本地忽略目录，不提交私人对话；本报告仅含技术字段及用量。[Issue #8](https://github.com/bseazh/persona-voice/issues/8)。
