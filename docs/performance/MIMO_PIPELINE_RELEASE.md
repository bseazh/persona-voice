# MiMo TTS 独立流水线路线上线与真实验证

日期：2026-11-05。实现提交 `36b9c7d657654dc195a1f7ae27ebbf5b61832002`。GitHub Actions `41994027631` 部署成功。

## 如何使用

打开 https://phone.hehaizhao.site/consult，登录后新建网页语音咨询，在语音路线选择 **新路线 · 千问 ASR + DeepSeek + MiMo TTS**。拨号页面也增加相同选项，仍受线路、白名单、空闲状态和时长限制约束。本次没有拨打电话。

路线 ID 为 `pipeline-mimo`。普通回复与结束语均由 MiMo 合成；原来的千问流式 ASR、DeepSeek、VAD/提前生成策略、模板、文字转录、报告和电话网关沿用。原 pipeline、Qwen Realtime、豆包路线都保留，默认路线未改。

MiMo Key 独立配置为本地和服务器 `.env` 的 `MIMO_API_KEY`，权限 0600、Git 忽略，不覆盖千问 ASR Key，不返回浏览器、不写入报告。当前没有新增网页编辑 MiMo Key 的表单；后续更换此 Key 需要更新服务端环境并重启服务。就绪检查明确显示“凭据配置”，不伪装成每次都已验证额度和可用性。

## 适配方式

使用标准 `mimo-v2.5-tts`、`mimo_default`，一次提交一句文字，SSE 分块解码为 24kHz PCM16 单声道。LiveKit 标准 StreamAdapter 负责 LLM 文字分句；并非 Qwen 式双向文字输入，不等待整段回答合成完才播放。

适配器复用 HTTP 客户端，取消/关闭流时释放响应；拒绝空音频、截断输出、错误结束原因和非对齐 PCM。日志保留 MiMo 供应商、模型、音色和 `sentence-input-sse-output` 模式，不误报为 Qwen。服务端错误只暴露状态/类别，不泄漏凭据或响应正文。

## 两次正式适配器合成

测试文本相同：“你好，这是一次语音合成测试。我们正在检查声音是否流畅。”。首帧时间为请求开始到 LiveKit 适配器首个音频帧，包含该测试位置出网开销；不是电话端到端时间。

|位置|第 1 次首帧|第 2 次首帧|音频时长（1 / 2）|中途关闭后重新合成|
|---|---:|---:|---:|---|
|开发电脑|0.598s|0.626s|5.44 / 5.44s|通过|
|腾讯云生产服务器|0.690s|0.827s|5.28 / 5.60s|通过|

均返回非静音音频。测试关闭了客户端请求并成功再次使用适配器，不代表确认供应商立即停止计算/计费，也不代替真人插话残留音频测试。

## 两次公网真实 LiveKit 房间

从公网工作台 API 创建会话、领取房间令牌、发布通用问题的合成音频、订阅实际 Agent 音轨；走生产 ASR + DeepSeek + MiMo TTS，而不是预设回复或 mock。输入测试音频由 Qwen TTS 生成，仅作为通用测试夹具；实际回答 TTS 经 benchmark_config 确认为 MiMo。

|项目|第 1 次：自然结束|第 2 次：后台结束|
|---|---|---|
|会话 ID|f168990c-644e-421e-82c7-fd81b6287ae4|681ef0d9-5213-4ef9-9589-d3d3b05488a5|
|识别问题|一天有多少个小时|一天有多少个小时|
|模型回答|一天有24个小时|一天有二十四个小时，并附简短延伸|
|正常问答 SDK e2e_latency|2.609s|2.261s|
|该轮 MiMo tts_node_ttfb|0.806s|0.579s|
|客户端非静音音频帧|1255|1419|
|结束语完成事件|1 次|1 次|
|客户端断开|是|是|
|会话状态 / 报告|closed / ready|closed / ready|
|voice.error / farewell_failed|0 / 0|0 / 0|

每次只有一个正常问题，不是五轮电话性能验收，不给出提速百分比。e2e 为 SDK 停说到 Agent 输出，未测手机听筒。使用已有提前生成策略，不能将所有分段简单相加。

自然结束计时为发送整段告别音频开始到客户端断开 13.261s，包含用户告别语本身、识别、模型、结束语生成/播放和释放；后台结束请求到断开 8.588s，包含当时回复播放、轮询、结束语与释放。两者起点不同，不直接比较。

第二次主动释放房间时出现 RTC 原生 data channel closed 与测试音源 callback 日志，不能将业务事件错误数为零说成全系统无错误。测试输入夹具还出现 DashScope 未配置 workspace、回落共享网关的警告；这不是 MiMo 返回错误，也不是生产 ASR 的 workspace 证据。

沿用旧流水线结束控制，本次以客户端实际断开确认房间退出，没有实时路线的独立 phone_release/room_release 确认记录。尚未验证 SIM 手机主动挂断。不会拿房间关闭替代手机释放证据。

## 检查与剩余验收

- 5 项 MiMo 单元测试通过：请求格式与 PCM、空流、截断、HTTP 错误脱敏、提前关闭释放。
- 原流水线结束控制 4 项、实时路由与结束控制 11 项通过；Python 编译、前端 lint/类型/构建通过。
- CI 的既有测试、依赖审计、部署和公网 HTTPS 检查通过。MiMo 5 项测试为本地运行，不声称现有 CI 已运行新增依赖测试。
- 公网拨号就绪接口确认 route=pipeline-mimo，正确显示千问 ASR、MiMo TTS、DeepSeek，线路和 Agent 当前可用；未提交拨号。
- 已确认转录保存及两份报告 ready。真人音色偏好、连续多轮、噪声识别、插话打断残留、真实 SIM 挂断仍待实际验收。

## 修改文件

- `services/agent/mimo_tts.py`：独立合成适配器。
- `services/agent/agent.py`：按路线选择 TTS，注册资源关闭。
- `services/agent/consultation_voice.py`：记录实际 TTS 供应商和模式。
- `web/lib/consultation.ts`、`web/lib/phone.ts`：路线校验与独立就绪检查。
- `web/app/api/consult/[...path]/route.ts`：缺凭据提示。
- `web/app/consult/workspace.tsx`、`phone-dial.tsx`：网页路线入口与展示。
- `scripts/benchmark-phone.cjs`：允许新路线，保留重复拨号保护。
- `scripts/probe-mimo-tts.py`、`probe-qwen-room.py`：真实合成、取消恢复与公网房间探针。
- `tests/test_mimo_tts.py`：适配器回归。
- `docs/performance/MIMO_TTS_FEASIBILITY.md`：首次官方文档与 Key 测试历史；此文补充随后实现及上线结果。

本轮仅更换 TTS 服务，2.609 / 2.261s 的短样本说明 ASR 收尾与 LLM 等待仍存在。下一次性能比较应使用同一服务器、同一问题集、相同 ASR/LLM 参数，分别选 Qwen TTS 与 MiMo TTS，而不是拿原生实时模型的不同起点数据计算收益。
