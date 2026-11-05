"""Build the versioned benchmark workbook and five reports from sanitized evidence.

Only writes docs/performance artifacts; never reads .env or private transcripts.
Rebuilding replaces the workbook: transfer manually entered evidence to the versioned
data/reports before running again.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/performance'
data = json.loads((OUT / 'measurements.json').read_text(encoding='utf-8'))
stages = [
    ('01-baseline', '01 基线', '当前链路实际耗时是多少？', '只增加统一计时，不改变语音策略。换卡后重测两通。', '现有两次拨号均未接通，有效轮数为零；新线路基线尚未测得。', '记录收尾、模型首字、切句、首音频、服务端输出总等待；同时记录人工听感。'),
    ('02-asr', '02 识别收尾', '说完后为何还在等待？', '依据最终识别与轮次确认时间调整 ASR 收尾和停顿参数，每次只改一项。', '尚未优化；此前单通历史日志仅提示收尾可能是主要等待，不能代替本轮基线。', '前：01 基线两通；后：本阶段两通。防止句中停顿被当成结束，记录漏识别与抢话。'),
    ('03-tts', '03 TTS流式', '首句与句间播放为何等待？', '在一个回复内持续提交文字并接收音频，检查连接复用与取消清理。', '尚未优化；目前是按句提交、音频分块返回。', '前：02 阶段两通；后：本阶段两通。比较首音频和切句等待，记录卡顿及打断残留。'),
    ('04-preemptive', '04 提前生成', '能否把模型等待与收尾重叠？', '试验提前生成；确认轮次再播放，继续说话则撤销旧回复，副作用操作不能提前执行。', '尚未优化；咨询模式当前关闭提前生成。', '前：03 阶段两通；后：本阶段两通。重叠阶段不能简单相加；记录错误回答与额外请求成本。'),
    ('05-concise', '05 简短发言', '如何减少长独白而保留咨询质量？', '使用简短回应加一个问题，保留必要说明、风险提示和结束语。', '尚未优化；不能把减少说话时长直接算成首响应提速。', '前：04 阶段两通；后：本阶段两通。除响应耗时外，比较发言时长、信息覆盖与人工自然度。'),
]
wb = Workbook(); guide = wb.active; guide.title = '00 使用说明'
guide.append(['项目', '说明'])
for row in [
    ('当前状态', '两次旧线路拨号未接通。新线路基线及四项优化均待测，所有空白不是零耗时。'),
    ('填写图例', '浅黄色蓝字为输入；公式为黑字。每通至少5轮；基线2通、每项优化后2通，共10通有效电话。'),
    ('对照规则', '每阶段“优化前”引用上一阶段两通，不重复拨打；baseline前值不适用。换卡后重新建立基线。'),
    ('真实来源', '历史记录来自 measurements.json；新数据填写会话ID与逐轮数值，关联服务端日志。勿填密钥、原始转录或完整手机号。'),
    ('总响应终点', '用户停止说话至 Agent 输出音频，不包含到接听手机的真实传输/播放耗时。'),
    ('阶段占比', '仅当同一轮边界齐全且无重叠时计算。提前生成重叠、负残差、缺值则不计算占比。'),
    ('ASR注意', 'transcription_delay 与 end_of_turn_delay 重叠，不能同时相加；切句=首段时间减首字时间。'),
    ('有效样本', '未接通不是有效测试；开场、工具结束语、中断分别标注，不混入正常轮次比较。'),
    ('统计边界', '两通只是验收小样本，不承诺P95、因果结论或长期稳定性。'),
    ('更新流程', '每轮补逐轮记录、阶段sheet与Markdown结论，校验公式后将工作簿和脱敏证据一起commit/push。'),
    ('再生成警告', 'build-latency-workbook.py 会重建模板；人工修改后先归档证据，不可直接重跑覆盖。'),
    ('示例隔离', '99示例为计算示范，完全虚构，不参与任何实际结果统计。'),
]: guide.append(row)

for index, (slug, title, question, strategy, status, acceptance) in enumerate(stages):
    ws=wb.create_sheet(title)
    ws.append(['阶段', title]); ws.append(['问题', question]); ws.append(['策略', strategy]); ws.append(['状态', status])
    ws.append(['前后','测试','会话ID','有效轮数','平均总等待(s)','中位数(s)','最大(s)','收尾均值(s)','模型首字(s)','切句等待(s)','TTS首音频(s)','其他调度(s)','解释/听感/来源'])
    for r,(phase,repeat) in enumerate([('优化前',1),('优化前',2),('优化后',1),('优化后',2)],6):
        ws.append([phase,repeat,None,None,None,None,None,None,None,None,None,None,'不适用：基线无前值' if index==0 and r<8 else '待有效测试；不得填写为0'])
        for c in range(3,13):
            ws.cell(r,c).fill=PatternFill('solid',fgColor='FFF2CC')
            ws.cell(r,c).comment=Comment('人工输入真实测量；单位秒；会话ID必须可追溯。缺测留空。','Source')
    ws['A11']='汇总（两通均有有效轮次和均值才计算）'
    ws['A12']='优化前两通均值'; ws['E12']='=IF(AND(COUNT(E6:E7)=2,COUNTIF(D6:D7,">0")=2),AVERAGE(E6:E7),"")'
    ws['A13']='优化后两通均值'; ws['E13']='=IF(AND(COUNT(E8:E9)=2,COUNTIF(D8:D9,">0")=2),AVERAGE(E8:E9),"")'
    ws['A14']='减少秒数（前-后）'; ws['E14']='=IF(COUNT(E12:E13)=2,E12-E13,"")'
    ws['A15']='相对减少比例'; ws['E15']='=IF(AND(COUNT(E12:E13)=2,E12>0),(E12-E13)/E12,"")'; ws['E15'].number_format='0.0%'
    ws['A17']='验收'; ws['B17']=acceptance
    ws['A18']='结论'; ws['B18']='待测。无优化收益数值；是否保留或回滚须等两通结果。'
    ws['A19']='统计口径'; ws['B19']='这里比较两通均值的等权平均；逐轮中位数及最大值分别记录，不能平均后当作总体中位数。'
    ws.freeze_panes='E6'
    report=f'''# {title}：{question}

## 当前结论

{status}

## 优化前

{'换卡后的新基线待测；旧线路失败拨号单独归档。' if index==0 else '使用上一阶段两通有效电话作为对照，当前尚无有效对照数据。'}

## 计划变更与原因

{strategy}

## 优化后与两次测试

|测试|会话ID|有效轮数|分段耗时/占比|结论|
|---|---|---|---|---|
|第1通|待测|—|N/A|无有效结果|
|第2通|待测|—|N/A|无有效结果|

{acceptance}

## 本轮解答与决策

目前不能判断收益，不填“已优化成功”。每次测试后补充：改变了什么、为什么、各段前后耗时、占比、异常原因、人工反馈、保留或回滚结论及代码版本。两通未完成不进入下一项优化。

工作簿：[latency-benchmark.xlsx](latency-benchmark.xlsx)，工作表“{title}”。脱敏证据：[measurements.json](measurements.json)。
'''
    (OUT/f'{slug}.md').write_text(report,encoding='utf-8')

history=wb.create_sheet('历史拨号记录')
history.append(['批次','次数','会话ID','拨号时间UTC秒','结束UTC秒','拨号等待(s)','状态','有效轮数','解释'])
for n,a in enumerate(data['attempts'],2):
    history.append([a['batch'],a['repeat'],a['session_id'],a['dialing_at'],a['ended_at'],f'=E{n}-D{n}',a['status'],a['valid_turns'],'旧线路未接通；不是ASR/LLM/TTS耗时'])
    history.cell(n,4).comment=Comment('Source: measurements.json / phone.state dialing payload.at (Unix UTC seconds)','Source')
    history.cell(n,5).comment=Comment('Source: measurements.json / phone.state ended payload.at (Unix UTC seconds)','Source')

def detail_sheet(name, example=False):
    ws=wb.create_sheet(name)
    ws.append(['会话ID','阶段','前后','通次','轮次','总等待(s)','收尾(s)','首字(s)','首段(s)','合成首音频(s)','切句(s)','其他(s)','收尾占比','首字占比','切句占比','合成占比','其他占比','边界无重叠确认','异常/说明'])
    for r in range(2,3 if example else 102):
        if example:
            ws.append(['DEMO-NOT-REAL','示例','优化前',1,1,3.0,1.4,.5,.9,.6,None,None,None,None,None,None,None,'是','虚构算例：不计入真实测试'])
        ws.cell(r,11,f'=IF(COUNT(H{r}:I{r})=2,I{r}-H{r},"")')
        ws.cell(r,12,f'=IF(AND(COUNT(F{r}:J{r})=5,R{r}="是"),F{r}-G{r}-I{r}-J{r},"")')
        for col,source in [(13,'G'),(14,'H'),(15,'K'),(16,'J'),(17,'L')]:
            ws.cell(r,col,f'=IF(AND(COUNT(F{r}:L{r})=7,F{r}>0,MIN(F{r}:L{r})>=0,R{r}="是"),{source}{r}/F{r},"")')
            ws.cell(r,col).number_format='0.0%'
        for col in list(range(1,11))+[18,19]: ws.cell(r,col).fill=PatternFill('solid',fgColor='FFF2CC')
    validation=DataValidation(type='list',formula1='"是,否,未确认"');ws.add_data_validation(validation);validation.add('R2:R101')
    ws.freeze_panes='F2';ws.auto_filter.ref=ws.dimensions
    return ws
detail_sheet('逐轮计时输入');detail_sheet('99 示例非实测',True)

for ws in wb:
    ws.sheet_view.showGridLines=False
    for row in ws:
        for cell in row:
            is_formula=cell.data_type=='f'
            cell.font=Font(name='Arial',size=11,color='000000' if is_formula else ('1761A0' if cell.fill.fgColor.rgb=='00FFF2CC' else '20334D'))
            cell.alignment=Alignment(vertical='top',wrap_text=True)
            if isinstance(cell.value,(int,float)) or is_formula:
                if cell.number_format=='General': cell.number_format='0.000'
    for cell in ws[1]:cell.fill=PatternFill('solid',fgColor='17365D');cell.font=Font(name='Arial',size=11,bold=True,color='FFFFFF')
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width=22
    ws.column_dimensions['A'].width=30
    ws.row_dimensions[1].height=32
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    if ws.title.startswith(('01','02','03','04','05')):
        ws.column_dimensions['B'].width=62;ws.column_dimensions['C'].width=42;ws.column_dimensions['M'].width=50
        for r in (2,3,4,17,18,19):ws.row_dimensions[r].height=64
        ws.print_area='A1:M19'
    if ws==guide:ws.column_dimensions['B'].width=110
    if ws==history:ws.column_dimensions['C'].width=42;ws.column_dimensions['I'].width=55
wb.save(OUT/'latency-benchmark.xlsx')
print(OUT/'latency-benchmark.xlsx')
