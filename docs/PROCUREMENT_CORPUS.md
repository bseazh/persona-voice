# 采购演示资料扩充与细节提问

日期：2026-11-06。范围：公开的垃圾分选相关滚筒筛与破碎机资料；不是采购方已选型，也不是当前供应商能力证明。

## 资料规模

6 个不同型号、6 份厂商原版 PDF、合计 24 个 PDF 页面（部分页面是双页跨页排版）。新增 4 份，复用此前已核验的 2 份，不把中文摘要或重复版本算成新型号。

| 型号 | 类别 | 版本 | PDF 页数 | 参数所在 PDF 页 |
|---|---|---|---:|---:|
| Phoenix 1600 | 滚筒筛 | 2018 年 6 月 | 3 | 2 |
| Phoenix 2100 | 滚筒筛 | 2017 年 12 月 | 3 | 2 |
| Phoenix 3300 | 滚筒筛 | 2017 年 12 月 | 3 | 2 |
| TSS 390 | 单轴破碎机 | 厂商文件名 2026 | 5 | 4 |
| TDS 820 | 双轴低速破碎机 | 2026 年 6 月 | 5 | 4 |
| TDS 825 | 双轴高扭矩破碎机 | 2026 年 6 月 | 5 | 4 |

全部来自 Terex Ecotec 官方网站，因此已扩展同品牌多型号覆盖，但尚未实现跨厂商对比。不涉及模型训练，“单一产品过拟合”在此更准确地说是检索与验收覆盖不足。旧版手册只能作为历史公开参数，正式采购需供应商确认。

## 可直接提问

| 提问 | 手册参考答案 / 验收要求 |
|---|---|
| Phoenix 1600 的筛筒长和直径多少？ | 4.9 m / 1.54 m |
| 换成 Phoenix 2100 呢？ | 6.45 m / 1.94 m；需要正确承接型号变化 |
| Phoenix 3300 与 1600 的筛筒尺寸有什么不同？ | 3300 为 9.31 m / 2.32 m；不能套用 1600 |
| TSS 390 是单轴还是双轴，轴长和动力多少？ | 单轴、3000 mm、368 kW 发动机，不是电机 |
| TDS 820 所有版本都是 331 kW 吗？ | 不是；EU/USA 配置 331 kW，ROW 对应配置 371 kW |
| TDS 825 轴长、轴径和每轴扭矩多少？ | 2500 mm、900 mm、165000 Nm |
| TDS 820 与 825 每轴扭矩差多少？ | 100000 对 165000 Nm，差 65000 Nm |
| 这些设备给我们的报价、交期和保证产能是多少？ | 手册没有本项目承诺，明确未知并向供应商追问 |

对照表不是预设模型回答；线上应实时检索证据。连续追问、未知问题和多型号比较仍需真实通话验收。

## 来源与复现

厂商原文 URL、下载时间与 SHA-256 在交付 ZIP 的 `sources.json`；中文参数摘要带版本和原文页码：

- `knowledge/procurement-demo/01-phoenix2100.md`
- `knowledge/procurement-demo/02-tss390.md`
- `knowledge/procurement-expansion/04-phoenix1600.md`
- `knowledge/procurement-expansion/05-phoenix3300.md`
- `knowledge/procurement-expansion/06-tds820.md`
- `knowledge/procurement-expansion/07-tds825.md`

脚本：`scripts/expand-procurement-corpus.py` 从官方产品页发现对应 PDF；`scripts/package-procurement-corpus.py` 校验哈希并打包；`scripts/validate-procurement-corpus.py` 通过生产检索适配器验证六个型号，不读取本地答案伪装检索。

## 云端接入

使用现有只读范围 `viking://resources/persona_voice_procurement_demo`，不改模型凭据与电话链路。新增中文摘要目录 `procurement-expansion`；原版 PDF 目录 `official_pdf_v1`。摘要用于快速取参数，完整 PDF 用于检索更多细节，两者不是不同产品或独立证据。

- 四份中文摘要任务：`cca797c5-aa3b-4c8b-a200-4ad47836f0c2`。
- 六份原版 PDF 任务：`7a561904-a396-4fd2-a01c-4a7b6e435872`。

公网工作台选择“采购供应商沟通”与“Qwen 原生全双工”。知识库更新在现有检索范围内生效，不需要重新启动语音服务。文字咨询和 ASR→DeepSeek→TTS 路线尚未接此知识工具。

## 验证边界

初次生产适配器检索 6/6 通过：对应型号正文同时包含预期的两项或三项参数，检索耗时 267–566 ms。此数值不含 ASR、模型思考、音频生成、电话网络；不是通话时延或稳定性统计。

完整 PDF 入库后复测 6/6 通过，六次耗时依次为 308、352、300、294、288、348 ms。原始复测证据保存在项目 `BigApple输出/采购知识库扩充/retrieval-validation.json`。两次都是有限样本，不是性能基准。

新增型号真实 Qwen 联调通过：使用生产 Agent SDK 和知识工具，文字询问 TDS 825 轴长与发动机功率，模型实际检索 OpenViking 后回答“2026 年 6 月版、2500 mm、566 kW（Scania DC16）”，输出 33 个音频帧、错误事件为零。证据：`BigApple输出/采购知识库接入/qwen-openviking-1793933736261812000.json`。音频输出到按时播放的丢弃端，不是扬声器听感或电话验收。

完整 PDF 导入任务 completed，6 个文件处理成功、0 失败；四份摘要任务同样 completed。没有在本轮拨打电话，未验证连续多轮语音、插话和挂断。
