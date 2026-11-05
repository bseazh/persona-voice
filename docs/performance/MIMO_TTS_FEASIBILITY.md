# MiMo TTS 替换可行性与首次真实接口测试

日期：2026-11-05。本阶段先核对文档与凭据可用性，未切换生产路线、未拨打电话。

## 结论

可以新增“千问流式 ASR → DeepSeek → MiMo TTS”路线，只替换合成服务。不能只将 MiMo Key 填进现有 Qwen TTS：请求协议、输入方式和取消处理不同，需要独立 LiveKit TTS 适配器。保留 pipeline 与 qwen-realtime，新增路线建议名 pipeline-mimo。

## 官方依据

- https://mimo.mi.com/static/docs/api/audio/tts-post.md
- https://mimo.mi.com/static/docs/quick-start/usage-guide/audio/speech-synthesis-v2.5.md

查阅时标准模型为 mimo-v2.5-tts；接口为 https://api.xiaomimimo.com/v1/chat/completions，支持 Bearer 或 api-key 鉴权。将需要朗读的 DeepSeek 文本放入 assistant 消息，不让 TTS 重新回答问题。stream=true、audio.format=pcm16、audio.voice=mimo_default。音频在 choices[].delta.audio.data 中以 Base64 分块返回；文档示例明确为 24kHz PCM16LE 单声道，与当前 LiveKit 输出格式匹配。

标准 TTS 文档已声明低延迟流式输出可用。本次实际也收到多块音频，首块早于请求完成。voicedesign/voiceclone 文档则提示低延迟流式尚不可用，兼容模式可能在完整推理结束后一次返回；本阶段不选这两种模型。

## 与现有 Qwen 适配器的区别

|项目|现有 Qwen TTS|MiMo 标准 TTS|
|---|---|---|
|传输|DashScope 会话、send_text/flush/stop|HTTP POST + SSE|
|输入|同一合成会话持续追加 LLM 文字|文档展示一次提交待合成文字；未见追加文字的双向会话协议|
|输出|分块 PCM|SSE Base64 音频块，解码为 PCM|
|LiveKit 接入|现有 QwenDuplex|新增适配器；短句分段提交，音频按序播放|
|取消|关闭 DashScope 会话|取消请求与分段队列、关闭 HTTP 流并丢弃旧回复音频；尚需实现和测试|
|日志|已记录 Qwen 模型/音色/耗时|应记录 MiMo provider/model/voice、首包、取消与播放结果，避免误标 Qwen|

建议使用 LiveKit 的标准句子流适配能力衔接 LLM 文本，单段音频流式输出；不得等完整回答全部合成才播放。分句本身可能增加等待和句间衔接成本，不能宣称与 Qwen 双向输入等价。

## 两次真实测试

位置：开发电脑出网，非腾讯云、非 LiveKit 房间、非手机。两次相同中文测试文本：“你好，这是一次语音合成测试。我们正在检查声音是否流畅。”；标准模型、默认音色、PCM16、SSE。计时从发起 HTTP 请求到首个成功解码的音频块，包含本机网络与建连；未做人工听感或语音转录准确性验收。

|测试|HTTP|首音频|整个请求|音频块数|按 PCM 字节计算时长|非静音峰值|
|---|---:|---:|---:|---:|---:|---:|
|1|200|1.032s|2.321s|17|5.60s|18971|
|2|200|0.897s|1.919s|16|5.12s|19743|

密钥可调用该标准 TTS 模型，两次均有非静音音频。未将凭据写入本报告或 Git；本次测试在进程内使用，未修改本地或云端 .env。没有保存生成音频文件。

这两个数不是 ASR+LLM+TTS 总响应时间，也不能与此前 Qwen 不同文本、不同机器的首包数字计算提速。换 TTS 不消除已定位的 ASR FINAL 等待。

## 下一步实现范围

1. 新建 MiMo TTS 适配器，复用 HTTP 客户端，严格校验 SSE/PCM，正确报告错误；实现取消与旧音频隔离。
2. 增加 pipeline-mimo 路线及服务端独立 MIMO_API_KEY；保留原 ASR、DeepSeek、VAD、业务模板、归档和电话网关。将结束语也交给所选 TTS。
3. 网页路线选择、就绪检查和测试接口按供应商分别判断；MiMo Key 不覆盖千问 ASR Key，密钥不返回浏览器。
4. 用腾讯云上的相同短句分别测 Qwen/MiMo 各两次，再验收 LiveKit 播放、插话取消、结束语与释放；最后单独约定真实电话测试。保持每轮单变量，不能以本次接口成功声称新电话路线已上线。
