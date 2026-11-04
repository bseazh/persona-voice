"use client";
import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, LocalAudioTrack } from "livekit-client";
import {
  RoomContext,
  RoomAudioRenderer,
  StartAudio,
  TrackToggle,
  useVoiceAssistant,
  useLocalParticipant,
  useTranscriptions,
  useTrackVolume,
  MediaDeviceSelect,
} from "@livekit/components-react";

async function request(path: string, id: string) {
  const r = await fetch("/api/consult/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Consultation": "1" },
    body: JSON.stringify({ id }),
  });
  const v = await r.json();
  if (!r.ok) throw Error(v.error || "连接失败");
  return v;
}
function Controls() {
  const { state } = useVoiceAssistant();
  const { localParticipant } = useLocalParticipant();
  const volume = useTrackVolume(
    localParticipant.getTrackPublication(Track.Source.Microphone)?.track as
      LocalAudioTrack | undefined,
  );
  const transcriptions = useTranscriptions();
  const last = transcriptions.at(-1);
  return (
    <>
      <p role="status">
        {(
          {
            listening: "正在聆听",
            thinking: "正在整理回复",
            speaking: "小禾正在回答",
            initializing: "助手正在上线",
            idle: "等待助手",
            connecting: "连接中",
            disconnected: "助手未连接",
          } as Record<string, string>
        )[state] || state}
      </p>
      <label>
        麦克风音量{" "}
        <meter
          min={0}
          max={100}
          value={Math.min(100, volume * 300)}
          style={{ width: "100%", height: 28 }}
        />
      </label>
      <div className="cw-voice-controls">
        <TrackToggle source={Track.Source.Microphone}>麦克风开关</TrackToggle>
        <MediaDeviceSelect kind="audioinput" />
      </div>
      <StartAudio label="点击允许播放声音" />
      {last && (
        <p aria-live="polite" className="cw-notice">
          即时字幕：{last.text}
        </p>
      )}
      <small>
        即时字幕可能修订；下方保留最终识别和播放同步文字。直接开口可打断普通回答。离开此页会断开语音。
      </small>
      <RoomAudioRenderer />
    </>
  );
}
export default function VoiceRoom({
  id,
  ending,
}: {
  id: string;
  ending: boolean;
}) {
  const [room, setRoom] = useState<Room | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const ref = useRef<Room | null>(null);
  useEffect(
    () => () => {
      void ref.current?.disconnect();
      ref.current = null;
    },
    [],
  );
  async function join() {
    setBusy(true);
    setError("");
    const next = new Room({
      adaptiveStream: true,
      dynacast: true,
      audioCaptureDefaults: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    ref.current = next;
    try {
      const token = await request("voice-token", id);
      next.on(RoomEvent.Disconnected, () => {
        setRoom(null);
        setError("语音已断开，正在保存会话。");
      });
      next.on(RoomEvent.MediaDevicesError, () =>
        setError("无法读取麦克风，请检查浏览器权限和设备选择。"),
      );
      await next.connect(token.serverUrl, token.participantToken);
      await next.startAudio();
      await next.localParticipant.setMicrophoneEnabled(true);
      setRoom(next);
    } catch (e) {
      await next.disconnect();
      setError(e instanceof Error ? e.message : "无法连接语音");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>网页实时语音</h2>
      {error && (
        <p role="alert" className="cw-error">
          {error}
        </p>
      )}
      {ending ? (
        <p>正在播放结束语，请稍候；播放完成后自动归档。</p>
      ) : (
        !room && (
          <button disabled={busy} onClick={join}>
            {busy ? "正在连接…" : "连接麦克风并开始"}
          </button>
        )
      )}
      {room && (
        <RoomContext.Provider value={room}>
          <Controls />
        </RoomContext.Provider>
      )}
      <button
        className="cw-quiet"
        onClick={async () => {
          if (confirm("强制断开并归档？结束语可能无法播放。")) {
            await request("voice-abort", id);
            await ref.current?.disconnect();
          }
        }}
      >
        异常时强制结束
      </button>
    </section>
  );
}
