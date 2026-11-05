"use client";
import { useCallback, useEffect, useRef, useState } from "react";
type Line = {
  voice_route: string;
  caller: string;
  sim: number;
  recipient: string;
  numbers: string[];
  max_seconds: number;
  dial_enabled: boolean;
  reason: string;
  checked_at: string;
  checks: { id: string; label: string; ok: boolean; detail: string }[];
};
async function request(path: string, body?: object) {
  const r = await fetch("/api/consult/" + path, {
    method: body ? "POST" : "GET",
    headers: body
      ? { "Content-Type": "application/json", "X-Consultation": "1" }
      : {},
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const v = await r.json();
  if (!r.ok) throw Error(v.error || "请求失败");
  return v;
}
export default function PhoneDial({
  onStarted,
}: {
  onStarted: (id: string) => Promise<unknown>;
}) {
  const [line, setLine] = useState<Line | null>(null),
    [number, setNumber] = useState(""),
    [title, setTitle] = useState("电话自由对话");
  const [voiceRoute, setVoiceRoute] = useState("pipeline");
  const [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const pending = useRef<{
    requestId: string;
    number: string;
    title: string;
    voiceRoute: string;
  } | null>(null);
  const initializedRecipient = useRef(false);
  const refresh = useCallback(async () => {
    try {
      const next = await request("line?route=" + voiceRoute);
      setLine(next);
      if (!initializedRecipient.current) {
        setNumber((current) => current || next.recipient);
        initializedRecipient.current = true;
      }
      setError("");
    } catch (e) {
      setLine(null);
      setError(String(e));
    }
  }, [voiceRoute]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => clearInterval(timer);
  }, [refresh]);
  async function dial() {
    if (
      !pending.current &&
      !confirm(
        `将通过 SIM 2 拨打 ${number}，最长约 180 秒。确认接听方已准备好？`,
      )
    )
      return;
    setBusy(true);
    setError("");
    pending.current ??= { requestId: crypto.randomUUID(), number, title, voiceRoute };
    const payload = pending.current;
    try {
      const result = await request("phone-dial", {
        ...payload,
        template: "free-chat-v1",
        sim: 2,
        consent,
      });
      await onStarted(result.id);
      pending.current = null;
    } catch (e) {
      setError(
        (e instanceof Error ? e.message : String(e)) +
          "。重试将使用同一请求编号，不会重复拨号。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="cw-kicker">PHONE CONSULTATION</div>
      <h1>拨打咨询电话</h1>
      <p>检查线路 → 拨打 → 实时对话 → 结束归档。管理接口仅服务器本机可访问。</p>
      <div className="cw-grid">
        <section>
          <h2>咨询与接听方</h2>
          <label>语音路线
            <select value={voiceRoute} disabled={busy || !!pending.current}
              onChange={(e) => { setLine(null); setVoiceRoute(e.target.value); }}>
              <option value="pipeline">原路线 · ASR + DeepSeek + TTS</option>
              <option value="qwen-realtime">新路线 · Qwen 原生全双工（试用）</option>
            </select>
          </label>
          <label>
            咨询模板
            <select disabled={busy}>
              <option value="free-chat-v1">自由对话测试 v1</option>
            </select>
          </label>
          <small>目前开放一个已验证模板；内容由模型根据真实回答生成。</small>
          <label>
            咨询标题
            <input
              value={title}
              disabled={busy || !!pending.current}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            接听号码
            <input
              inputMode="tel"
              value={number}
              disabled={busy || !!pending.current}
              onChange={(e) => setNumber(e.target.value.replace(/\s/g, ""))}
            />
          </label>
          <p>配置主叫：{line?.caller || "未读取"} · SIM 2（逻辑槽位 1）；实际号码以 SIM 和接听端来电显示为准</p>
          <small>
            主叫号码由实体 SIM 决定。网页不远程切换卡槽。允许号码：
            {line?.numbers.join("、") || "等待服务器检查"}
          </small>
          <label>
            <input
              type="checkbox"
              checked={consent}
              disabled={busy}
              onChange={(e) => setConsent(e.target.checked)}
            />
            我已获得拨号授权；AI 开场将说明文字保存并征求参与同意。
          </label>
          <button
            disabled={
              busy ||
              !consent ||
              (!pending.current &&
                (!line?.dial_enabled || line.voice_route !== voiceRoute || !line.numbers.includes(number)))
            }
            onClick={() => void dial()}
          >
            {busy
              ? "正在提交…"
              : pending.current
                ? "查询或重试同一请求"
                : "拨打并进入实时对话"}
          </button>
          {error && (
            <p role="alert" className="cw-error">
              {error}
            </p>
          )}
        </section>
        <section>
          <h2>拨打前检查</h2>
          {line?.checks.map((check) => (
            <div key={check.id} className="cw-check">
              <strong>
                {check.ok ? "✓" : "○"} {check.label}
              </strong>
              <p>{check.detail}</p>
            </div>
          ))}
          <p>{line?.reason || "正在读取线路状态…"}</p>
          <small>
            检查通过不代表运营商或模型不会临时失败；完整链路以实际通话为准。最长{" "}
            {line?.max_seconds || 180} 秒。
          </small>
          <button
            className="cw-secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            重新检查
          </button>
        </section>
      </div>
    </>
  );
}
