# Qwen 原生全双工路线

追踪：[Issue #6](https://github.com/bseazh/persona-voice/issues/6)。这是新增路线，旧的 ASR → DeepSeek → TTS 默认路线仍保留。

## 使用入口

登录 `https://phone.hehaizhao.site/consult`，新建网页语音咨询或进入拨号页面，在“语音路线”选择“新路线 · Qwen 原生全双工（试用）”。使用语音配置页面已经保存的千问 Key，无需把密钥放进浏览器脚本。每次会话创建后路线固定，重试相同拨号请求时不允许偷偷更换路线。

新路线的普通对话是 LiveKit 音频输入 → Qwen Realtime → LiveKit 音频输出；不使用独立 ASR、DeepSeek 或独立 TTS 生成普通回复。归档报告仍使用现有报告服务。音频输入与输出可同时传输，用户插话会取消当前回答。

原路线以原有 ASR/TTS 最近测试结果检查就绪；新路线只检查已保存的千问凭据，真实模型权限在连接时验证。页面不会把旧 ASR/TTS 测试结果当成原生 Realtime 已验收。供应商失败会记错误，不静默切换模型。

## 结束控制

可以明确说“请挂断电话”“今天就聊到这里吧”“再见”，或点击页面结束按钮。完整转录匹配明确结束短句，支持合并的多个结束短句；否定、引用、假设性的“再见”不会触发。模糊表达不保证自动结束，可使用按钮。

识别到明确结束后：停止输入和当前回答 → 使用 Qwen 原生实时接口生成一个短结束语 → 按实际返回文字记录转录并播放音频 → 请求释放当前会话对应的电话通道 → 删除当前 LiveKit 房间 → 记录释放确认和归档。

结束语使用独立、限时的 Realtime 请求，先收齐这句短音频及实际转录再播放，以隔离主连接取消竞态；它不是独立 TTS 服务。正常问答仍是流式的。失败时记录 `farewell_failed` 并继续关闭，不假装已经播完。

取消处理按 response_id / item_id 隔离。过期响应不能关闭新回答的音频流；没有开始的取消条目不再访问不存在的通道。供应商明确返回“没有活动响应”的取消竞态按幂等成功处理，其他供应商错误仍上报。

## 日志与限制

- `voice.benchmark_config` 标识 `route=qwen-realtime`；不虚构独立 ASR/LLM/TTS 的分段耗时。
- 双方文字及打断标记沿用原日志、转录和报告存储。
- `voice.ending`、`farewell_played` / `farewell_failed`、`phone_release`、`room_release`、`closed` 记录结束过程。
- `phone_release.requested` 只表示发出当前 call ID 的挂断请求；`channel_closed` 只表示服务端通道状态。没有手机端证据时，`handset_confirmed` 始终为 false。
- 当前模型可能在短暂停顿时拆分句子；500ms server VAD 不是语义完整性保证。长对话、噪声、弱网和真实 SIM 仍需分别验收。

## 开发验证

`tests/test_realtime_control.py` 不需要模型服务，覆盖取消与结束短句；`test_realtime_ending.py`、`test_qwen_realtime_bridge.py` 使用项目 Agent 依赖。

`scripts/probe-qwen-agent-session.py` 调用真实供应商，使用测试音频 sink，覆盖问答、边播放边输入、插话与自然结束，不拨号。

`scripts/probe-qwen-room.py --ending natural` 或 `--ending operator` 从公网工作台创建标记为自动验收的会话，通过真实 LiveKit 房间收发音频并验证转录、一次结束语及断开；同样不拨号。它从服务器 `.env` 读取管理密码，不输出凭据。

回退：下一次新建会话选择“原路线”。已有会话不热切换，防止两条路线同时响应。
