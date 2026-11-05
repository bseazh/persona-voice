# 停说后提前生成：vad-gated-v2 待真人验收版

Issue #4。参照上一轮会话 73ca29d6-65e9-40f1-a58e-dde289547873，不是本轮新通话ID。本次仅修改代码、自动测试和部署，未拨打电话、未产生优化后的电话时延数据。

## 为什么改

v1在说话期间中间文字稳定300ms就生成候选，容易在完整问题出现前耗尽预算。两通完整回复均值2.378 / 2.855秒，没有稳定收益；第二通真实FINAL等待1.157～2.489秒。新版把候选启动移到VAD检测停说之后，尝试将模型等待与剩余ASR收尾重叠。

## 本版行为

1. 使用AgentSession公开user_state_changed事件。在现有turn_detection=vad配置下，speaking/listening由VAD识别钩子更新；未观察到说话→停说周期时不触发候选。
2. 说话期间只缓存最新中间识别；停说后，文字至少6字符且稳定150ms才发PREFLIGHT。稳定时间从最近文字更新算起，已稳定的文字不在停说后重复等150ms。原Silero静音检测0.5秒保持不变。
3. 每个ASR句子最多1次中间识别候选。重新说话撤销尚未发送的计时任务，不重置候选预算；已启动的候选由SDK在中间文字变化时作废，播放仍受用户静音及正式轮次授权约束。没有调用全局interrupt去干扰正常打断逻辑。
4. FINAL仍完整使用供应商原文，不伪造最终结果；FINAL与流关闭清理候选。SDK max_retries=2、max_speech_duration=10秒保持不变，因此长句可能不提前生成。
5. 不提前TTS、不提前执行结束工具。TTS双工、模型/音色、正式停顿参数及已修复的单次结束语流程保持不变。

默认VOICE_PREFLIGHT=on启用新版；回退设置off，在无通话时重启Agent。开关不切回旧v1。

## 具体文件

|文件|作用|
|---|---|
|[services/agent/preflight.py](https://github.com/bseazh/persona-voice/blob/main/services/agent/preflight.py)|VAD门控、最新文字稳定窗口、每句1次预算、默认开启与回退|
|[services/agent/qwen_streaming_stt.py](https://github.com/bseazh/persona-voice/blob/main/services/agent/qwen_streaming_stt.py)|把说话状态传到活动识别流，流结束解除注册，新增asr_vad_boundary时间日志|
|[services/agent/agent.py](https://github.com/bseazh/persona-voice/blob/main/services/agent/agent.py)|用公开session事件连接VAD状态与ASR适配器，不修改LiveKit源码|
|[services/agent/consultation_voice.py](https://github.com/bseazh/persona-voice/blob/main/services/agent/consultation_voice.py)|记录preflight_mode=vad-gated-v2、150ms与1次预算|
|[scripts/export-latency-evidence.py](https://github.com/bseazh/persona-voice/blob/main/scripts/export-latency-evidence.py)|脱敏保留VAD边界、实验模式与计时|
|[tests/test_preflight.py](https://github.com/bseazh/persona-voice/blob/main/tests/test_preflight.py)|9项门控、稳定窗口、取消、预算、关闭与异常测试|
|[tests/test_qwen_preflight.py](https://github.com/bseazh/persona-voice/blob/main/tests/test_qwen_preflight.py)|2项SDK事件适配测试：候选不冒充FINAL、off回退，使用假供应商做单元测试，不作为真实电话结果|
|[scripts/comment-latency-result.py](https://github.com/bseazh/persona-voice/blob/main/scripts/comment-latency-result.py)|增加plan评论类型，明确区分未拨号的代码验证和实测结果|
|docs/performance/VAD_GATED_PREFLIGHT_V2.md|本方案、验证结果、局限与待验收项|

## 自动验证结果

本地共17项通过：门控9、ASR适配2、TTS双工2、结束语流程4。Python编译与diff空白检查通过；CI另执行门控测试、电话安全测试和部署检查。单元测试不使用真实API或拨号，不代表真实时延下降。

## 重要边界

- 这版不缩短千问实际FINAL等待，只尝试利用这段等待准备回复。
- LiveKit 1.8.10的FINAL分支以原始文本是否相同决定是否重新启动提前生成；最终识别改字或标点差异仍可能导致候选被替换。不得把提示数当采用数；若实际中间结果与最终结果不一致，收益可能仍然很小。
- 候选过早作废的成本仍可能存在；新增VAD边界用于核对提示是否发生在停说后。SDK转录延迟受PREFLIGHT时钟影响，继续以独立asr_final事件核对。
- 未测手机端听音、RTP丢包或抖动；不归因于线路、不承诺降低百分比。

## 下一次真人验收

接听方确认开始后用相同配置测两通，不自动拨号。保持13660199577拨出、19221659824接听；每通尽量5个完整问答，包含短问、长句、中途停顿继续说、打断及结束。

每通结束立即提交Issue评论及Markdown/脱敏JSON：停说→候选→真实FINAL→首字→首音频，提示/取消/未调度次数、语音错误、实际结束语重复情况及听感。并行段不强算100%占比。只有真实数据后才决定保留或回退。
