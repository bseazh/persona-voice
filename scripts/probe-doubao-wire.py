"""Real provider event-shape probe. Secret via stdin; synthetic input only."""
import asyncio
import base64
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from doubao_realtime import Connection, GREETING

async def main():
    credential=json.load(sys.stdin)
    conn=Connection(credential['key'])
    try:
        await conn.connect('你是中文语音助手，直接简短回答。')
        await conn.send('speech_text_buffer.commit',text=GREETING)
        async with asyncio.timeout(12):
            while True:
                e=await conn.recv()
                safe={k:v for k,v in e.items() if k in ('type','response_id','question_id','tts_type','status_code','speech_id')}
                safe['fields']=list(e)
                if e.get('type')=='response.output_audio.delta':safe['audio_bytes']=len(base64.b64decode(e['delta']))
                print(json.dumps(safe,ensure_ascii=False),flush=True)
                if e.get('type')=='response.output_audio.done':break
    finally:await conn.close()

asyncio.run(main())
