'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import {
  BarVisualizer,
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useChat,
  useLocalParticipant,
  useTranscriptions,
  useVoiceAssistant,
} from '@livekit/components-react';
import { Bot, Mic, PhoneOff, Radio, Send, Sparkles } from 'lucide-react';
import { MediaDeviceFailure, Track } from 'livekit-client';

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

function MicrophoneTest({ onReady }: { onReady: (ready: boolean) => void }) {
  const [testing, setTesting] = useState(false);
  const [ready, setReady] = useState(false);
  const [heardVoice, setHeardVoice] = useState(false);
  const [level, setLevel] = useState(0);
  const [message, setMessage] = useState('进入房间前先确认麦克风有声音。');
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const animationRef = useRef<number | null>(null);

  function stopTest() {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void contextRef.current?.close();
    contextRef.current = null;
  }

  useEffect(() => () => stopTest(), []);

  async function beginTest() {
    stopTest();
    setTesting(true);
    setReady(false);
    setHeardVoice(false);
    setLevel(0);
    onReady(false);

    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.72;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      streamRef.current = stream;
      contextRef.current = context;
      setReady(true);
      setMessage('麦克风已连接，请说一句话观察音量。');
      onReady(true);

      const updateLevel = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) {
          const normalized = (sample - 128) / 128;
          sum += normalized * normalized;
        }
        const nextLevel = Math.min(100, Math.sqrt(sum / samples.length) * 420);
        setLevel(nextLevel);
        if (nextLevel > 5) {
          setHeardVoice(true);
          setMessage('检测到声音，可以开始语音对话。');
        }
        animationRef.current = requestAnimationFrame(updateLevel);
      };
      updateLevel();
    } catch (reason) {
      const name = reason instanceof DOMException ? reason.name : '';
      const nextMessage = name === 'NotAllowedError'
        ? '麦克风权限被拒绝，请在地址栏的网站权限中允许麦克风。'
        : name === 'NotFoundError'
          ? '没有检测到麦克风，请连接设备后重试。'
          : name === 'NotReadableError'
            ? '麦克风可能正被其他应用占用，请关闭占用后重试。'
            : '无法启动麦克风，请检查浏览器和系统权限。';
      setMessage(nextMessage);
      setReady(false);
      onReady(false);
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className={`mic-test ${ready ? 'mic-test-ready' : ''}`}>
      <div className="mic-test-head">
        <span>{heardVoice ? '麦克风测试通过' : ready ? '等待声音输入' : '麦克风测试'}</span>
        <button className="mic-test-button" type="button" onClick={beginTest} disabled={testing}>
          <Mic size={15} />{testing ? '正在连接…' : ready ? '重新测试' : '测试麦克风'}
        </button>
      </div>
      <div className="mic-meter" aria-label="麦克风输入音量">
        <span style={{ width: `${Math.max(2, level)}%` }} />
      </div>
      <p>{message}</p>
    </div>
  );
}

function ConversationRoom({ mediaError }: { mediaError: string }) {
  const { state, audioTrack } = useVoiceAssistant();
  const { isMicrophoneEnabled, lastMicrophoneError, localParticipant } = useLocalParticipant();
  const { chatMessages, send, isSending } = useChat();
  const transcriptions = useTranscriptions();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [textInput, setTextInput] = useState('');
  const [textError, setTextError] = useState('');

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [chatMessages, transcriptions]);

  async function submitText(event: FormEvent) {
    event.preventDefault();
    const message = textInput.trim();
    if (!message || isSending) return;
    setTextError('');
    try {
      await send(message);
      setTextInput('');
    } catch {
      setTextError('文字消息发送失败，请确认房间仍然连接。');
    }
  }

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
        <div className={`microphone-status ${isMicrophoneEnabled ? 'microphone-ready' : 'microphone-blocked'}`} role="status">
          {isMicrophoneEnabled
            ? '麦克风已开启，正在实时传输声音'
            : mediaError || lastMicrophoneError
              ? '麦克风不可用：请在浏览器地址栏的网站权限中允许麦克风，然后重新进入。'
              : '麦克风当前关闭，请点击下方麦克风按钮开启。'}
        </div>
        <div className="visualizer-wrap">
          {audioTrack ? (
            <BarVisualizer state={state} trackRef={audioTrack} barCount={21} className="visualizer" />
          ) : (
            <div className="waiting">正在等待实时语音 Agent 加入房间…</div>
          )}
        </div>
        <div className="transcript">
          {transcriptions.length === 0 && chatMessages.length === 0 && (
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
          {chatMessages.map((item) => (
            <div className="message local" key={`chat-${item.id}`}>
              <small>你 · 文字输入</small>
              {item.message}
            </div>
          ))}
        </div>
      </div>

      <form className="text-input-form" onSubmit={submitText}>
        <div>
          <input
            value={textInput}
            onChange={(event) => setTextInput(event.target.value)}
            placeholder="语音没反应时，在这里输入文字测试 DeepSeek 和语音回复"
            aria-label="手动输入消息"
            maxLength={500}
          />
          <button type="submit" disabled={isSending || !textInput.trim()} aria-label="发送文字消息">
            <Send size={17} />{isSending ? '发送中' : '发送'}
          </button>
        </div>
        {textError && <p className="error">{textError}</p>}
      </form>

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
  const [mediaError, setMediaError] = useState('');
  const [microphoneReady, setMicrophoneReady] = useState(false);

  async function start(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setError('');
    setMediaError('');
    try {
      const response = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessCode: accessCode.trim() }),
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
              <MicrophoneTest onReady={setMicrophoneReady} />
              <button className="primary-button" disabled={connecting || !microphoneReady} type="submit">
                {connecting ? <Radio size={18} /> : <Sparkles size={18} />}
                {connecting ? '正在建立实时连接…' : microphoneReady ? '开始语音对话' : '请先测试麦克风'}
              </button>
              {error && <p className="error" role="alert">{error}</p>}
              <p className="privacy">麦克风音频通过 LiveKit 实时传输，不在本项目服务器保存。</p>
            </form>
          </section>
        ) : (
          <LiveKitRoom
            token={connection.participantToken}
            serverUrl={connection.serverUrl}
            connect
            audio={{ echoCancellation: true, noiseSuppression: true, autoGainControl: true }}
            video={false}
            onDisconnected={() => setConnection(null)}
            onError={(reason) => setError(reason.message)}
            onMediaDeviceFailure={(failure, kind) => {
              if (kind !== 'audioinput') return;
              const message = failure === MediaDeviceFailure.PermissionDenied
                ? '浏览器拒绝了麦克风权限。请在地址栏的网站权限中选择“允许麦克风”，然后重新进入。'
                : failure === MediaDeviceFailure.NotFound
                  ? '没有检测到可用麦克风，请连接麦克风后重新进入。'
                  : failure === MediaDeviceFailure.DeviceInUse
                    ? '麦克风正被其他应用占用，请关闭占用麦克风的应用后重试。'
                    : '麦克风启动失败，请检查浏览器的网站权限和系统麦克风权限。';
              setMediaError(message);
            }}
          >
            <ConversationRoom mediaError={mediaError} />
          </LiveKitRoom>
        )}
      </div>
    </main>
  );
}
