"""Real production adapter + LiveKit Agent SDK + Qwen + OpenViking, no telephone.

Text triggers a real tool call and real audio output to a paced discard sink.
This is integration verification, not an ASR/interruptions/handset latency test.
"""
import asyncio
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv
from livekit.agents import AgentSession

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
sys.path.insert(0,str(ROOT/'services/agent'))
from qwen_realtime import QwenRealtime
from realtime_voice import RealtimeAssistant
from procurement_knowledge import ProcurementKnowledge

spec=importlib.util.spec_from_file_location('sink',ROOT/'scripts/probe-qwen-agent-session.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--question',default='请查资料，Phoenix 2100 滚筒筛的筛筒长度和直径是多少？请说明资料版本。')
    parser.add_argument('--expect',action='append',help='Literal expected answer value; repeat for multiple values')
    parser.add_argument('--turn',action='append',default=[],help='Earlier user turn, replayed sequentially before the final question')
    parser.add_argument('--instructions-file',help='Use the actual business instructions exported by the web template')
    args=parser.parse_args()
    events=[];messages=[];errors=[]
    def audit(kind,payload):events.append({'kind':kind,'payload':payload})
    knowledge=ProcurementKnowledge(audit)
    model=QwenRealtime(audit=audit)
    session=AgentSession(llm=model)
    sink=fixture.Sink();session.output.audio=sink
    @session.on('conversation_item_added')
    def message(event):
        if getattr(event.item,'role',None) in ('assistant','user'):
            messages.append({'role':event.item.role,'text':event.item.text_content})
    @session.on('error')
    def error(event):errors.append(type(event.error).__name__)
    try:
        instructions=Path(args.instructions_file).read_text(encoding='utf-8') if args.instructions_file else '你是采购演示助手。按知识工具规则理解型号；信息不足时可以简短澄清，有充分线索后先查工具再回答，不做开场。'
        await session.start(agent=RealtimeAssistant(instructions,knowledge))
        for user_turn in [*args.turn,args.question]:
            handle=session.generate_reply(user_input=user_turn)
            await asyncio.wait_for(handle.wait_for_playout(),55)
            await asyncio.sleep(.3)
        for _ in range(30):
            if any(m['role']=='assistant' and m['text'] for m in messages) and sink.frames:break
            await asyncio.sleep(.2)
    finally:
        await session.aclose();await model.aclose()
    hits=[e for e in events if e['kind']=='knowledge.completed' and e['payload']['status']=='ok']
    answer=next((m['text'] or '' for m in reversed(messages) if m['role']=='assistant'),'')
    dimensions=any(x in answer for x in ('6.45','六点四五')) and any(x in answer for x in ('1.94','一点九四'))
    if args.expect:
        dimensions=all(value in answer for value in args.expect)
    report={'real_qwen':True,'real_openviking':True,'production_adapter':True,'phone_call':False,
            'input_mode':'text_tool_integration','audio_sink':'paced_discard_not_speaker',
            'question':args.question,'expected_values':args.expect,'messages':messages,'audio_frames':sink.frames,'events':events,'errors':errors,
            'expected_dimensions_confirmed':dimensions,'ok':bool(hits and dimensions and sink.frames and not errors)}
    out=ROOT/'BigApple输出/采购知识库接入';out.mkdir(parents=True,exist_ok=True)
    target=out/f'qwen-openviking-{time.time_ns()}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False,indent=2));print(target)
    if not report['ok']:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
