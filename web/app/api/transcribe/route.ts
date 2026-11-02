import { timingSafeEqual } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { toWav, wavMetrics } from '../../../lib/qwen-asr';

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
    const metrics = wavMetrics(wav);
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
      const failure = await response.json().catch(() => ({}));
      // Keep provider diagnostics, but never log the request audio or credentials.
      const safeIdentifier = (value: unknown) => typeof value === 'string' && /^[\w.:-]{1,160}$/.test(value) ? value : undefined;
      const code = safeIdentifier(failure.code);
      const reason = safeIdentifier(failure.message);
      const requestId = safeIdentifier(failure.request_id);
      console.error('qwen_asr_failure', { status: response.status, code, reason, requestId, bytes: file.size, wavBytes: wav.length, metrics });
      const reference = requestId ? `（请求编号：${requestId}）` : '';
      if (response.status === 400 && (reason === 'ASR_RESPONSE_HAVE_NO_WORDS' || code === 'ASR_RESPONSE_HAVE_NO_WORDS')) {
        const detail = metrics && metrics.peakDb < -55
          ? '服务器收到的录音接近静音，请试听录音并检查麦克风输入设备。'
          : '录音中有音频信号，但千问没有识别出文字。请试听录音，确认人声清晰；噪声也会产生音频信号。';
        return NextResponse.json({ error: `${detail}${reference}`, code: 'NO_SPEECH', requestId, metrics }, { status: 422 });
      }
      const error = response.status === 401 || response.status === 403
        ? '千问语音识别鉴权失败，请检查服务器 API Key 和服务权限。'
        : response.status === 429
          ? '千问语音识别请求受限，请稍后重试；管理员需检查服务限流或额度。'
          : response.status === 400
            ? '千问未接受本次识别请求，需要根据请求编号检查音频或服务参数。'
            : `千问语音识别服务暂时失败（${response.status}），请稍后重试。`;
      return NextResponse.json({ error: error + reference, code: code || 'ASR_UPSTREAM_ERROR', requestId }, { status: 502 });
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
