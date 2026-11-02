import { timingSafeEqual } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const attempts = new Map<string, number>();

export async function POST(request: NextRequest) {
  const expected = process.env.VOICE_ACCESS_CODE;
  const key = process.env.ELEVENLABS_API_KEY;
  if (!expected || !key) return NextResponse.json({ error: '服务器语音识别配置不完整' }, { status: 503 });
  const supplied = request.headers.get('x-voice-access-code')?.trim() || '';
  const left = Buffer.from(supplied);
  const right = Buffer.from(expected);
  if (left.length !== right.length || !timingSafeEqual(left, right)) {
    return NextResponse.json({ error: '语音输入身份验证失败，请结束对话后重新输入访问码进入。' }, { status: 401 });
  }
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0] || 'unknown';
  const now = Date.now();
  for (const [address, time] of attempts) if (now - time > 60_000) attempts.delete(address);
  if (now - (attempts.get(ip) || 0) < 3000) return NextResponse.json({ error: '请稍等三秒再识别。' }, { status: 429 });
  attempts.set(ip, now);
  if (Number(request.headers.get('content-length')) > 6 * 1024 * 1024) {
    return NextResponse.json({ error: '录音过大，请控制在一分钟内。' }, { status: 413 });
  }
  try {
    const data = await request.formData();
    const file = data.get('audio');
    if (!(file instanceof File) || !file.size || file.size > 5 * 1024 * 1024) {
      return NextResponse.json({ error: '录音为空或超过 5MB，请重新录制。' }, { status: 400 });
    }
    const form = new FormData();
    form.set('file', file);
    form.set('model_id', 'scribe_v2');
    form.set('language_code', 'zho');
    form.set('tag_audio_events', 'false');
    const response = await fetch('https://api.elevenlabs.io/v1/speech-to-text', {
      method: 'POST', headers: { 'xi-api-key': key }, body: form,
      signal: AbortSignal.timeout(45_000),
    });
    if (!response.ok) {
      console.error('transcribe provider failure', response.status);
      return NextResponse.json({ error: `语音识别供应商请求失败（${response.status}）。${response.status === 401 ? '请检查服务器供应商密钥。' : '请稍后重试。'}` }, { status: 502 });
    }
    const result = await response.json();
    const text = typeof result.text === 'string' ? result.text.trim() : '';
    if (!/[\p{L}\p{N}]/u.test(text)) return NextResponse.json({ error: '录音未识别出有效文字，请重新说一句完整的话。' }, { status: 422 });
    return NextResponse.json({ text }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('transcribe request failure', error instanceof Error ? error.name : 'unknown');
    return NextResponse.json({ error: '录音解析失败或识别服务连接超时，请重试。' }, { status: 502 });
  }
}
