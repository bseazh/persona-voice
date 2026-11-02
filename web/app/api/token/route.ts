import { randomUUID, timingSafeEqual } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { AccessToken, RoomConfiguration, type VideoGrant } from 'livekit-server-sdk';

export const dynamic = 'force-dynamic';

const attempts = new Map<string, { count: number; resetAt: number }>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const current = attempts.get(ip);
  if (!current || current.resetAt <= now) {
    attempts.set(ip, { count: 1, resetAt: now + 60_000 });
    return false;
  }
  current.count += 1;
  return current.count > 10;
}

function matchesAccessCode(received: unknown, expected: string): boolean {
  if (typeof received !== 'string') return false;
  const left = Buffer.from(received.trim());
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function GET() {
  return NextResponse.json({ status: 'ok', service: 'persona-voice-token' });
}

export async function POST(request: NextRequest) {
  const livekitUrl = process.env.LIVEKIT_URL;
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const agentName = process.env.LIVEKIT_AGENT_NAME || 'persona-voice-agent';
  const expectedAccessCode = process.env.VOICE_ACCESS_CODE;

  if (!livekitUrl || !apiKey || !apiSecret) {
    return NextResponse.json({ error: 'LiveKit 服务端配置不完整' }, { status: 503 });
  }
  if (process.env.NODE_ENV === 'production' && !expectedAccessCode) {
    return NextResponse.json({ error: '服务尚未设置体验访问码' }, { status: 503 });
  }

  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
  if (rateLimited(ip)) return NextResponse.json({ error: '请求过于频繁，请一分钟后重试' }, { status: 429 });

  let body: { accessCode?: string } = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: '请求格式无效' }, { status: 400 });
  }
  if (expectedAccessCode && !matchesAccessCode(body.accessCode, expectedAccessCode)) {
    return NextResponse.json({ error: '体验访问码不正确' }, { status: 401 });
  }

  const suffix = randomUUID();
  const roomName = `persona-${suffix}`;
  const token = new AccessToken(apiKey, apiSecret, { identity: `web-${suffix}`, name: '访客', ttl: '15m' });
  const grant: VideoGrant = { room: roomName, roomJoin: true, canPublish: true, canPublishData: true, canSubscribe: true };
  token.addGrant(grant);
  token.roomConfig = RoomConfiguration.fromJson({ agents: [{ agentName }] });

  return NextResponse.json({ serverUrl: livekitUrl, roomName, participantName: '访客', participantToken: await token.toJwt() }, { headers: { 'Cache-Control': 'no-store' } });
}
