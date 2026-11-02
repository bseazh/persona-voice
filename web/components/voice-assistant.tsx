'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  BarVisualizer,
  DisconnectButton,
  RoomContext,
  RoomAudioRenderer,
  TrackToggle,
  useChat,
  useLocalParticipant,
  useTranscriptions,
  useVoiceAssistant,
} from '@livekit/components-react';
import { Bot, Mic, PhoneOff, Radio, Send, Sparkles } from 'lucide-react';
import { DisconnectReason, MediaDeviceFailure, Room, RoomEvent, Track } from 'livekit-client';

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

function MicrophoneTest({ onReady, onDevice }: { onReady: (ready: boolean) => void; onDevice: (deviceId: string) => void }) {
  const [testing, setTesting] = useState(false);
  const [ready, setReady] = useState(false);
  const [heardVoice, setHeardVoice] = useState(false);
  const [level, setLevel] = useState(0);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [db, setDb] = useState(-100);
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

  async function beginTest(selected = deviceId) {
    stopTest();
    setTesting(true);
    setReady(false);
    setHeardVoice(false);
    setLevel(0);
    onReady(false);

    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: selected ? { exact: selected } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      const context = new AudioContext();
      await context.resume();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.72;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      streamRef.current = stream;
      contextRef.current = context;
      setReady(true);
      const actualDevice = stream.getAudioTracks()[0].getSettings().deviceId || selected;
      setDeviceId(actualDevice);
      onDevice(actualDevice);
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === 'audioinput'));
      setMessage('麦克风已连接，请说一句话观察音量。');
      let voicedFrames = 0;

      const updateLevel = () => {
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) {
          sum += sample * sample;
        }
        const decibels = 20 * Math.log10(Math.max(0.00001, Math.sqrt(sum / samples.length)));
        const nextLevel = Math.max(0, Math.min(100, (decibels + 60) / 60 * 100));
        setDb(Math.round(decibels));
        setLevel(nextLevel);
        if (decibels > -45) voicedFrames++;
        if (voicedFrames >= 20) {
          setHeardVoice(true);
          onReady(true);
          setMessage('已检测到持续声音，可以进入。音量测试不代表语音识别已通过。');
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
        <button className="mic-test-button" type="button" onClick={() => void beginTest()} disabled={testing}>
          <Mic size={15} />{testing ? '正在连接…' : ready ? '重新测试' : '测试麦克风'}
        </button>
      </div>
      {devices.length > 0 && <select className="mic-device" aria-label="选择麦克风" value={deviceId} disabled={testing} onChange={(event) => {
        const selected = event.target.value;
        setDeviceId(selected);
        void beginTest(selected);
      }}>{devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `麦克风 ${index + 1}`}</option>)}</select>}
      <div className="mic-level-label"><strong>{ready ? db < -55 ? '未检测到明显声音' : db < -35 ? '声音较轻' : db > -6 ? '声音过大，请稍远离麦克风' : '音量清晰' : '点击测试，然后说一句完整的话'}</strong><span>{ready ? `${db} dBFS` : '等待测试'}</span></div>
      <div className="mic-meter mic-meter-large" role="meter" aria-label="麦克风输入音量" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)}>
        <span style={{ width: `${level}%` }} />
      </div>
      <div className="mic-scale"><span>静音</span><span>轻声</span><span>清晰</span><span>过响</span></div>
      <p>{message}</p>
    </div>
  );
}

function ConversationRoom({ mediaError, accessCode, deviceId }: { mediaError: string; accessCode: string; deviceId: string }) {
  const { state, audioTrack } = useVoiceAssistant();
  const { isMicrophoneEnabled, lastMicrophoneError, localParticipant } = useLocalParticipant();
  const { chatMessages, send, isSending } = useChat();
  const transcriptions = useTranscriptions();
  const scrollRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [textInput, setTextInput] = useState('');
  const [textError, setTextError] = useState('');
  const [dictating, setDictating] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [inputMode, setInputMode] = useState<'realtime' | 'recording'>('realtime');
  const [recordingUrl, setRecordingUrl] = useState('');
  const [recordingLevel, setRecordingLevel] = useState(0);
  const [recordingDevice, setRecordingDevice] = useState('');
  const meterRef = useRef<{ context: AudioContext; timer: ReturnType<typeof setInterval> } | null>(null);

  function stopMeter() {
    if (meterRef.current) {
      clearInterval(meterRef.current.timer);
      void meterRef.current.context.close();
      meterRef.current = null;
    }
  }

  useEffect(() => () => { if (recordingUrl) URL.revokeObjectURL(recordingUrl); }, [recordingUrl]);

  useEffect(() => () => {
    stopMeter();
    if (timerRef.current) clearTimeout(timerRef.current);
    if (recorderRef.current) {
      recorderRef.current.onstop = null;
      if (recorderRef.current.state !== 'inactive') recorderRef.current.stop();
    }
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [chatMessages, transcriptions]);

  async function toggleDictation() {
    if (dictating) {
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
      return;
    }
    if (transcribing) return;
    setTextError('');
    setTranscribing(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('当前浏览器不支持录音，请使用新版浏览器。');
      // Keep live ASR muted so this utterance cannot trigger two replies.
      await localParticipant.setMicrophoneEnabled(false);
      setInputMode('recording');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: deviceId ? { exact: deviceId } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      recordingStreamRef.current = stream;
      setRecordingUrl('');
      setRecordingDevice(stream.getAudioTracks()[0]?.label || '默认麦克风');
      setRecordingLevel(0);
      const context = new AudioContext();
      await context.resume();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      meterRef.current = { context, timer: setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
        setRecordingLevel(Math.min(100, rms * 500));
      }, 100) };
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        stopMeter();
        if (timerRef.current) clearTimeout(timerRef.current);
        stream.getTracks().forEach((track) => track.stop());
        setDictating(false);
        setTranscribing(true);
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType });
          setRecordingUrl(URL.createObjectURL(blob));
          const form = new FormData();
          form.set('audio', blob, recorder.mimeType.includes('mp4') ? 'recording.m4a' : 'recording.webm');
          const response = await fetch('/api/transcribe', {
            method: 'POST', headers: { 'x-voice-access-code': accessCode.trim() },
            body: form, signal: AbortSignal.timeout(55_000),
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || `识别请求失败（${response.status}）`);
          setTextInput((previous) => `${previous.trim()} ${result.text}`.trim().slice(0, 500));
        } catch (error) {
          setTextError(error instanceof Error ? error.message : '录音识别失败');
        } finally {
          setTranscribing(false);
        }
      };
      recorder.start();
      setDictating(true);
      setTranscribing(false);
      timerRef.current = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 60_000);
    } catch (error) {
      stopMeter();
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
      setTranscribing(false);
      setTextError(error instanceof Error ? error.message : '无法开始录音');
    }
  }

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
          <div><strong>小禾</strong><span>千问识别 · DeepSeek · 千问语音</span></div>
        </div>
        <div className={`state state-${state}`}><span className="state-dot" />{stateLabels[state] ?? state}</div>
      </div>

      <div className="conversation" ref={scrollRef}>
        <div className="input-modes" role="group" aria-label="对话模式">
          <button type="button" aria-pressed={inputMode === 'realtime'} disabled={dictating || transcribing} onClick={async () => {
            try { await localParticipant.setMicrophoneEnabled(true); setInputMode('realtime'); setTextError(''); }
            catch { setTextError('无法开启实时麦克风，请检查设备连接。'); }
          }}>实时对话</button>
          <button type="button" aria-pressed={inputMode === 'recording'} disabled={dictating || transcribing} onClick={async () => {
            try { await localParticipant.setMicrophoneEnabled(false); setInputMode('recording'); }
            catch { setTextError('无法切换录音模式，请重试。'); }
          }}>录音转文字（备用）</button>
        </div>
        <p className="privacy">{inputMode === 'realtime' ? '直接说话即可，停顿后自动回复；助手说话时也可以开口打断。' : '点击输入框旁的麦克风录音，停止后确认文字再发送。'}</p>
        <div className={`microphone-status ${isMicrophoneEnabled ? 'microphone-ready' : 'microphone-blocked'}`} role="status">
          {isMicrophoneEnabled
            ? '实时通话麦克风已开启'
            : mediaError || lastMicrophoneError
              ? '麦克风不可用：请在浏览器地址栏的网站权限中允许麦克风，然后重新进入。'
              : '实时通话已静音；可使用输入框旁的录音按钮，或开启下方通话麦克风。'}
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
            placeholder="输入消息，或点击右侧麦克风录音"
            aria-label="手动输入消息"
            maxLength={500}
            disabled={dictating || transcribing}
          />
          <button
            className={`dictation-button ${dictating ? 'dictation-active' : ''}`}
            type="button"
            onClick={toggleDictation}
            disabled={transcribing}
            aria-label={dictating ? '停止语音输入' : '使用语音输入文字'}
            title={dictating ? '停止录音并识别' : '录音转文字'}
          >
            <Mic size={17} />
          </button>
          <button type="submit" disabled={dictating || transcribing || isSending || !textInput.trim()} aria-label="发送文字消息">
            <Send size={17} />{isSending ? '发送中' : '发送'}
          </button>
        </div>
        <p className="privacy" role="status">{dictating ? '正在录音，再点麦克风停止并识别（最长 60 秒）。' : transcribing ? '正在准备录音或识别，请稍候…' : '点击麦克风录音 → 再点停止 → 文字填入后确认发送。录音模式会关闭实时通话麦克风。'}</p>
        {textError && <p className="error">{textError}</p>}
        {dictating && <div className="mic-test">
          <p>正在录制：{recordingDevice} · 请观察说话时音量是否变化</p>
          <div className="mic-meter" aria-label="录音输入音量"><span style={{ width: `${Math.max(2, recordingLevel)}%` }} /></div>
        </div>}
        {recordingUrl && <div className="mic-test">
          <p>试听刚才实际上传的录音（仅保留在当前页面）：</p>
          <audio controls src={recordingUrl} style={{ width: '100%' }} />
        </div>}
      </form>

      <div className="controls">
        <TrackToggle className="control-button" source={Track.Source.Microphone} showIcon disabled={dictating || transcribing} onChange={(enabled) => { if (enabled) setInputMode('realtime'); }}>
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

function VoiceSession({ connection, accessCode, deviceId, onLeave }: {
  connection: ConnectionDetails; accessCode: string; deviceId: string;
  onLeave: (message: string) => void;
}) {
  const [room, setRoom] = useState<Room>();
  const [mediaError, setMediaError] = useState('');

  useEffect(() => {
    const current = new Room();
    let active = true;
    let connected = false;
    setRoom(current);
    const disconnected = (reason?: DisconnectReason) => {
      // A failed join emits Disconnected before connect() rejects. Let the
      // rejection report its original error before unmounting the room.
      if (!active || !connected) return;
      onLeave(reason === DisconnectReason.CLIENT_INITIATED ? ''
        : '实时连接已断开，自动重连未成功。请检查网络后重新进入。');
    };
    current.on(RoomEvent.Disconnected, disconnected);
    void (async () => {
      try {
        await current.connect(connection.serverUrl, connection.participantToken);
      } catch (reason) {
        if (!active) return;
        console.warn('voice_connection_failed', reason);
        onLeave('无法建立实时语音连接，请检查网络后重试。' +
          (reason instanceof Error ? `（${reason.message}）` : ''));
        return;
      }
      if (!active) return;
      connected = true;
      try {
        await current.localParticipant.setMicrophoneEnabled(true, {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        });
      } catch (reason) {
        if (!active) return;
        const failure = MediaDeviceFailure.getFailure(reason);
        setMediaError(failure === MediaDeviceFailure.PermissionDenied
          ? '浏览器拒绝了麦克风权限。请在网站权限中允许麦克风后重试。'
          : '麦克风启动失败，请检查所选设备和系统权限，也可以先发送文字。');
      }
    })();
    return () => {
      active = false;
      current.off(RoomEvent.Disconnected, disconnected);
      void current.disconnect();
    };
  }, [connection, deviceId, onLeave]);

  if (!room) return <p role="status">正在建立实时连接…</p>;
  return <RoomContext.Provider value={room}>
    <ConversationRoom mediaError={mediaError} accessCode={accessCode} deviceId={deviceId} />
    <button type="button" className="mic-test-button" onClick={() => onLeave('')}>返回首页</button>
  </RoomContext.Provider>;
}

export function VoiceAssistant() {
  const [connection, setConnection] = useState<ConnectionDetails | null>(null);
  const [accessCode, setAccessCode] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');
  const [microphoneReady, setMicrophoneReady] = useState(false);
  const [deviceId, setDeviceId] = useState('');
  const leave = useCallback((message: string) => {
    setConnection(null);
    setMicrophoneReady(false);
    setError(message);
  }, []);

  async function start(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setError('');
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
            <p className="lead">支持实时语音与文字对话，也可以点击输入框旁的麦克风录音，确认识别文字后发送。</p>
            <form className="start-form" onSubmit={start}>
              <input className="code-input" type="password" autoComplete="current-password" placeholder="输入体验访问码" value={accessCode} onChange={(event) => setAccessCode(event.target.value)} aria-label="体验访问码" />
              <MicrophoneTest onReady={setMicrophoneReady} onDevice={setDeviceId} />
              <button className="primary-button" disabled={connecting || !microphoneReady} type="submit">
                {connecting ? <Radio size={18} /> : <Sparkles size={18} />}
                {connecting ? '正在建立实时连接…' : microphoneReady ? '开始语音对话' : '请先测试麦克风'}
              </button>
              {error && <p className="error" role="alert">{error}</p>}
              <p className="privacy">麦克风音频通过 LiveKit 实时传输，不在本项目服务器保存。</p>
            </form>
          </section>
        ) : (
          <VoiceSession connection={connection} accessCode={accessCode} deviceId={deviceId} onLeave={leave} />
        )}
      </div>
    </main>
  );
}
