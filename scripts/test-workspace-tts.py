"""Private subprocess: JSON credential on stdin; WAV on stdout; no secret logging."""
import io
import json
import sys
import wave
import dashscope

def main():
    config=json.loads(sys.stdin.read(4096))
    client=dashscope.Client(api_key=config['key'],workspace=config['workspace'],region='cn-beijing',timeout=25)
    try:
        with client.audio.tts.connect(model='qwen-audio-3.1-tts-flash',voice='longanhuan_v3.1',format='pcm',sample_rate=24000,timeout=25) as session:
            session.send_text('你好，这是咨询工作台的语音测试。如果你能听到这句话，说明文字转语音已返回音频。')
            session.stop()
            pcm=b''.join(session.audio_chunks())
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm)
        sys.stdout.buffer.write(output.getvalue())
    finally:
        client.close()

if __name__=='__main__':
    try:main()
    except Exception:sys.exit(1)
