# OpenViking CLI 与 Qwen 采购语音接入

## 当前结果（2026-11-06）

- 使用火山官方 `ve 1.2.2` 的 `ve ov` 入口，自动安装官方 OpenViking CLI 0.5.1。无需 OpenClaw，也无需重复安装另一个 CLI。
- 活动配置：`persona-voice-procurement`，服务地址 `https://api.vikingdb.cn-beijing.volces.com/openviking`。配置验证与健康检查通过；服务端返回版本 v0.5.0.10。Key 存在本机 CLI 配置和项目/服务器忽略版本控制的 `.env`，不在本文与源码中。
- 只读检索范围：`viking://resources/persona_voice_procurement_demo`。已导入本仓库 `knowledge/procurement-demo/` 三份中文资料，带原始 URL、版本与 PDF 页码。未上传私人录音、采购转录或会话记忆。
- 入库任务 `c50b5b19-dfcc-4dc3-ad1d-e8462f9922a9` completed，3 个文件成功、0 个失败。供应商口述不会自动写进正式知识库。
- 采购表全空时使用明确标注的演示背景，型号、预算、处理量与供应商仍未知；只填部分字段时其余项保持空白，不补造事实。

## 使用

公网工作台选择“采购供应商沟通”与“Qwen 原生全双工”，项目表可留空。开场加载少量业务背景，具体型号问题由 `search_procurement_knowledge` 查询，模型收到资料后继续流式语音。普通追问不要求检索。

```text
项目表（可留空）+采购问法+少量背景
                  ↓
Qwen 实时理解/生成 ── 工具调用 ── 服务端适配器
                  ↑                   ↓
               证据片段 ← OpenViking /api/v1/search/find
                  ↓
         流式语音 + 保存转录
                  ↓
          结束后 DeepSeek 报告
```

本次只为采购 Qwen 路线注册知识工具。文字咨询和 ASR→DeepSeek→TTS 路线尚未接知识检索，不能声称所有路线都具备 RAG。原有报告和转录继续保存；检索事件与证据在管理员事件日志中查看，尚未新增单独的知识引用展示卡片。

## CLI 运维

```bash
ve ov config validate
ve ov health -o json
ve ov tree viking://resources/persona_voice_procurement_demo -o json
ve ov find 'Phoenix 2100 筛筒长度和直径' \
  --uri viking://resources/persona_voice_procurement_demo \
  --level 2 --read-content -n 3 -o json
```

CLI 用于配置、资料导入与检查；实时通话进程直接调用官方 HTTPS API，避免每次检索启动 CLI 子进程的额外成本。语义检索选用 `find`，当前不启用另一个模型进行多轮 `search` 规划。

环境变量：`OPENVIKING_API_KEY`、`OPENVIKING_PROCUREMENT_URI`；可选 `OPENVIKING_AGENT_ID`。接口凭据仅服务端使用。`scripts/sync-openviking-config.py` 从命名 CLI 配置写入本地 `.env`；`--emit` 只能直接通过 SSH 管道传到服务器的 `--receive`，不可保存进日志。另有 `scripts/configure-openviking.py --resource-id ov-...` 可通过已登录 `ve` 获取指定既有库凭据，本次因用户提供了库 Key 未使用该路径。

## 检索约束与审计

- 固定官方 HTTPS 主机，不从模型参数接受地址/Key/检索目录；禁止重定向。
- 只查演示资源目录，最多 3 条 L2 正文，每条最多 2200 字符，响应大小上限 256 KB，单次总超时 5 秒，每会话最多 20 次查询。
- 对没有正文、越界 URI 的命中不返回；不把生成摘要直接当成参数原文。
- 检索状态明确区分未配置、无证据、服务失败；不以本地固定答案冒充云端命中。
- `voice.knowledge.started/completed/cancelled` 记录查询、耗时、来源 URI、正文片段与内容哈希；无 Key、无模型隐藏思维。哈希对应完整命中正文，返回片段可能截短。
- 未设置未经校准的相关性阈值，仍可能返回不相关候选；由模型核对型号和证据。错型号、无答案、冲突及打断后的行为属于下一轮业务验收，尚不保证。

## 证据与测试

1. 原生 Qwen 协议验证：真实模型以 auto 模式发起工具调用，工具回传静态的已查阅公开资料后生成音频。仅此步骤不算真实 RAG。
2. CLI 云端检索：成功返回 Phoenix 2100 原文，包含 6.45 m 与 1.94 m 及来源/历史版本。
3. 生产适配器联调：`scripts/probe-qwen-openviking.py` 使用实际 LiveKit Agent SDK、RealtimeAssistant、QwenRealtime 与 ProcurementKnowledge；Qwen 自主调工具，实际请求 OpenViking 后回答“长度 6.45 米、直径 1.94 米”，说明手册印刷时间 2017 年 12 月；产生 59 个输出音频帧、错误事件为零。结果 `qwen-openviking-1793932315200113278.json`。

第 3 项使用文字触发工具和定时丢弃音频的测试输出端，不是麦克风 ASR、真人听感、网页房间或 SIM 通话测试。不会以它证明全双工插话、自然挂断或端到端时延。用户要求的长对话、缺资料、型号混淆、检索中打断与时延验收留到下一轮。

本地校验：3 项检索边界/未配置测试、11 项实时控制测试、采购模板字段测试、前端 lint/build 通过。PDF 文字提取和首页渲染检查通过。

## 演示资料

按采购录音主题选取公开厂家资料，不声称这些设备就是录音供应商产品，也不推荐它们直接用于本项目。

- Phoenix 2100：官网下载手册为 2017 年版本，保留历史版本标识。
- TSS 390：厂商 PDF 文件名标注 2026；368 kW 为发动机配置，不能误写成电机。
- Mixed Waste：混合废物处理概念、破碎与筛分边界。

中文入库内容与 `BigApple输出/采购知识库接入/采购演示知识资料.pdf` 一致；厂商原版 PDF 保存在该目录的 `演示资料/` 下。`scripts/render-procurement-knowledge.py` 可从已审阅 Markdown 重建中文 PDF。入库采用可追溯的中文 Markdown，原版 PDF 用于核验，不重复导入同一内容以免混淆版本。

官方接口依据：
- https://docs.volcengine.com/docs/84313/2374483 （find）
- https://docs.volcengine.com/docs/84313/2594206 （获取既有库 API Key）
- https://docs.volcengine.com/docs/vector-database-vikingdb/quick-access?lang=zh （快速接入）
