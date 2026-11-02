import { timingSafeEqual } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { toWav } from '../../../lib/qwen-asr';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const attempts = new Map<string, number>();

export async function POST(request: NextRequest) {
  const expected = process.env.VOICE_ACCESS_CODE;
  const key = process.env.DASHSCOPE_API_KEY;
  const url = process.env.QWEN_ASR_URL;
  if (!expected || !key || !url) return NextResponse.json({ error: '服务器千问语音识别配置不完整' }, { status: 503 });
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
    const wav = await toWav(Buffer.from(await file.arrayBuffer()));
    const response = await fetch(url, {
      method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', 'X-DashScope-SSE': 'disable' },
      body: JSON.stringify({
        model: process.env.QWEN_ASR_MODEL || 'qwen-audio-3.1-asr-flash',
        input: { messages: [{ role: 'user', content: [{ type: 'input_audio', input_audio: { data: `data:audio/wav;base64,${wav.toString('base64')}` } }] }] },
        parameters: { format: 'wav', sample_rate: '16000' },
      }),
      signal: AbortSignal.timeout(45_000),
    });
    if (!response.ok) {
      console.error('transcribe provider failure', response.status);
      return NextResponse.json({ error: `千问语音识别请求失败（${response.status}），请检查服务权限、额度或稍后重试。` }, { status: 502 });
    }
    const result = await response.json();
    const rawText = result.text ?? result.output?.text ?? result.output?.sentence?.text;
    const text = typeof rawText === 'string' ? rawText.trim() : '';
    console.info('qwen_asr_result', { requestId: result.request_id, bytes: file.size, wavBytes: wav.length, textLength: text.length });
    if (!/[\p{L}\p{N}]/u.test(text)) return NextResponse.json({ error: '录音未识别出有效文字，请重新说一句完整的话。' }, { status: 422 });
    return NextResponse.json({ text }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('transcribe request failure', error instanceof Error ? error.name : 'unknown');
    return NextResponse.json({ error: '录音解析失败或识别服务连接超时，请重试。' }, { status: 502 });
  }
}
