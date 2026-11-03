# 故障排查手册

适用：`v1.0.0` 自建 LiveKit + 千问语音 + Asterisk / 安卓 SIM 网关。整理日期：2026-11-03。历史原因见 [调试复盘](DEBUGGING_RETROSPECTIVE.md)。

## 0. 操作边界

- **只读检查**：状态、近期日志、端口和拨号计划；本手册默认先执行这些。
- **测试调用**：TTS/实时测试消耗 API 额度；观察脚本可能输出对话文本，只在授权测试中运行。
- **变更操作**：重启、配置、发布会影响服务，必须先检查活动通话与网页房间；Asterisk 无通道不代表浏览器无人使用。
- **真实拨号**：需要确认号码、SIM、接听人可用且已同意；可能产生话费。不要把拨号命令当健康检查循环执行。

不执行全量环境变量输出、不直接展示 `.env` 或 SIP 密码文件。日志对外发送前脱敏。不要通过关闭 TLS 验证、全开放防火墙或反复更换 Key“碰运气”。

## 1. 先选故障层

```text
页面/API 不正常 → Web、访问码、反向代理
房间进不去     → 令牌、LiveKit 信令、生命周期
能进房无识别   → 输入音量 → 音频轨道 → Agent → ASR
有文字无声音   → TTS 单测 → 返回音频 → 浏览器播放/电话 RTP
电话未接通     → SIM、网关注册、白名单、拨号计划
电话接通无声   → 手机 ↔ Asterisk 回声 → Asterisk ↔ SIP 桥 → Agent
能说但答错     → LLM/知识/提示词，不先改音频网络
```

## 2. 服务器基础检查（只读）

先登录部署服务器，在项目目录执行：

```bash
cd /home/ubuntu/Project/persona-voice
date -Is
sudo systemctl is-active persona-voice-web persona-voice-agent persona-livekit persona-livekit-sip asterisk redis-server caddy
curl --fail --show-error --max-time 10 https://phone.hehaizhao.site/api/token
curl --fail --show-error --max-time 10 https://phone.hehaizhao.site/livekit/
sudo asterisk -rx 'core show channels concise'
sudo asterisk -rx 'pjsip show contacts'
```

正常：服务均 `active`，token GET 返回健康 JSON，LiveKit 返回 `OK`。无电话时通道列表为空。`k60-test` 应 `Avail`；本机 `livekit-local` 未启用 qualify，显示 `NonQual` 不等于失联。

失败时先看对应服务日志，不立即全部重启：

```bash
sudo journalctl -u persona-voice-web --since '10 minutes ago' -n 120 --no-pager
sudo journalctl -u persona-voice-agent --since '10 minutes ago' -n 120 --no-pager
sudo journalctl -u persona-livekit --since '10 minutes ago' -n 120 --no-pager
sudo journalctl -u persona-livekit-sip --since '10 minutes ago' -n 120 --no-pager
```

健康检查不验证模型权限、麦克风或真实音频；`active` 只表示进程运行。

## 3. 401 / 422 / 502：先看哪个接口

| 请求或错误 | 解释 | 下一步 |
| --- | --- | --- |
| `POST /api/token` 401 | 网页访问码不匹配 | 重新输入正确访问码；管理员核对服务器配置，不把 LiveKit Secret 填到访问码框 |
| `/api/transcribe` 401 | 录音请求的访问码验证失败 | 结束会话后重新输入访问码；检查前端请求是否带 `x-voice-access-code`，不要分享该头的值 |
| `/api/transcribe` 422 | 当前接口可能是无有效文字 | 查看 JSON 的 code、requestId、metrics；不是笼统的“API Key 错误” |
| `/api/transcribe` 502 | 上游请求失败、解析或超时 | 匹配 web 日志的 `qwen_asr_failure`、请求编号和上游状态 |
| 上游 401 / 403 | 供应商凭据或权限 | 核对 Key、业务空间、地域及模型权限 |
| 上游 400 | 请求参数、音频或 workspace 等问题 | 根据供应商具体 code/message 判断，不能只看 HTTP 数字 |
| 429 | 本地或供应商限流 | 区分来源；按提示等待，核对限额，不密集重试 |
| 旧 `/api/conversation` 422 / 404 | 旧架构接口 | 检查是否打开旧页面、缓存或部署版本，不恢复旧模拟接口 |

浏览器 Network 面板只记录 URL、状态、脱敏响应和时间；不要复制包含访问码、token 或录音请求体的完整 curl。

## 4. 一直聆听 / 录音无文字

1. 入房前选择实际麦克风，对着它说完整句子，确认音量条随人声变化；允许浏览器麦克风权限。
2. 用录音模式录 3–5 秒，试听是否有人声。只有音量变化可能只是底噪。
3. 录音正常但没有文本：看 web 日志与请求编号。`NO_SPEECH` 且 `peakDb < -55` 表明服务器收到的信号接近静音；有信号仍无字则查人声清晰度、编码与上游返回。
4. 录音可以识别但实时失败：确认已切回实时模式、麦克风发布成功，Agent 加入同一房间；检查 `RoomIO linked to participant` 和 `qwen_streaming_connected`。
5. 已建立 ASR 连接仍无识别：核对上行轨道实际音频、Agent 收到的输入和供应商超时。ASR “connected” 不是识别成功证据。

成功标准：已说的完整句子成为正确文本，并得到相关回复。不要仅以“进入 listening 状态”验收。

## 5. 有文字回复，但没有声音

### 5.1 先隔离 TTS（消耗模型额度）

在有正确 `.env` 的项目根目录运行：

```bash
.venv-agent/bin/python scripts/check-tts.py
```

正常：输出 `ok: true`，生成 `BigApple输出/tts-check.wav`，存在非零时长与有效峰值。试听文件确认内容正常。文件有效不代表浏览器或电话一定能听到。

失败时：按输出的 HTTP 状态与 provider_error 排查。workspace 不匹配需更正配套凭据；如果单独设置 TTS Key，应同时核对 `DASHSCOPE_TTS_WORKSPACE`。当前支持独立 TTS 凭据，无需连带更换已工作的 ASR Key。

### 5.2 TTS 正常，再查输出链路

- 浏览器：点击“测试扬声器 / 耳机”；出现“点击开启助手声音”时主动解锁播放。检查系统输出设备、标签页静音、媒体音量及返回音频轨道。
- 电话：看第 8 节双段 RTP 和回声测试。不要把浏览器 autoplay 问题套用到电话。
- 没有回复文本：先查 LLM 是否返回，不要直接归为 TTS。

成功标准：用户实际听到与回复文本一致的声音；不能只依据服务器有文件。

## 6. LiveKit 超时 / closed engine / disconnect

1. 确认当前 URL 为自建 `/livekit` 入口，而非旧 Cloud 项目。前后端凭据和 `LIVEKIT_AGENT_NAME` 要匹配。
2. 基础检查失败：查 Caddy 和 LiveKit；HTTPS 正常但无媒体，查 TCP 5052、UDP 5053 及客户端网络。
3. `cannot negotiate on closed engine`：记录连接/退出/重试时序。避免在旧 Room 已关闭后继续开启麦克风；先完整退出再重进，不在卡住的页面反复连点。
4. `CLIENT_INITIATED`：与用户挂断时间对应时可属正常；如果发生在主动说话过程中，继续核查前端状态、房间事件和服务重启时间。
5. 当前没有 TURN/TLS，受限网络问题可能需要增设中继；不可仅凭 HTTPS 可访问认定媒体也通。

成功标准：房间连通、双方轨道有收发、实际语音往返成功。

## 7. 手机无法拨出 / SIP 未注册

在连接安卓 USB 的电脑执行（不是在云服务器执行）：

```bash
adb devices
adb shell am broadcast -n io.github.sparkcyf.voicesipagent/io.github.sparkcyf.voicesipagent.app.AdbControlReceiver --es op status
```

正常预期：设备 `device`，网关 `ready=true`，`sip=ready`，`shizuku=CONNECTED`，当前 SIM 与 `default_sim` 一致。未授权应在手机确认 USB 调试；设备不在线先查线缆/连接。多个设备时使用 `adb -s <SERIAL>` 指定目标。

手机重启后要重新核对 Shizuku、权限和网关状态，不能假设系统会全部自动恢复。`audioReady=true` 只说明接口检查就绪。

服务器核对：

```bash
sudo asterisk -rx 'pjsip show contacts'
sudo asterisk -rx 'dialplan show test-headers'
sudo asterisk -rx 'dialplan show sim-ai-outbound'
```

换卡后确认：实体卡、网关默认槽位、`X-VSA-SIMSLOT`、允许拨号号码与实际测试目标一致。界面的 SIM 2 对应逻辑槽位 1。修改号码不能只改某一个拨号字符串；参照运维说明同步受限目标与网关白名单，不扩大成任意号码。

## 8. 电话接通，但单向 / 双向无声

在通话进行中执行只读检查：

```bash
sudo asterisk -rx 'pjsip show channelstats'
sudo asterisk -rx 'rtp show settings'
sudo asterisk -rx 'core show channels concise'
```

AI 电话正常应有 `k60-test` 和 `livekit-local` 两条媒体腿，Receive/Transmit 随音频传输增加。播放夹具或静音等待时，某方向暂时不增长未必异常；在主动说话、AI 回答时分别观察。

| 观察 | 优先定位 |
| --- | --- |
| 手机有采集信号，服务器 `k60-test` 收包为 0 | 安卓→服务器 RTP、防火墙、NAT、网络 |
| 服务器发包但手机接收为 0 | 返回 RTP 目标地址、UDP 放行和手机网络 |
| 回声双向正常，AI 电话无声 | `livekit-local`、SIP dispatch、Agent 与模型 |
| 两侧有包但用户听不到 | 包可能承载静音；查音频峰值、网关注入与实际输出 |
| 识别正确但回复无声音 | LLM/TTS 返回、SIP 下行音频与手机注入 |

手机日志（电脑侧，只读，输出分享前脱敏）：

```bash
adb logcat -d -t 300 -s VoiceSipAgent:V VsaPrivileged:V VsaTap:V
```

结合 `down/up`、峰值、包数和 `backendFailures` 判断，避免只看一个 ready 标志。Asterisk 的 Receive/Transmit 是以服务器为视角。

防火墙应核对 Asterisk UDP 10000–10019；LiveKit UDP 5053 是另一条链路。不要简单把全部 UDP 对公网放开。

需要回声或真实 AI 重测时，先征得接听人同意，按 [SIM AI 操作说明](../ops/SIM_AI.md) 执行一次受限拨号。最终让接听人明确反馈提示音、自己的回声或 AI 回复，不能用“电话接通”替代验收。

## 9. Asterisk ↔ LiveKit SIP ↔ Agent 排查

```bash
sudo systemctl is-active persona-livekit-sip
sudo ss -lntup | grep -E '5060|5062'
sudo asterisk -rx 'pjsip show endpoint livekit-local'
sudo asterisk -rx 'dialplan show livekit-ai'
sudo journalctl -u persona-livekit-sip --since '10 minutes ago' -n 100 --no-pager
```

预期：桥监听本机 5060，Asterisk 本机 UDP 5062；SIP 日志出现加入 `sim-ai-` 房间，Agent 日志收到 job 并绑定 SIP participant。

- 未进房：查本机 SIP 服务、trunk 来源限制、目标 9000 与 dispatch。
- 已进房无 Agent：检查指定 agent name、工作进程注册与 dispatch 配置。
- Agent 已加入无识别：检查 SIP 上行音频、ASR。
- 没有真实手机时，可做服务器夹具测试，但它不能验证蜂窝音频。

夹具文件找不到时：

```bash
sudo asterisk -rx 'core show settings'
ls -l /usr/share/asterisk/sounds/custom/persona-sip-test.wav
```

当前发行版 Data directory 是 `/usr/share/asterisk`；音频须为适合 Asterisk 的 8 kHz 单声道 PCM WAV。不要假设其他发行版目录也一样。

观察脚本输出零帧时还应确认观察任务是否报错、是否加入了正确的活跃测试房间。监控工具自身失败不能证明业务链路无声。

## 10. 变更与恢复的最小规则

1. 记录时间、故障现象、接口、房间或请求编号和当前版本。
2. 先执行只读检查，确认故障层；保留必要脱敏证据。
3. 确认无人正在进行电话或网页会话，再修改对应配置或重启单个受影响服务。
4. 修改前保留受保护的配置副本；不把含凭据的备份提交到 GitHub。
5. 修改后重复最小复现，再做完整往返测试。不要只看到服务 active 就宣布修好。

push `main` 会触发部署并重启 Web/Agent，可能影响通话。系统基础设施不随普通 push 自动重建；源码标签不是服务器配置和 Redis 的备份。不要把配置脚本当日常只读诊断命令。

## 11. 故障记录模板

```text
发生时间（含时区）：
版本 / 最近部署：
设备、SIM 槽位与网络（号码脱敏）：
现象、影响范围、复现步骤：
接口状态 / 请求编号 / 房间（脱敏）：
检查命令与关键结果：
已确认事实：
尚未确认的假设：
本次唯一或最小变更：
恢复验证（文字、音频、用户听感）：
遗留风险 / 下一步：
```

无法定位时优先收集这份记录，不直接公开 `.env`、完整抓包、通话录音或全部日志。
