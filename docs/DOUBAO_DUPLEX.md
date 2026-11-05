# 豆包 Seeduplex 独立实时语音路线

2026-11-05。状态：代码已部署腾讯云，项目专用 Key 已加密配置；真实供应商连接/合成、公网房间语音问答与两种结束方式通过。尚未进行豆包路线 SIM 电话、真人麦克风或时延 A/B 验收。独立讨论：[Issue #8](https://github.com/bseazh/persona-voice/issues/8)。后续真实验证与修复记录见 [首轮验收](performance/DOUBAO_REAL_SERVICE_1.md)。

## 配置入口

打开 https://phone.hehaizhao.site/consult ，登录后进入「语音配置」→「豆包原生全双工 · Seeduplex」。

1. 从 [火山语音控制台 API Key 管理](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default) 获取 Key，确认开通 Seeduplex 端到端实时语音权限与额度。这不是千问 Key，也不是通用云账号 AccessKey。
2. 填写「豆包 API Key」、选择音色，点击「保存豆包 Key」。凭据通过 HTTPS 保存到腾讯云 PostgreSQL 的独立 `doubao` 配置，AES-256-GCM 加密；不回显、不写 GitHub、不覆盖千问配置。不需要把明文 Key 再贴到聊天里。
3. 点击「测试连接与音频」。服务端真实建立会话、合成测试文字、返回 WAV 试听并正常关闭；会消耗服务额度，不拨号。此测试只证明连接、会话参数和返回音频，不是 ASR 或全双工电话验收。
4. 新建网页语音，选择「豆包 Seeduplex 全双工（待验收）」。实际问答由实时模型生成；固定文字只用于开场、结束语和配置测试，不是预设业务答案。结束后复用现有转录与报告。
5. 完成网页验收后再在电话工作台选择同一路线。号码白名单、SIM、线路状态、重复拨号保护保持有效；无 Key 或连接音频测试未通过时禁用拨号。当前不自动拨打任何号码。

配置页即服务器的配置入口，不需要 USB、SSH 或本地脚本同步 Key。本地开发如需要真实服务测试，应单独提供受保护凭据；此版本不新增一份自动明文 `.env` 副本。

## 官方文档阅读结论

- [端到端实时语音 Seeduplex](https://docs.volcengine.com/docs/doubao-voice/end-to-end-real-time-voice-full-duplex-version?lang=zh)，页面更新 2026-11-03；[接入必读](https://docs.volcengine.com/docs/doubao-voice/access-must-read?lang=zh)，更新 2026-10-26。已阅读官方 Python 示例的配置、收发事件与关闭处理。
- 新版为 JSON WebSocket 事件，入口 `wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`，`X-Api-Key` 鉴权；模型固定 `1.2.6.1`。不能拿旧版二进制协议、AppID/Token 接入方式直接替换。
- 音频输入：单声道 16kHz/int16，20ms/640 字节，按真实节奏发送。输入过快/过慢或低质量都可能导致异常。
- 音频输出：24kHz，显式请求 `pcm_s16le`。官方 `pcm` 输出是 32 位，不能按现有 16 位链路解释。
- 无麦克风帧时发 `input_audio_mute.commit`，恢复发 `input_audio_unmute.commit`；先发 `session.close` 并等待 `session.closed`，再关闭 WebSocket。
- 下行协议不是 OpenAI/Qwen 的同名兼容接口。例如没有照搬 `response.create`，开场使用官方 `speech_text_buffer.commit`，普通回答由实时音频触发。

## 实现与控制

通过 LiveKit 公共 `RealtimeModel / RealtimeSession` 扩展点接入独立适配器，不改 LiveKit 源码。输入在播放期间持续上传，利用模型转录开始事件触发 LiveKit 的标准插话控制；目前没有启用 LiveKit 的“双方持续同时说话且永不打断”能力标记，不把全双工传输混同为任意重叠发言策略。

按 response_id 隔离旧音频，取消或已完成的回复不重新打开。用户明确告别时同步停止普通回复，使用同一豆包服务合成一次短告别，等实际播放完成再释放本次电话和房间；故障仍尝试释放，并分别记录是否确认。沿用保守的完整结束指令识别，否定、引用不激进挂断。

日志增加 provider_connected（含供应商 logid）、realtime_event（含 response_id/item_id）、realtime_first_audio、provider_failure、provider_closed。不记录音频、Key 或完整原始供应商错误。该路线转录完成事件与 Qwen 停说事件口径不同，未经统一音频观测不能宣称谁更快。

首版普通语音问答与转录接入，未开启联网搜索、音乐、复刻音色、视频、函数工具或任意历史上下文编辑。供应商异常当前明确失败并由既有会话结束机制收束，不在活跃电话中无界重连或重放用户音频；5xx 自动重连及上下文恢复是后续独立验收项。未声称长期无人值守能力完成。

## 验证边界

本地协议测试覆盖 PCM16 格式、20ms 节奏、静音通知、有界输入队列、旧回复隔离、结束转录同步阻断输出；本地假 WebSocket 服务与真实 LiveKit AgentSession 验证开场音频、文字入历史和正常关闭。这些是适配器测试，不是供应商成功响应，也不作为性能报告。

实现提交 `490517f`，GitHub Actions `41989776315` 的测试、审计、构建、部署和公网检查均成功。新适配器 7 项测试在本地与腾讯云各通过一次；本地另通过原结束控制 11 项、电话保护 11 项、Qwen 兼容 1 项，网页 lint/build 通过。协议测试的消费端不支持暂停，SDK 提示忽略 false-interruption resume，这不是实机打断验收。

初次部署时公网已确认：豆包设置 configured=false、对应 dial_enabled=false；不带登录凭据读取配置返回 401。后续用户授权后，通过 CLI 创建项目专用 Key 并保存，真实音频测试已通过；没有使用旧千问凭据访问火山服务，也没有拨号。第一次真实房间发现无 ID 音频分块兼容问题并修复，完整过程见首轮验收报告，不覆盖早期失败记录。

真正验收顺序：保存 Key → 腾讯云连接/音频测试 → 网页连续问答、停顿、插话、文字完整保存 → 自然告别与页面结束 → 两通授权真实电话与逐轮计时。没有有效 Key 前不填写真实时延数字。

## 文件

- `services/agent/doubao_realtime.py`：独立协议与 LiveKit 适配器。
- `services/agent/agent.py`、`realtime_voice.py`：路线选择和共享结束控制。
- `web/lib/consultation.ts`、`phone.ts`：独立加密配置与路线就绪判断。
- `web/app/api/consult/[...path]/route.ts`、`web/app/api/consult-agent/route.ts`：受登录/来源校验保护的配置与测试、受内部鉴权保护的 Agent 凭据分发。
- `web/app/consult/doubao-settings.tsx`、`workspace.tsx`、`phone-dial.tsx`：配置与三路线入口。
- `scripts/test-doubao-realtime.py`：密钥仅经 stdin 的真实服务音频探针。
- `scripts/benchmark-phone.cjs`：显式支持新路线，不自动重拨。
- `tests/test_doubao_realtime.py`：协议与 LiveKit 调度回归。
