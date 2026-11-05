# 百度 Lite 首次联通测试

日期：2026-11-05。范围：真实凭据鉴权与实时接口握手；未拨打电话，未切换生产路线。

## 后续排查：已联通，两轮真实 API 问答通过

保留下方最初失败记录，不覆盖历史结论。用户确认服务开通后继续排查：腾讯云使用 curl 的 HTTP/1.1 Upgrade 成功返回 101 和 `session.created`，模型为 `audio-mini-realtime-near`。本机改用官方 Python 示例使用的 websockets 库（本次 15.0.1），同一凭据和模型成功建立会话并完成两轮问答。

|轮次|输入|返回文字|输入文件发送结束 → 首音频收到|收到 speech_stopped → 首音频收到|输出音频|
|---|---|---|---:|---:|---:|
|1|请问一天有多少个小时？|一天有二十四个小时哦。|3.098s|1.395s|2.260s|
|2|那两天一共有多少个小时？|两天一共四十八个小时哦。|1.983s|0.273s|2.200s|

两轮输入转录正确，response.status=completed，输出为非零 PCM 音频，按官方示例的 24kHz、16bit、单声道保存 WAV。输入是 macOS Tingting 合成的测试语音，以 16kHz PCM 实时节奏发送；这是访问真实百度服务的探针，不是真人麦克风、LiveKit 或 SIM 电话测试。未验证主观音质、插话和挂断。

计时包含本机与供应商通信，输入文件结束不等于真人最后有声样本。两轮从输入文件发送结束到收到 speech_stopped 约 1.70/1.71s，不能将全部归因为 VAD；session.updated 中 silence_duration_ms=200 也不代表实测只等 200ms。不能拿这里数据与 Qwen 不同边界的电话测量直接计算提速比例。

故障定位到客户端握手兼容性：原 aiohttp 3.14.5 连接仍为 400，更换为 websockets 后成功；补测 aiohttp 压缩开关、显式版本头及保留 URL 编码仍失败。具体线上的请求差异尚未抓包证实，不编造某个头字段的根因。此前“需核实权限”只是排查方向，现在真实会话已证明该凭据可访问 Lite，不能再将这次 400 归因为服务未开通。

本次修改仅为独立探针，未切换生产路线。后续接入需要百度 Realtime 适配器、转录日志映射、取消/结束控制及真实电话验证，不能仅更改 Qwen 的接口地址。

## 实测

|检查|结果|
|---|---|
|本机 OAuth 获取 access_token|成功，不输出或归档令牌|
|本机 audio-mini-realtime-near WebSocket 握手|HTTP 400，响应体 `Bad Request`|
|腾讯云 OAuth 获取 access_token|成功|
|腾讯云 audio-mini-realtime-near 握手|HTTP 400，响应体 `Bad Request`|
|腾讯云 audio-mini-realtime-far 握手|HTTP 400，响应体 `Bad Request`|
|真实语音回答、转录、首音频时延|未进入会话，尚未测试|

接口按官方 Pro/Lite 文档使用 `/ws/2.0/speech/v1/realtime`，model 与 access_token 通过查询参数传入。仅采用 access_token 鉴权，不混用 IAM API Key。OAuth 成功只能确认应用凭据能换取令牌，不能证明 Lite 实时接口权限或额度适用于当前应用。

两个环境均拒绝握手，暂未证实具体原因；不能直接归咎于本机网络、余额不足或语音适配代码。需在百度控制台确认此凭据所属应用是否开通端到端 Lite，以及其免费额度适用的模型。若官方在线体验/示例也失败，应向百度确认 model 名称、应用权限及当前接口可用性；如控制台提供专用调用示例，优先核对该示例。

探针：`scripts/probe-baidu-realtime.py`，从 BAIDU_API_KEY / BAIDU_SECRET_KEY 环境变量读取凭据。计划使用本机合成的两句测试音频验证真实服务与上下文，当前停在握手阶段，未生成回答音频。探针语法与 git diff 空白检查通过，不代表服务联通。

参考：https://cloud.baidu.com/doc/SPEECH/s/nmcytnwei

鉴权：https://cloud.baidu.com/doc/SPEECH/s/Em8snejw1
