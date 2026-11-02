'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import {
  BarVisualizer,
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useLocalParticipant,
  useTranscriptions,
  useVoiceAssistant,
} from '@livekit/components-react';
import { Bot, Mic, PhoneOff, Radio, Sparkles } from 'lucide-react';
import { Track } from 'livekit-client';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

const stateLabels: Record<string, string> = {
  disconnected: '已断开',
  connecting: '正在连接',
  initializing: '助手正在上线',
  idle: '准备中',
  listening: '正在聆听',
  thinking: '正在思考',
  speaking: '正在回答',
};

function ConversationRoom() {
  const { state, audioTrack } = useVoiceAssistant();
  const { localParticipant } = useLocalParticipant();
  const transcriptions = useTranscriptions();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [transcriptions]);

  return (
    <section className="room">
      <div className="room-head">
        <div className="room-title">
          <div className="avatar"><Bot size={21} /></div>
          <div><strong>小禾</strong><span>ElevenLabs · DeepSeek · LiveKit</span></div>
        </div>
        <div className={`state state-${state}`}><span className="state-dot" />{stateLabels[state] ?? state}</div>
      </div>

      <div className="conversation" ref={scrollRef}>
        <div className="visualizer-wrap">
          {audioTrack ? (
            <BarVisualizer state={state} trackRef={audioTrack} barCount={21} className="visualizer" />
          ) : (
            <div className="waiting">正在等待实时语音 Agent 加入房间…</div>
          )}
        </div>
        <div className="transcript">
          {transcriptions.length === 0 && (
            <div className="empty-transcript">连接完成后直接说话，实时字幕会显示在这里。</div>
          )}
          {transcriptions.map((item) => {
            const isLocal = item.participantInfo.identity === localParticipant.identity;
            return (
              <div className={`message ${isLocal ? 'local' : ''}`} key={item.streamInfo.id}>
                <small>{isLocal ? '你' : '小禾'}</small>
                {item.text}
              </div>
            );
          })}
        </div>
      </div>

      <div className="controls">
        <TrackToggle className="control-button" source={Track.Source.Microphone} showIcon>
          <Mic size={19} />
        </TrackToggle>
        <DisconnectButton className="control-button disconnect">
          <PhoneOff size={18} /> 结束对话
        </DisconnectButton>
      </div>
      <RoomAudioRenderer />
    </section>
  );
}

export function VoiceAssistant() {
  const [connection, setConnection] = useState<ConnectionDetails | null>(null);
  const [accessCode, setAccessCode] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');

  async function start(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setError('');
    try {
      const response = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessCode }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || '无法创建实时语音房间');
      setConnection(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '连接失败，请稍后重试');
    } finally {
      setConnecting(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><Radio size={18} /></span>Persona Voice</div>
        <div className="live-badge">LiveKit 实时语音</div>
      </header>
      <div className="stage">
        {!connection ? (
          <section className="welcome">
            <p className="eyebrow">Realtime voice agent</p>
            <h1>像打电话一样，<br />自然地聊起来。</h1>
            <p className="lead">浏览器通过 WebRTC 直连 LiveKit。没有录音上传、Base64 转换或临时音频地址，支持实时字幕、连续对话和随时打断。</p>
            <form className="start-form" onSubmit={start}>
              <input className="code-input" type="password" autoComplete="current-password" placeholder="输入体验访问码" value={accessCode} onChange={(event) => setAccessCode(event.target.value)} aria-label="体验访问码" />
              <button className="primary-button" disabled={connecting} type="submit">
                {connecting ? <Radio size={18} /> : <Sparkles size={18} />}
                {connecting ? '正在建立实时连接…' : '开始语音对话'}
              </button>
              {error && <p className="error" role="alert">{error}</p>}
              <p className="privacy">麦克风音频通过 LiveKit 实时传输，不在本项目服务器保存。</p>
            </form>
          </section>
        ) : (
          <LiveKitRoom token={connection.participantToken} serverUrl={connection.serverUrl} connect audio video={false} onDisconnected={() => setConnection(null)} onError={(reason) => setError(reason.message)}>
            <ConversationRoom />
          </LiveKitRoom>
        )}
      </div>
    </main>
  );
}
