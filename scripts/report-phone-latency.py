"""Report measured turns without treating overlapping provider metrics as additive."""
import json
from pathlib import Path
import statistics
import sys

root = Path(__file__).resolve().parents[1]
directory = root / 'BigApple输出/latency-benchmark'
stage = sys.argv[1]
lines = [f'# 电话时延测试：{stage}', '', '单位：秒。终点为 Agent 输出，不代表接听手机实际听音；未测手机网络延迟。', '']
for repeat in (1, 2):
    file = directory / f'{stage}-{repeat}.json'
    lines += [f'## 第 {repeat} 通', '']
    if not file.exists():
        lines += ['尚未完成，不能计入有效样本。', '']; continue
    data = json.loads(file.read_text(encoding='utf-8'))
    session = data['session']
    lines += [f"会话：{data['id']}；结束原因：{session.get('reason')}；消息数：{len(session.get('messages', []))}。", '']
    timings = [e['payload'] for e in data['events'] if e['kind'] == 'voice.turn_timing']
    users = [t['metrics'] for t in timings if t['role'] == 'user']
    lines += ['|轮次|总等待|收尾/占比|首字/占比|首字后切句/占比|合成首音频/占比|其他调度/占比|中断|', '|---|---|---|---|---|---|---|---|']
    totals = []
    for n, turn in enumerate((t for t in timings if t['role'] == 'assistant'), 1):
        m = turn['metrics']; total = m.get('e2e_latency')
        if total is None:
            lines += [f'|{n}|N/A（开场或未测）|—|—|—|—|—|{turn["interrupted"]}|']; continue
        stop = m.get('started_speaking_at', 0) - total
        candidates = [u for u in users if abs(u.get('stopped_speaking_at', -999)-stop) < .1]
        u = candidates[-1] if candidates else {}
        eou, ttft, ttfs, tts = (u.get('end_of_turn_delay'), m.get('llm_node_ttft'), m.get('llm_node_ttfs'), m.get('tts_node_ttfb'))
        values = [eou, ttft, ttfs-ttft if ttfs is not None and ttft is not None else None, tts]
        residual = total-sum(values) if all(v is not None for v in values) else None
        valid = residual is not None and residual >= 0 and all(v >= 0 for v in values)
        def fmt(v):
            return 'N/A' if v is None else f'{v:.3f}' + (f' / {v/total*100:.1f}%' if valid and total > 0 else '')
        lines += ['|'+'|'.join([str(n),f'{total:.3f}',*(fmt(v) for v in values),fmt(residual) if valid else '重叠或缺测，不计算占比',str(turn['interrupted'])])+'|']
        if not turn['interrupted']: totals.append(total)
    lines += ['']
    if totals:
        lines += [f'非中断有效计时轮次 {len(totals)}；均值 {statistics.mean(totals):.3f}；中位数 {statistics.median(totals):.3f}；最大 {max(totals):.3f}。', '']
    else: lines += ['没有有效的完整回复计时样本；不能据此评价优化收益。', '']
    lines += ['人工听感：待接听方反馈。ASR 最终转录与轮次收尾重叠，原始数据单独保留，不重复相加。', '']
lines += ['## 比较限制', '', '每阶段至少两通有效电话才进入下一阶段。失败拨号单列；不补造数据。提前生成可能与收尾重叠，负残差不当成负耗时或强制计算百分比。原始事件保存在同目录 JSON 中。']
target = directory / f'{stage}-report.md'
target.write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(target)
