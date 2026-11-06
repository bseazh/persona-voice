# 语义轮次手机实测：第1通

日期：2026-11-06；版本 cec43f1；会话 13b494eb-3a1c-4762-9bd9-169288bf3e52。真实 SIM 电话，采购模板，Qwen 全双工与 OpenViking。

## 结果

voice.benchmark_config 和服务端 voice.wire_session 均确认 smart_turn_v2。接通至线路结束约111.15秒，15条消息。8条助手 turn_timing 中1条 interrupted=true，发生在用户继续补充采购提问时；其余7条完整播放，包括三次参数回答。

旧模式上一通为16条助手发言中13条中断，新模式本通为8条中1条。两通问题、附和和插话次数不同，不能将比例变化当成严格A/B误打断率或证明所有附和已过滤。本次没有 ambient_audio 事件，不能据此量化被过滤声音数量；仍需第二通独立验收。本轮未自动补拨。

## 知识与计时

1600的4.9m/1.54m、2100的6.45m/1.94m、3300的9.31m/2.32m均与返回资料一致。3300与1600比较只新增查询3300，复用了前面1600证据。报价问题未编造价格。

| 查询 | speech_stopped至工具开始 ms | 检索 ms | speech_stopped至首音频 ms |
|---|---:|---:|---:|
| Phoenix1600尺寸 | 27 | 619 | 1666 |
| Phoenix2100尺寸 | 24 | 255 | 1765 |
| Phoenix3300尺寸 | 25 | 479 | 1980 |

重要限制：语义模式和声学模式的 speech_stopped 时机不同。新模式该事件至工具开始仅24–27ms，说明此前使用的边界不能用来独立衡量模型完整处理时间。1.666–1.980秒是事件之后的等待，不是实际停说至手机听到语音的完整延迟；不能与旧模式2.55–3.73秒直接相减宣称提速。需同步原始音频停说时间或统一客户端采样口径再做延迟对比。

工具输入输出日志已捕获本通三次查询，包含原始query、完整返回JSON、tool_id、request_id和耗时。未记录 voice.error/failed 类事件；report.generated 确认报告生成成功，耗时2402ms。

## 收尾遗留问题

最后用户在较长句子末尾表达“没事，再见”，模型回复“好的，再见。”；没有 voice.ending / voice.farewell_played，结束原因 participant_disconnected，线路随后 channel_closed。现有 explicit_end 仅完整句式匹配，未覆盖这次带前置说明的自然告别。因此不能声称本通自动挂断成功，也不能依据断开事件确认哪端先挂断。

后续应在不误判引用、否定、条件句的前提下补充自然告别识别与回归测试。本轮只记录问题，不追加修改，以免混淆本次语义轮次验收。

## 文件与原始记录

本轮新增报告 docs/performance/QWEN_SMART_TURN_PHONE_1.md，无运行代码修改。上一轮实现文件与合成音频对照见 QWEN_SMART_TURN_V2.md。

原始会话保存于受保护的 BigApple输出/latency-benchmark/procurement-smart-turn-20261106-1.json；不在公开Issue上传完整私人转录或电话号码。
