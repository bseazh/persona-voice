"use client";
import { useEffect, useState } from "react";
type Event = {
  seq: number;
  kind: string;
  created_at: string;
  payload: Record<string, unknown>;
};
const labels: Record<string, string> = {
  "phone.requested": "拨号请求",
  "phone.state": "电话线路",
  "phone.submit_error": "拨号提交异常",
  "phone.hangup_requested": "人工挂断请求",
  "voice.state": "助手状态",
  "voice.message": "最终转录",
  "voice.generated": "模型生成（不等于已播放）",
  "voice.metrics": "阶段耗时",
  "voice.error": "语音服务错误",
  "voice.ending": "准备结束语",
  "voice.farewell_played": "结束语播放完成",
  "voice.farewell_failed": "结束语播放失败",
  "voice.closed": "会话关闭",
  "report.generated": "报告生成",
  "report.failed": "报告失败",
};
export default function Diagnostics({
  id,
  closed,
}: {
  id: string;
  closed: boolean;
}) {
  const [events, setEvents] = useState<Event[]>([]),
    [error, setError] = useState(""),
    [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let stopped = false;
    async function read() {
      try {
        const r = await fetch("/api/consult/events?id=" + id, {
          cache: "no-store",
        });
        if (!r.ok) throw Error("日志暂时无法读取");
        const data = await r.json();
        if (!stopped) {
          setEvents(data);
          setError("");
        }
      } catch (e) {
        if (!stopped) setError(String(e));
      }
    }
    void read();
    const timer = setInterval(() => void read(), closed ? 15000 : 3000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [id, closed]);
  const latest = (kind: string) => events.findLast((e) => e.kind === kind);
  const state = latest("voice.state"),
    phone = latest("phone.state"),
    failure = latest("voice.error");
  const hints: Record<string, string> = {
    listening: "正在等待有效语音；长时间无转录时检查手机音频或麦克风",
    thinking: "已进入回复阶段；长时间停留时检查 LLM 调用与耗时",
    speaking: "正在输出语音；无声音时检查 TTS 和播放/电话音频链路",
    initializing: "正在建立语音会话",
    idle: "等待输入或助手就绪",
  };
  const stage = closed
    ? "已结束，可核对转录、结束原因和报告"
    : state
      ? hints[String(state.payload.state)] || String(state.payload.state)
      : phone
        ? {
            queued: "拨号请求已提交",
            dialing: "正在呼叫接听方",
            connected: "电话已接通，等待 AI 进入",
            uncertain: "拨号结果待确认，请勿重复拨打",
            ended: "电话已结束，等待归档",
            failed: "未建立通话",
          }[String(phone.payload.state)] || "检查线路"
        : "等待会话启动";
  const metrics = events.filter((e) => e.kind === "voice.metrics");
  return (
    <section className="cw-diagnostics">
      <h2>运行诊断 · 管理员</h2>
      <p role="status">{stage}</p>
      <small>
        阶段提示用于定位，不把“正在聆听”直接判为 ASR
        故障。记录执行结果与耗时，不记录模型隐藏思维。
      </small>
      {error && <p role="alert">{error}</p>}
      {failure && (
        <p className="cw-error">
          最近语音异常：{String(failure.payload.type)} ·{" "}
          {new Date(failure.created_at).toLocaleTimeString()}
        </p>
      )}
      <div className="cw-diagnostic-grid">
        {["STTMetrics", "LLMMetrics", "TTSMetrics", "EOUMetrics"].map(
          (type) => {
            const m = metrics.findLast((e) => e.payload.type === type)?.payload;
            return (
              <div key={type}>
                <strong>
                  {
                    {
                      STTMetrics: "识别",
                      LLMMetrics: "模型回复",
                      TTSMetrics: "语音合成",
                      EOUMetrics: "停顿与轮次",
                    }[type]
                  }
                </strong>
                <p>
                  {m
                    ? Object.entries(m)
                        .filter(
                          ([k, v]) =>
                            typeof v === "number" && !k.includes("tokens"),
                        )
                        .map(([k, v]) => `${k}: ${Number(v).toFixed(2)} s`)
                        .join(" · ")
                    : "尚无该阶段指标"}
                </p>
              </div>
            );
          },
        )}
      </div>
      <button className="cw-secondary" onClick={() => setExpanded(!expanded)}>
        {expanded ? "收起" : "展开"}完整事件时间线（{events.length}）
      </button>
      {expanded && (
        <div className="cw-audit">
          {events.map((e) => (
            <details key={e.seq}>
              <summary>
                {new Date(e.created_at).toLocaleTimeString()} ·{" "}
                {labels[e.kind] || e.kind}
                {e.kind === "voice.message"
                  ? e.payload.role === "user"
                    ? " · 用户识别"
                    : " · 助手播放同步"
                  : ""}
                {e.payload.interrupted ? " · 被打断" : ""}
              </summary>
              <pre>{JSON.stringify(e.payload, null, 2)}</pre>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
