# 两通测试复盘与低时延语音方案调研

调研日期：2026-11-05。关联Issue #4；当前代码1623870，LiveKit Agents 1.8.10。此次只测试、排查和调研，没有换模型、改线路或追加第三通电话。

## 1. 本轮验收结果：未达到自然对话目标

|项目|第1通|第2通|
|---|---|---|
|会话|84a028fd-15bc-4307-ba82-3c510d2e7bfb|946cd6cf-f2cb-4c2e-a50e-cdd53671c4c2|
|完整有效计时|4轮，另1轮中断|4轮，另1轮中断|
|平均等待|3.601秒|2.820秒|
|最大等待|4.469秒|3.208秒|
|提前提示/生成记录/取消|5 / 11 / 2|5 / 9 / 1|
|关闭记录|participant_disconnected|farewell_played，随后channel_closed|
|逐轮报告|[第1通](vad-gated-v2-1.md)|[第2通](vad-gated-v2-2.md)|

两通均未记录voice.error，但用户明确反馈延迟仍高、不会自动挂断，不能把无错误或有结束事件视为体验通过。每通不足5轮完整计时，不作显著性或P95/P99推断。所有计时终点为Agent输出，不是手机听筒。

10次候选均在最近一次VAD边界为listening之后发出，间隔3～111ms，说明停说门控生效。它减少了过早生成，但尚未证明稳定降低总等待。第一通真实FINAL最慢约3.255秒；第二通约0.651～2.016秒。两通模型启动到首音频约1.05～1.42秒（包括中断与未配对轮次的已知指标）。

## 2. 挂断必须分层验收

第1通没有ending/farewell_played事件；助手已出现收尾话语但没有进入结束工具。用户随后明确确认“第一通电话没有主动挂断”，该项已判定失败。最后participant_disconnected的直接触发方尚未核实。

第2通在04:58:40.995 UTC记录farewell_played，04:58:44.905 UTC记录Asterisk channel_closed，相差约3.9秒。用户已澄清没有主动挂断指第1通，不应将该反馈算成第2通故障；第2通手机端自动释放仍未独立采样。不能根据channel_closed反推网关SIM已自动结束。

代码检查：`services/agent/consultation_voice.py`的close_room先标记closed并刷新日志，再shutdown Agent、delete_room；删除失败仅写warning。`services/phone-console/managed_calls.py`有按call_id范围挂断Asterisk通道的接口，监控器以通道消失判定ended。现有Agent关闭路径没有直接等待手机SIM回报。

建议后续单独实现：结束意图确认 → 唯一结束语播完 → 对当前call_id发幂等挂断 → 记录SIP/Asterisk通道关闭 → 校验安卓通话空闲；超时只重试本次通话并提示失败。归档状态要区分“AI已结束”和“电话已挂断”。明确结束不能只依赖LLM自由文本；模糊话语可简短确认，不能把任意提到“结束”的句子当授权。

官方[LiveKit Job lifecycle](https://docs.livekit.io/agents/server/job.md)明确：关闭Agent会话不自动结束其他参与者；删除房间才断开所有房间参与者。我们已经调用delete_room，因此不能简单归因为忘了删房间，仍要查下游Asterisk→安卓→蜂窝释放及工具未触发这两类问题。

## 3. 社区与开源资料：哪些能用于当前项目

### A. Pipecat：先测最终转录等待，再调轮次策略

[STT Latency Tuning](https://docs.pipecat.ai/pipecat/fundamentals/stt-latency-tuning.md)将TTFS定义为停说至最终转录。文档强调供应商、区域、音频和参数都会改变它；超时太短会丢字，太长会导致尴尬停顿。仅调聚合器的等待阈值并不能让供应商更早产生最终文字。

配套开源工具：[pipecat-ai/stt-benchmark](https://github.com/pipecat-ai/stt-benchmark)，同时测TTFS分位数和语义WER。它适合替代频繁让用户接电话试参数：先用固定、有权使用的中文音频，在腾讯云同机实时节奏送入服务比较，再用真实SIM验收。公开榜单的语言、地域、硬件与我们不同，不能把其数百毫秒成绩当作本项目保证。

具体工程实践：[Pipecat PR #6537](https://github.com/pipecat-ai/pipecat/pull/6537)描述Soniox本地VAD finalize与供应商endpoint共同工作；[PR #6497](https://github.com/pipecat-ai/pipecat/pull/6497)描述VAD停说后主动commit获得正式转录。它们是其他供应商的协议能力，不是可以直接塞进千问的参数。

本机DashScope 2.0.3当前`Recognition`提供send_audio_frame、update_context、stop；stop发送finish_task并结束本次输入。没有在这个类发现可重复提交一句、继续同一识别任务的公开finalize/commit方法。recognize允许parameters透传，但不能据此臆造当前qwen-audio-3.1模型支持的静音参数。必须核对官方协议及账号模型权限，stop不能直接当作无损flush。

### B. Smart Turn：改善“说完了吗”，不替代快速ASR

[pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn)提供音频原生轮次判断，README列出中文在内23种语言、16kHz单声道PCM输入、CPU/GPU模型；在VAD检测静音后结合语调判断是否真的结束。它解决中途停顿与抢话问题，不能保证已经等了两秒的ASR马上返回FINAL。项目所列推理耗时不是完整电话应答耗时。

[Speech Input & Turn Detection](https://docs.pipecat.ai/pipecat/learn/speech-input.md)区分原始VAD静音和最终用户轮次。我们目前是VAD-only，后续可对比音频轮次模型，但不建议未经中文电话样本验证就把静音阈值压到极低。

Pipecat有官方[LiveKit Transport](https://docs.pipecat.ai/api-reference/server/services/transport/livekit.md)。因此可保留当前LiveKit Server/SIP/Asterisk/网页，平行建立Pipecat Agent实验路径，不需要先拆掉电话链路。不过若复用同一慢ASR，迁移框架本身不会自动消除等待。

### C. LiveKit：预生成必须真的被复用

[PR #6667](https://github.com/livekit/agents/pull/6667)处理最终转录只改变大小写、空格、标点时的候选复用；[Issue #7506](https://github.com/livekit/agents/issues/7506)专门讨论中文全角标点导致复用失败；[PR #7949](https://github.com/livekit/agents/pull/7949)处理继续说话后无效候选及时取消。

这些解释了为什么“开启预生成”不等于降低实际等待。但是本机1.8.10实际测试：`_transcripts_equivalent('你好我想了解维修费用','你好，我想了解维修费用。')`返回True，英文格式差异也返回True。不能把已修复的中文标点等价问题直接认作我们仍存在的根因。

当前SDK的audio_recognition FINAL分支另有原始文本变化判断，可能再次触发生成；需要通过同一speech_id关联“提示→生成→最终转录→采用/替换”复现整条路径。当前字符长度不同只能证明文本形式不一致，不能证明只有标点不同。不能盲目修改site-packages或反复升级来碰运气。

### D. Reddit：与当前症状接近，但数字仅是个人经验

已读取原帖和评论：[VAD issues – takes too much time to understand when the user has stopped talking](https://www.reddit.com/r/LocalLLaMA/comments/1smzsff/vad_issues_takes_too_much_time_to_understand_when/)。发帖者使用Pipecat、Silero、Sarvam，称识别停说要约1.5秒，LLM流式帮助了后段却未解决首个瓶颈。

评论讨论了STT分块大小、独立finalize、Smart Turn和提前流式TTS；也有人反馈自由对话里Smart Turn收益有限。部分评论把“感知更快”和完整轮次关闭混用，并给出未独立验证的数字。我们的取舍：借鉴分段测量和明确finalize能力，不直接复制阈值，也不在最终意图确认前执行工具或播放可能错误的回答。

### E. Stack Overflow：本轮检索未找到足够直接的已验证结论

通过Stack Exchange API检索livekit latency、voice agent latency、speech recognition endpointing。较相关的[Android SpeechRecognizer + LiveKit麦克风冲突问题](https://stackoverflow.com/questions/80002050/android-speechrecognizer-livekit-voice-app-mic-ownership-conflict-and-tts-sel)没有回答，且讨论的是双麦克风采集/回声，与当前ASR FINAL等待不同。其余结果多是较早的WebSocket、播放或注册问题。本报告不把它们包装成社区一致认可的优化方案。

## 4. 可选路线与推荐顺序

|路线|能改变什么|当前建议与限制|
|---|---|---|
|保留LiveKit，换成或调通真正低TTFS的中文实时ASR|直接压缩主要等待，保留DeepSeek/TTS与日志|优先。先确认千问当前模型的端点协议；若不可控，再同机对比有明确commit/finalize能力的中文服务|
|Pipecat + Smart Turn + LiveKit Transport|更成熟的轮次策略、STT适配与延迟观测|适合平行实验，不做无证据全量重写；同一供应商等待仍会存在|
|原生Realtime语音模型|把独立ASR→LLM→TTS串联换成音频输入输出模型|可以做第二条实验线。需要确认中文、国内访问、账号权限、音色、工具调用和转录可靠性；原DeepSeek不再承担同样的主对话角色|
|自托管中文ASR|减少外部服务网络依赖并控制切段|可评估[FunAudioLLM/Fun-ASR](https://github.com/FunAudioLLM/Fun-ASR)及其流式部署；需测现有CPU/GPU与尾延迟，不能承诺现有腾讯云机器免费达到低延迟|

[LiveKit Turns文档](https://docs.livekit.io/agents/logic/turns.md)支持传统流水线和Realtime模型两类轮次控制。使用Realtime仍需结束状态机、工具授权、转录归档和网络测量，不会自动修好挂断。

推荐下一轮先做：

1. 修复并验收电话结束闭环；与时延实验分开，避免“对话结束”伪装为“电话已释放”。
2. 采用stt-benchmark的测量方式，在腾讯云用相同中文样本对比当前千问与可用实时ASR。至少覆盖短句、长句、停顿继续、结束语与8k电话带宽；同时看准确性，不只看平均速度。
3. 补候选采用/替换的可关联证据。如果只是格式改变导致实际重做，做最小兼容修复；若是内容频繁变化或最终结果太晚，停止继续堆叠预生成参数。
4. 只有上述结果仍无法满足体验，再对比Pipecat或原生Realtime。新服务权限、费用和硬件采购需先明确，不在本次调研中擅自购买或启用。

此处是方案，不是已完成的改造；本轮保持现有线上配置，未宣称vad-gated-v2验收通过。

## 5. 本次产物及后续可能涉及文件

本次只新增两通Markdown、两份脱敏timings.json和本调研文档，均在docs/performance/；生产代码未改。

后续ASR适配/观测涉及services/agent/qwen_streaming_stt.py、preflight.py、agent.py、consultation_voice.py及对应tests；挂断闭环涉及consultation_voice.py、services/phone-console/managed_calls.py、Web端状态/归档处理及网关状态接口。实际实施时再列出精确改动文件与提交，不将计划文件当成已经修改。
