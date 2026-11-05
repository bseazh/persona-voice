# 本轮改动文件与下一阶段优化

GitHub Issue #4。实测会话：1e4d4047-d9ed-4bb6-88e4-ca9cf36452e0、73ca29d6-65e9-40f1-a58e-dde289547873。
实验代码 cd67eec；默认回退与重复结束语修复 74a7f6a。此次两通测试之后未追加第三通。

## 结果与定位

|指标|第1通|第2通|
|---|---|---|
|非中断回复|4轮|8轮|
|平均等待|2.378秒|2.855秒|
|最大等待|2.614秒|3.721秒|
|提前识别提示|8次|12次|
|模型生成记录 / 取消|14 / 7|21 / 10|
|未进入调度的speech handle|7个|12个|

第1通接听方反馈延迟明显、不自然；第2通反馈结尾感谢语重复。均无voice.error，但这不代表体验合格。

第2通停说至真实ASR FINAL约1.157～2.489秒；模型启动至首音频约0.935～1.607秒。当前主要可见等待仍在识别收尾，其后还有模型和TTS时间。ASR等待包含送达与服务端处理，现有数据不能拆开供应商计算、网络各占多少；手机端听音亦未独立测量。

本轮中间文字稳定300ms就启动候选，实际经常尚未说完，后续文字改变使候选作废。两通20次提示伴随较多废弃任务，没有稳定改善；默认关闭，不增加重试预算或用假FINAL掩盖问题。

## 涉及文件：已实现并提交

以下链接固定到74a7f6a，确保后续改动不覆盖本轮审计依据。

|文件|改动作用|
|---|---|
|[services/agent/preflight.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/services/agent/preflight.py)|稳定窗口、候选去重/预算、取消与关闭；测试后默认off|
|[services/agent/qwen_streaming_stt.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/services/agent/qwen_streaming_stt.py)|官方PREFLIGHT事件、真实FINAL审计；不修改正式识别文本|
|[services/agent/agent.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/services/agent/agent.py)|接入受限提前生成；关闭提前TTS，限制次数与说话时长|
|[services/agent/consultation_voice.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/services/agent/consultation_voice.py)|记录生成取消、speech调度、实验配置；修复同轮结束语重复与finish幂等|
|[tests/test_preflight.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/tests/test_preflight.py)|5项稳定候选生命周期测试|
|[tests/test_voice_consultation.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/tests/test_voice_consultation.py)|4项结束行为测试，含重复结束语和误复用保护|
|[scripts/report-phone-latency.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/scripts/report-phone-latency.py)|报告新增候选计数、真实FINAL时间核对；重叠不强算百分比|
|[scripts/export-latency-evidence.py](https://github.com/bseazh/persona-voice/blob/74a7f6a/scripts/export-latency-evidence.py)|脱敏导出数值、配置及调度证据，不发布全文对话或凭据|
|[.github/workflows/deploy.yml](https://github.com/bseazh/persona-voice/blob/74a7f6a/.github/workflows/deploy.yml)|CI增加候选生命周期测试|
|[docs/performance/04-preemptive.md](04-preemptive.md)|本阶段结果与回退决策|
|[docs/performance/FAREWELL_DUPLICATION.md](FAREWELL_DUPLICATION.md)|重复结束语根因、修复、边界与验收限制|
|[docs/performance/preflight-v1-1.md](preflight-v1-1.md)|第一通逐轮报告与人工反馈|
|[docs/performance/preflight-v1-1-timings.json](preflight-v1-1-timings.json)|第一通脱敏原始计时|
|[docs/performance/preflight-v1-2.md](preflight-v1-2.md)|第二通逐轮报告与真实FINAL核对|
|[docs/performance/preflight-v1-2-timings.json](preflight-v1-2-timings.json)|第二通脱敏原始计时|

本轮未修改千问TTS适配器、ASR供应商模型、VAD停顿参数、LiveKit源码或手机网关。现有TTS双工2项回归也通过。

## 下一阶段：待实现，不是已生效功能

1. **停说后才准备候选。** 通过VAD停说信号与最新中间识别协同：只有检测到停说、文字稳定才启动一次候选；继续讲话即撤销。保留真实FINAL确认后才播音/执行工具，不增加盲目请求次数。拟涉及 agent.py、preflight.py、qwen_streaming_stt.py 和 test_preflight.py；具体接线先验证SDK公开接口，避免依赖私有实现。
2. **先检查可用识别窗口。** 记录停说后中间文字何时完整、与FINAL是否一致、候选是否被采用。如果完整中间结果本就要等到FINAL附近，这条优化没有空间；届时核查千问官方端点设置或评估原生实时ASR。尚未验证模型支持的服务端静音参数，不编造配置。
3. **固定验收与副作用。** 同配置两通，尽量每通5个完整问答，包含长句、短暂停顿继续说、插话、结束。记录各轮停说→真实FINAL→模型首字→音频，并记录候选废弃和token统计。结束语修复需真人再验收；不以本次修复前通话宣称通过。
4. **TTS与线路分开验证。** 保留供应商/音色标签；后续需要时测TTS首音频连接成本，以及RTP丢包、抖动和手机端听音。现在没有证据说明换TTS或换线路即可解决主要等待。

每个后续版本仍采用“代码＋测试→部署→两通→每通Issue评论→Markdown与脱敏JSON入库”，失败和回退也保留；不会把平均数降低直接写成自然对话已达标。
