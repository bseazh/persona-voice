"""Protected subprocess probe: stdin secret, bounded JSON/audio stdout, no secret logs."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/agent'))
from doubao_realtime import synthesize_control, VOICE

async def main():
    data=json.load(sys.stdin)
    try:
        _, frames, logid=await synthesize_control(data['key'], '你好，这是豆包实时语音连接测试。', data.get('voice',VOICE))
        pcm=b''.join(bytes(f.data) for f in frames)
        if not any(pcm): raise ValueError('silent_audio')
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm)
        print(json.dumps({'ok':True,'audio':base64.b64encode(output.getvalue()).decode(),
                         'logid':logid,'scope':'session_and_prescribed_audio_not_asr_or_phone'}))
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__}))
        sys.exit(1)

asyncio.run(main())
