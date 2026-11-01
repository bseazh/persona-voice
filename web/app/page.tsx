"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock3,
  Mic,
  PhoneCall,
  ShieldCheck,
  Square,
  Volume2,
} from "lucide-react";
import "./voice.css";

type Call = {
  id: string;
  phone_masked: string;
  status: string;
  mode: string;
  created_at: string;
  result?: { summary: string };
};
type Message = { role: "user" | "assistant"; content: string };
const terminal = new Set([
  "completed",
  "failed",
  "busy",
  "no_answer",
  "declined",
  "canceled",
  "timed_out",
]);

export default function Home() {
  const [phone, setPhone] = useState("+8613800000000");
  const [goal, setGoal] = useState(
    "询问明天下午三点是否可以安排两个人，并复述确认，但不执行真实预约。",
  );
  const [calls, setCalls] = useState<Call[]>([]);
  const [active, setActive] = useState<Call | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [voiceState, setVoiceState] = useState<
    "idle" | "recording" | "thinking" | "speaking"
  >("idle");
  const [voiceError, setVoiceError] = useState("");
  const [localVoiceReady, setLocalVoiceReady] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function loadCalls() {
    const res = await fetch("/api/calls");
    if (res.ok) setCalls((await res.json()).items);
  }
  useEffect(() => {
    loadCalls();
    fetch("/api/health")
      .then((response) => response.json())
      .then((health) =>
        setLocalVoiceReady(Boolean(health.local_conversation_enabled)),
      )
      .catch(() => setLocalVoiceReady(false));
  }, []);
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      audioRef.current?.pause();
    },
    [],
  );
  useEffect(() => {
    if (!active || terminal.has(active.status)) return;
    const timer = setInterval(async () => {
      const res = await fetch(`/api/calls/${active.id}`);
      if (res.ok) {
        const next = await res.json();
        setActive(next);
        if (terminal.has(next.status)) {
          setBusy(false);
          loadCalls();
        }
      }
    }, 700);
    return () => clearInterval(timer);
  }, [active]);

  async function start() {
    setBusy(true);
    setError("");
    const res = await fetch("/api/calls", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        phone_number: phone,
        task: {
          goal,
          language: "zh-CN",
          questions: ["明天下午是否有时间？", "是否可以两个人？"],
          required_slots: ["available_time", "party_size_supported"],
        },
        mode: "mock",
      }),
    });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail || "请求失败");
      setBusy(false);
      return;
    }
    const detail = await fetch(body.status_url).then((r) => r.json());
    setActive(detail);
    loadCalls();
  }

  function blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function submitRecording(blob: Blob) {
    setVoiceState("thinking");
    setVoiceError("");
    try {
      const audioBase64 = await blobToBase64(blob);
      const res = await fetch("/api/conversation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_base64: audioBase64,
          mime_type: blob.type || "audio/webm",
          history: messages.slice(-10).map((message) => ({
            role: message.role,
            content: message.content.slice(0, 2000),
          })),
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail
              .map((item: { msg?: string }) => item.msg || "参数无效")
              .join("；")
          : body.detail;
        throw new Error(detail || "语音对话请求失败");
      }
      setMessages((previous) => [
        ...previous,
        { role: "user", content: body.transcript },
        { role: "assistant", content: body.answer },
      ]);
      const rawAudioUrl =
        res.headers.get("X-Persona-Audio-Url") || body.audio_url;
      if (typeof rawAudioUrl !== "string") {
        throw new Error("语音回复地址无效");
      }
      const resolvedAudioUrl = new URL(rawAudioUrl, window.location.origin);
      if (
        resolvedAudioUrl.origin !== window.location.origin ||
        !resolvedAudioUrl.pathname.startsWith("/api/conversation/audio/")
      ) {
        throw new Error("语音回复地址无效");
      }
      const audio = new Audio(resolvedAudioUrl.href);
      audioRef.current = audio;
      audio.onended = () => {
        setVoiceState("idle");
      };
      audio.onerror = () => {
        setVoiceState("idle");
        setVoiceError("回复已生成，但音频播放失败");
      };
      setVoiceState("speaking");
      await audio.play();
    } catch (reason) {
      setVoiceState("idle");
      setVoiceError(reason instanceof Error ? reason.message : "语音对话失败");
    }
  }

  async function toggleRecording() {
    if (voiceState === "recording") {
      recorderRef.current?.stop();
      return;
    }
    if (voiceState !== "idle") return;
    try {
      setVoiceError("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const preferred = [
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/webm",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(
        stream,
        preferred ? { mimeType: preferred } : undefined,
      );
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        if (blob.size < 1000) {
          setVoiceState("idle");
          setVoiceError("录音太短，请重试");
          return;
        }
        submitRecording(blob);
      };
      recorder.start();
      setVoiceState("recording");
    } catch {
      setVoiceError("无法使用麦克风，请在浏览器地址栏允许麦克风权限");
    }
  }

  const voiceLabels = {
    idle: "点击开始说话",
    recording: "正在录音，点击结束",
    thinking: "正在识别并思考…",
    speaking: "小禾正在回答…",
  };

  return (
    <main>
      <header>
        <div className="brand">
          <span className="mark">
            <PhoneCall size={19} />
          </span>
          <span>Persona Voice</span>
        </div>
        <div className={`environment ${localVoiceReady ? "live" : ""}`}>
          <span></span>{" "}
          {localVoiceReady ? "本地语音可用" : "语音仅限本地启动"}
        </div>
      </header>
      <section className="workspace">
        <div className="intro">
          <div>
            <p className="eyebrow">AI 语音工作台</p>
            <h1>先和数字人面对面聊一聊</h1>
            <p className="sub">
              无需 SIP 或电话号码，直接使用电脑麦克风体验完整语音对话。
            </p>
          </div>
          <div className="safety">
            <ShieldCheck size={20} />
            <div>
              <strong>电话外呼仍锁定</strong>
              <small>本地对话不会拨号，不产生电话线路费用</small>
            </div>
          </div>
        </div>
        <section className="voice-panel">
          <div className="voice-head">
            <div>
              <p className="eyebrow">LIVE VOICE</p>
              <h2>和小禾对话</h2>
              <p>ElevenLabs 识别与合成 · DeepSeek 对话</p>
            </div>
            <div className={`voice-status ${voiceState}`}>
              <span></span>
              {voiceLabels[voiceState]}
            </div>
          </div>
          <div className="conversation">
            {messages.length === 0 ? (
              <div className="conversation-empty">
                <Volume2 size={26} />
                <strong>你好，我是小禾</strong>
                <span>点击下方按钮，说一句“你好”试试</span>
              </div>
            ) : (
              messages.map((message, index) => (
                <div key={index} className={`bubble ${message.role}`}>
                  <small>{message.role === "user" ? "你" : "小禾"}</small>
                  <p>{message.content}</p>
                </div>
              ))
            )}
            {voiceState === "thinking" && (
              <div className="bubble assistant pending">
                <small>小禾</small>
                <p>正在听懂你的话…</p>
              </div>
            )}
          </div>
          {voiceError && <p className="error voice-error">{voiceError}</p>}
          <div className="voice-actions">
            <button
              className={`record-button ${voiceState}`}
              onClick={toggleRecording}
              disabled={
                !localVoiceReady ||
                voiceState === "thinking" ||
                voiceState === "speaking"
              }
            >
              {voiceState === "recording" ? (
                <Square size={19} />
              ) : (
                <Mic size={20} />
              )}{" "}
              {localVoiceReady
                ? voiceLabels[voiceState]
                : "请在本地启动后使用"}
            </button>
            {messages.length > 0 && (
              <button
                className="clear-button"
                onClick={() => setMessages([])}
                disabled={voiceState !== "idle"}
              >
                清空对话
              </button>
            )}
          </div>
        </section>
        <div className="section-divider">
          <span>模拟外呼功能</span>
        </div>
        <div className="grid">
          <section className="panel form-panel">
            <div className="panel-title">
              <h2>新建任务</h2>
              <span>MOCK</span>
            </div>
            <label>
              目标号码 <small>E.164 格式</small>
            </label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+8613800000000"
            />
            <label>
              任务目标 <small>{goal.length}/1000</small>
            </label>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              maxLength={1000}
            />
            {error && <p className="error">{error}</p>}
            <button onClick={start} disabled={busy || !phone || !goal}>
              <PhoneCall size={17} />
              {busy ? "任务进行中" : "开始模拟通话"}
            </button>
          </section>
          <section className="panel status-panel">
            <div className="panel-title">
              <h2>当前状态</h2>
              <Activity size={18} />
            </div>
            {active ? (
              <div className="active">
                <div
                  className={`status-icon ${active.status === "completed" ? "done" : ""}`}
                >
                  {active.status === "completed" ? (
                    <CheckCircle2 />
                  ) : (
                    <Clock3 />
                  )}
                </div>
                <p className="status-name">{active.status}</p>
                <p className="call-id">{active.id}</p>
                <div className="steps">
                  {[
                    "queued",
                    "dispatching",
                    "dialing",
                    "connected",
                    "completed",
                  ].map((step) => (
                    <span
                      key={step}
                      className={
                        step === active.status || active.status === "completed"
                          ? "on"
                          : ""
                      }
                    >
                      {step}
                    </span>
                  ))}
                </div>
                {active.result && (
                  <div className="result">{active.result.summary}</div>
                )}
              </div>
            ) : (
              <div className="empty">
                <PhoneCall size={28} />
                <p>尚未发起任务</p>
                <small>状态事件将在这里实时更新</small>
              </div>
            )}
          </section>
        </div>
        <section className="history">
          <div className="section-heading">
            <div>
              <p className="eyebrow">RECENT ACTIVITY</p>
              <h2>最近任务</h2>
            </div>
            <span>{calls.length} 条记录</span>
          </div>
          <div className="table">
            <div className="row head">
              <span>创建时间</span>
              <span>号码</span>
              <span>模式</span>
              <span>状态</span>
            </div>
            {calls.map((call) => (
              <div className="row" key={call.id}>
                <span>{new Date(call.created_at).toLocaleString("zh-CN")}</span>
                <span>{call.phone_masked}</span>
                <span>{call.mode}</span>
                <span className={`badge ${call.status}`}>{call.status}</span>
              </div>
            ))}
            {calls.length === 0 && <div className="no-rows">暂无历史记录</div>}
          </div>
        </section>
      </section>
    </main>
  );
}
