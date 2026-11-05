"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import VoiceRoom from "./voice-room";
import PhoneDial from "./phone-dial";
import Diagnostics from "./diagnostics";
import DoubaoSettings from "./doubao-settings";
import ProjectForm from "./project-form";
import { procurementId, projectFields } from "@/lib/procurement";
import "./workspace.css";
type Message = {
  id: string;
  role: string;
  text: string;
  created_at: string;
  interrupted?: boolean;
};
type Consultation = {
  id: string;
  title: string;
  status: string;
  mode: "text" | "voice" | "phone";
  voice_state?: string;
  voice_route?: "pipeline" | "pipeline-mimo" | "pipeline-mimo-all" | "qwen-realtime" | "doubao-realtime" | "baidu-realtime";
  phone_state?: string;
  created_at: string;
  ended_at?: string;
  reason?: string;
  report_status: string;
  messages: Message[];
  facts: Record<string, { value: string; source: string }>;
  risks: { text: string; source: string }[];
  report?: { summary: string; next_steps: string[]; limitations: string };
  lease_until?: string;
  template?: { id: string; title: string; fields: Record<string, string>; project?: Record<string,string> };
};
type Speech = {
  configured: boolean;
  workspace: string;
  asr_test?: { ok: boolean; at: string };
  tts_test?: { ok: boolean; at: string };
};
const legacyFields: Record<string, string> = {
  schedule: "作息时间",
  onset: "入睡情况",
  awakenings: "夜间醒来",
  daytime: "白天状态",
  habits: "生活习惯",
  goal: "改善目标",
};
async function api(path: string, body?: unknown) {
  const response = await fetch("/api/consult/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-Consultation": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
export default function Workspace() {
  const [logged, setLogged] = useState<boolean | null>(null),
    [password, setPassword] = useState(""),
    [page, setPage] = useState("sessions"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [list, setList] = useState<Consultation[]>([]),
    [current, setCurrent] = useState<Consultation | null>(null),
    [text, setText] = useState(""),
    [title, setTitle] = useState("自由对话测试"),
    [consent, setConsent] = useState(false);
  const [speech, setSpeech] = useState<Speech>({
      configured: false,
      workspace: "llm-w115702gcv6zwvwy",
    }),
    [key, setKey] = useState(""),
    [audio, setAudio] = useState(""),
    [asr, setAsr] = useState("");
  const [file, setFile] = useState<File | null>(null),
    [logs, setLogs] = useState<
      { seq: number; kind: string; payload: unknown; created_at: string }[]
    >([]);
  const requestRef = useRef<{
    id: string;
    text: string;
    requestId: string;
  } | null>(null);
  const [mode, setMode] = useState<"text" | "voice">("voice");
  const [voiceRoute, setVoiceRoute] = useState("pipeline");
  const [businessTemplate,setBusinessTemplate]=useState(procurementId);
  const [project,setProject]=useState<Record<string,string>>({});
  const fields = current?.template?.fields || (current?.template?.id === "free-chat-v1" ? {} : legacyFields);
  async function refreshList() {
    setList(await api("sessions"));
  }
  async function load(id: string) {
    const c = await api("session?id=" + id);
    setCurrent(c);
    setPage(c.status === "closed" ? "result" : "chat");
    return c;
  }
  useEffect(() => {
    api("me")
      .then(() => {
        setLogged(true);
        api("sessions")
          .then(setList)
          .catch(() => {});
      })
      .catch(() => setLogged(false));
  }, []);
  useEffect(() => {
    if (!current || !["chat", "result"].includes(page)) return;
    const id = current.id;
    const interval = setInterval(() => {
      api("session?id=" + id)
        .then((c) => {
          setCurrent(c);
          if (c.status === "closed") setPage("result");
        })
        .catch(() => {});
    }, 1500);
    return () => clearInterval(interval);
  }, [current?.id, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (
      page === "result" &&
      current?.status === "closed" &&
      current.report_status === "pending"
    ) {
      void report(current.id);
    }
  }, [page, current?.id, current?.report_status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(
    () => () => {
      if (audio) URL.revokeObjectURL(audio);
    },
    [audio],
  );
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    await run(async () => {
      const c = await api("create", { title:businessTemplate===procurementId ? project.project || title : title, consent, mode, voiceRoute, template:businessTemplate, project });
      await load(c.id);
      await refreshList();
      if (mode === "voice") return;
      const first = await api("turn", {
        id: c.id,
        requestId: crypto.randomUUID(),
      });
      setCurrent(first);
    });
  }
  async function send(finish = false) {
    if (!current) return;
    if (current.mode !== "text") {
      await run(async () => {
        await api("voice-end", { id: current.id });
        setNotice("已请求结束，等待结束语播放和归档。");
      });
      return;
    }
    await run(async () => {
      const value = text.trim();
      if (!finish && !value) return;
      let request = requestRef.current;
      if (
        !request ||
        request.id !== current.id ||
        request.text !== value ||
        finish
      ) {
        request = {
          id: current.id,
          text: value,
          requestId: crypto.randomUUID(),
        };
        requestRef.current = request;
      }
      const c = await api("turn", {
        ...request,
        text: finish ? null : value,
        finish,
      });
      requestRef.current = null;
      setText("");
      setCurrent(c);
      if (c.status === "closed") setPage("result");
      await refreshList();
    });
  }
  async function report(id: string) {
    await run(async () => {
      await api("report", { id });
      await load(id);
      await refreshList();
    });
  }
  async function navigation(next: string) {
    await run(async () => {
      setPage(next);
      if (next === "sessions") await refreshList();
      if (next === "speech") setSpeech(await api("speech"));
    });
  }
  async function test(kind: string) {
    await run(async () => {
      let body: FormData | undefined;
      if (kind === "asr") {
        if (!file) throw Error("请先选择短语音文件");
        body = new FormData();
        body.append("audio", file);
      }
      const r = await fetch("/api/consult/test-" + kind, {
        method: "POST",
        headers: { "X-Consultation": "1" },
        body,
      });
      if (!r.ok) {
        const v = await r.json();
        throw Error(v.error);
      }
      if (kind === "tts") {
        setAudio(URL.createObjectURL(await r.blob()));
        setNotice("音频已返回，请点击播放器试听。");
      } else {
        const v = await r.json();
        setAsr(v.text);
        setNotice(v.notice);
      }
      setSpeech(await api("speech"));
    });
  }
  const duration = current?.ended_at
    ? Math.round(
        (new Date(current.ended_at).getTime() -
          new Date(current.created_at).getTime()) /
          1000,
      )
    : 0;
  return (
    <div className="cw">
      <header className="cw-header">
        <a href="/consult" className="cw-brand">
          PERSONA<span>咨询工作台</span>
        </a>
        <span className="cw-tag">实时语音 / 文字 · 自由对话</span>
        {logged && (
          <button
            className="cw-quiet"
            onClick={() =>
              run(async () => {
                await api("logout", {});
                setLogged(false);
                setCurrent(null);
                setList([]);
              })
            }
          >
            退出
          </button>
        )}
      </header>
      {logged === null ? (
        <main>正在检查登录…</main>
      ) : !logged ? (
        <main className="cw-login">
          <div className="cw-kicker">WORKSPACE ACCESS</div>
          <h1>欢迎回来</h1>
          <p>登录后开展咨询、查看报告并配置语音服务。</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await api("login", { password });
                setPassword("");
                setLogged(true);
                await refreshList();
              });
            }}
          >
            <label>
              工作台管理员密码
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            <button disabled={busy}>登录工作台</button>
          </form>
          <small>与旧语音体验访问码、云服务器密码不同。</small>
          {error && (
            <p role="alert" className="cw-error">
              {error}
            </p>
          )}
        </main>
      ) : (
        <>
          <nav className="cw-nav">
            <button
              className={page === "sessions" ? "selected" : ""}
              onClick={() => navigation("sessions")}
            >
              咨询记录
            </button>
            <button
              className={page === "speech" ? "selected" : ""}
              onClick={() => navigation("speech")}
            >
              语音配置 · 填写 Key
            </button>
            <button
              className={page === "line" ? "selected" : ""}
              onClick={() => navigation("line")}
            >
              电话线路
            </button>
            <Link href="/">原语音体验</Link>
          </nav>
          <main>
            {error && (
              <div className="cw-error" role="alert">
                {error}
              </div>
            )}
            {notice && (
              <div className="cw-notice" role="status">
                {notice}
              </div>
            )}
            {current?.template?.id===procurementId && ["chat","result"].includes(page) && <details><summary>本次采购项目需求（已保存）</summary>{Object.entries(projectFields).map(([key,label])=><p key={key}><strong>{label}：</strong>{current.template?.project?.[key] || "待确认"}</p>)}<small>项目需求不等于供应商承诺。语音模式的结构化字段在结束报告时统一核验提取。</small></details>}
            {page === "sessions" && (
              <>
                <div className="cw-heading">
                  <div>
                    <div className="cw-kicker">CONSULTATIONS</div>
                    <h1>每次沟通，都有据可查</h1>
                    <p>用语音或文字开展咨询，结束后获得报告与完整转录。</p>
                  </div>
                </div>
                <div className="cw-grid">
                  <section>
                    <h2>新建沟通任务</h2>
                    <label>业务模板<select value={businessTemplate} onChange={e=>setBusinessTemplate(e.target.value)}>
                      <option value={procurementId}>采购供应商沟通</option><option value="free-chat-v1">自由对话测试</option>
                    </select></label>
                    {businessTemplate===procurementId && <ProjectForm value={project} onChange={setProject} disabled={busy}/>}
                    <label>
                      咨询方式
                      <select
                        value={mode}
                        onChange={(e) =>
                          setMode(e.target.value as "text" | "voice")
                        }
                      >
                        <option value="voice">网页实时语音</option>
                        <option value="text">文字咨询</option>
                      </select>
                    </label>
                    {mode === "voice" && <label>语音路线
                      <select value={voiceRoute} onChange={(e) => setVoiceRoute(e.target.value)}>
                        <option value="pipeline">原路线 · ASR + DeepSeek + TTS</option>
                        <option value="pipeline-mimo">新路线 · 千问 ASR + DeepSeek + MiMo TTS</option>
                        <option value="pipeline-mimo-all">实验路线 · MiMo ASR + DeepSeek + MiMo TTS</option>
                        <option value="qwen-realtime">新路线 · Qwen 原生全双工（试用）</option>
                        <option value="doubao-realtime">新路线 · 豆包 Seeduplex 全双工（待验收）</option>
                        <option value="baidu-realtime">新路线 · 百度 Lite（请先说话）</option>
                      </select>
                    </label>}
                    <p>{businessTemplate===procurementId ? "顺着供应商回答自然追问，确认供货范围、能力与待办。语音请选择原路线或 Qwen 全双工。文字模式可先验证提问与信息采集。" : "自由选择话题，支持连续问答、插话和随时结束。"}</p>
                    {businessTemplate!==procurementId && <label>
                      咨询标题
                      <input
                        value={title}
                        maxLength={80}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </label>}
                    <div className="cw-disclaimer">
                      本次文字会保存在服务器用于生成报告，可在结果页删除；不保存通话录音。请勿填写无关个人隐私。供应商口述、技术与商务条件需要人工核验，AI 不代表采购批准。
                    </div>
                    <label className="cw-check">
                      <input
                        type="checkbox"
                        checked={consent}
                        onChange={(e) => setConsent(e.target.checked)}
                      />
                      我已了解并同意保存本次咨询文字
                    </label>
                    <button disabled={!consent || busy} onClick={start}>
                      {busy
                        ? "正在准备…"
                        : mode === "voice"
                          ? "创建语音咨询"
                          : "开始真实文字咨询"}
                    </button>
                    <small>{mode === "voice" && voiceRoute === "baidu-realtime" ? "百度 Lite 直接语音回答，请先说话；此版不应用咨询模板指令，可用结束按钮退出。" : mode === "voice" && voiceRoute === "doubao-realtime" ? "由豆包实时语音直接回答，请先在语音配置保存并测试豆包 Key。" : mode === "voice" && voiceRoute === "qwen-realtime" ? "由 Qwen 实时语音直接回答，使用已保存的千问 Key。" : "由 DeepSeek 生成回答，非预设回复。"}</small>
                  </section>
                  <section>
                    <h2>
                      历史咨询 <span className="cw-count">{list.length}</span>
                    </h2>
                    {!list.length ? (
                      <p className="cw-muted">
                        尚无咨询记录。完成第一轮后将在这里保留。
                      </p>
                    ) : (
                      <div className="cw-list">
                        {list.map((c) => (
                          <button
                            key={c.id}
                            onClick={() =>
                              run(async () => {
                                await load(c.id);
                              })
                            }
                          >
                            <strong>{c.title}</strong>
                            <span>
                              {new Date(c.created_at).toLocaleString()} ·{" "}
                              {c.status === "closed" ? "已结束" : "进行中"}
                            </span>
                            <small>
                              {c.report_status === "ready"
                                ? "报告已生成"
                                : c.status === "closed"
                                  ? "报告待处理"
                                  : "继续咨询"}{" "}
                              →
                            </small>
                          </button>
                        ))}
                      </div>
                    )}
                  </section>
                </div>
              </>
            )}
            {page === "chat" && current && (
              <>
                <div className="cw-heading">
                  <div>
                    <div className="cw-kicker">LIVE CONSULTATION</div>
                    <h1>{current.title}</h1>
                    {current.mode !== "text" && <small>{current.voice_route === "baidu-realtime" ? "百度 Lite 端到端语音" : current.voice_route === "pipeline-mimo-all" ? "MiMo ASR + DeepSeek + MiMo TTS" : current.voice_route === "pipeline-mimo" ? "千问 ASR + DeepSeek + MiMo TTS" : current.voice_route === "doubao-realtime" ? "豆包 Seeduplex 全双工" : current.voice_route === "qwen-realtime" ? "Qwen 原生全双工" : "ASR + DeepSeek + TTS"}</small>}
                    <p>
                      {current.mode === "text"
                        ? "文字咨询 · 按轮显示回复"
                        : current.mode === "phone"
                          ? "电话咨询 · 同步查看最终转录"
                          : "语音咨询 · 支持连续问答和插话打断"}
                    </p>
                  </div>
                  <button
                    className="cw-secondary"
                    disabled={busy || current.voice_state === "ending"}
                    onClick={() => send(true)}
                  >
                    结束咨询并生成报告
                  </button>
                </div>
                {current.mode === "voice" && (
                  <VoiceRoom
                    key={current.id}
                    id={current.id}
                    ending={current.voice_state === "ending"}
                  />
                )}
                {current.mode === "phone" && (
                  <section>
                    <p>
                      电话状态：
                      {(
                        {
                          submitting: "正在提交",
                          queued: "等待拨号",
                          dialing: "正在呼叫",
                          connected: "已接通",
                          uncertain: "结果待确认",
                          ended: "已挂断",
                          failed: "未接通",
                        } as Record<string, string>
                      )[current.phone_state || ""] || "正在同步"}
                    </p>
                    <p>
                      接听方无需网页操作，双方文字会自动显示；最长通话约 180
                      秒。
                    </p>
                    <button
                      className="cw-secondary"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await api("phone-reconcile", { id: current.id });
                          await load(current.id);
                        })
                      }
                    >
                      核对拨号状态
                    </button>
                    <button
                      className="cw-danger"
                      disabled={busy}
                      onClick={() => {
                        if (
                          confirm("立即挂断此通电话？可能无法播放完整结束语。")
                        )
                          void run(async () => {
                            await api("phone-hangup", { id: current.id });
                            setNotice("已请求挂断当前电话");
                          });
                      }}
                    >
                      立即挂断
                    </button>
                  </section>
                )}
                <div className="cw-chat-grid">
                  <section className="cw-chat">
                    <div className="cw-messages" role="log" aria-live="polite">
                      {current.messages.map((m) => (
                        <article key={m.id} className={"cw-bubble " + m.role}>
                          <small>
                            {m.role === "user" ? "你" : "AI 小禾"} ·{" "}
                            {new Date(m.created_at).toLocaleTimeString()}
                          </small>
                          <p>{m.text}</p>
                          {m.interrupted && <small>此回答被打断</small>}
                        </article>
                      ))}
                      {busy && <p className="cw-thinking">小禾正在整理回复…</p>}
                      {current.mode === "text" &&
                        !current.messages.length &&
                        !busy && (
                          <button
                            onClick={() =>
                              run(async () => {
                                setCurrent(
                                  await api("turn", {
                                    id: current.id,
                                    requestId: crypto.randomUUID(),
                                  }),
                                );
                              })
                            }
                          >
                            重新获取开场问候
                          </button>
                        )}
                    </div>
                    {current.mode === "text" && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void send();
                        }}
                        className="cw-compose"
                      >
                        <textarea
                          aria-label="咨询回复"
                          placeholder="说说你的实际情况，也可以输入“跳过”或“结束”…"
                          value={text}
                          maxLength={2000}
                          onChange={(e) => setText(e.target.value)}
                        />
                        <button disabled={busy || !text.trim()}>发送</button>
                      </form>
                    )}
                  </section>
                  <aside>
                    <section>
                      <h2>已了解的信息</h2>
                      {Object.entries(fields).map(([key, label]) => (
                        <div className="cw-fact" key={key}>
                          <small>{label}</small>
                          <p>{current.facts[key]?.value || "待了解"}</p>
                        </div>
                      ))}
                    </section>
                    <section>
                      <h2>待确认提醒</h2>
                      {current.risks.length ? (
                        current.risks.map((r, i) => <p key={i}>{r.text}</p>)
                      ) : (
                        <p className="cw-muted">
                          暂无。AI 摘要可能有误，请以原话为准。
                        </p>
                      )}
                    </section>
                  </aside>
                </div>
              </>
            )}
            {page === "result" && current && (
              <>
                <div className="cw-heading">
                  <div>
                    <div className="cw-kicker">CONSULTATION SUMMARY</div>
                    <h1>本次咨询已结束</h1>
                    <p>
                      {current.title} · {Math.floor(duration / 60)} 分{" "}
                      {duration % 60} 秒 ·{" "}
                      {current.mode === "text" ? "文字咨询" : "语音咨询"}
                      （包含连接和等待时间）
                    </p>
                  </div>
                  <button
                    className="cw-secondary"
                    onClick={() => navigation("sessions")}
                  >
                    返回咨询列表
                  </button>
                </div>
                <div className="cw-grid">
                  <section>
                    <h2>{current.template?.id === "free-chat-v1" ? "自由对话摘要" : "咨询报告"}</h2>
                    {current.report_status === "ready" && current.report ? (
                      <>
                        <p>{current.report.summary}</p>
                        <h3>已获取信息</h3>
                        {Object.entries(fields).map(([key, label]) => (
                          <p key={key}>
                            <strong>{label}：</strong>
                            {current.facts[key]?.value || "未确认"}
                          </p>
                        ))}
                        <h3>下一步</h3>
                        <ul>
                          {current.report.next_steps.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                        <div className="cw-disclaimer">
                          {current.report.limitations}
                        </div>
                        <a
                          className="cw-download"
                          href={
                            "/api/consult/export?id=" +
                            current.id +
                            "&kind=report"
                          }
                        >
                          下载报告 Markdown
                        </a>
                      </>
                    ) : (
                      <>
                        <p>
                          {busy
                            ? "正在根据真实转录生成报告…"
                            : "转录已保存，报告尚未完成。可重试生成。"}
                        </p>
                        <button
                          disabled={busy}
                          onClick={() => report(current.id)}
                        >
                          生成 / 重试报告
                        </button>
                      </>
                    )}
                  </section>
                  <section>
                    <h2>完整文字转录</h2>
                    <a
                      className="cw-download"
                      href={
                        "/api/consult/export?id=" +
                        current.id +
                        "&kind=transcript"
                      }
                    >
                      下载转录 Markdown
                    </a>
                    <div className="cw-transcript">
                      {current.messages.map((m) => (
                        <div key={m.id}>
                          <small>
                            {m.role === "user" ? "用户" : "AI 小禾"} ·{" "}
                            {new Date(m.created_at).toLocaleTimeString()}
                          </small>
                          <p>{m.text}</p>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>
                <details
                  onToggle={(e) => {
                    if (e.currentTarget.open)
                      api("events?id=" + current.id)
                        .then(setLogs)
                        .catch(() => {});
                  }}
                >
                  <summary>管理员：查看技术审计记录</summary>
                  <p className="cw-muted">
                    执行动作与依据，不是模型内部思维。对话内容不进入服务日志。
                  </p>
                  {logs.map((e) => (
                    <pre key={e.seq}>
                      {e.kind +
                        " · " +
                        new Date(e.created_at).toLocaleString() +
                        "\n" +
                        JSON.stringify(e.payload, null, 2)}
                    </pre>
                  ))}
                </details>
                <button
                  className="cw-danger"
                  disabled={busy}
                  onClick={() => {
                    if (
                      confirm(
                        "删除此咨询、转录、报告和会话事件？下载到你电脑的文件不会一并删除。",
                      )
                    )
                      void run(async () => {
                        await api("delete", { id: current.id });
                        setCurrent(null);
                        setPage("sessions");
                        await refreshList();
                      });
                  }}
                >
                  删除本次咨询数据
                </button>
              </>
            )}
            {page === "speech" && (
              <>
                <div className="cw-kicker">SPEECH SETTINGS</div>
                <h1>语音服务配置</h1>
                <DoubaoSettings />
                <h2>千问语音配置</h2>
                <p>
                  ASR 与 TTS 共用一个
                  Key。仅服务器保存加密凭据；保存后不回显，也不写入日志。
                </p>
                <div className="cw-grid">
                  <section>
                    <h2>填写与保存</h2>
                    <label>
                      北京业务空间 ID（默认入口留空）
                      <input
                        value={speech.workspace}
                        onChange={(e) =>
                          setSpeech({ ...speech, workspace: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      共用 API Key
                      <input
                        type="password"
                        autoComplete="off"
                        value={key}
                        placeholder={
                          speech.configured
                            ? "已配置 · 填写新 Key 可替换"
                            : "填写百炼 API Key"
                        }
                        onChange={(e) => setKey(e.target.value)}
                      />
                    </label>
                    <p className="cw-muted">
                      留空使用阿里云官方默认入口；指定北京业务空间时，Key
                      必须与该空间匹配。此配置用于下一次网页语音及电话咨询。
                    </p>
                    <button
                      disabled={busy || !key.trim()}
                      onClick={() =>
                        run(async () => {
                          await api("speech", {
                            key: key.trim(),
                            workspace: speech.workspace.trim(),
                          });
                          setKey("");
                          setSpeech(await api("speech"));
                          setAudio("");
                          setAsr("");
                          setNotice("已加密保存，请分别测试 ASR 和 TTS。");
                        })
                      }
                    >
                      保存共用 Key
                    </button>
                    <p>
                      {speech.configured
                        ? "● 已配置，明文不可读取"
                        : "○ 尚未配置"}
                    </p>
                  </section>
                  <section>
                    <h2>独立测试</h2>
                    <p>测试会调用真实模型并产生额度消耗，不会拨打电话。</p>
                    <h3>TTS 试听</h3>
                    <button
                      disabled={busy || !speech.configured}
                      onClick={() => test("tts")}
                    >
                      合成测试语音
                    </button>
                    {audio && <audio controls src={audio} />}
                    <small>
                      {speech.tts_test
                        ? speech.tts_test.ok
                          ? "最近测试成功"
                          : "最近测试失败"
                        : "尚未测试"}
                    </small>
                    <h3>录音 ASR</h3>
                    <input
                      aria-label="ASR 测试音频"
                      type="file"
                      accept="audio/*"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                    />
                    <p className="cw-muted">
                      上传 3–10 秒清晰中文语音，最大
                      5MB。只用于本次识别，不落盘保存。
                    </p>
                    <button
                      disabled={busy || !speech.configured || !file}
                      onClick={() => test("asr")}
                    >
                      识别上传语音
                    </button>
                    {asr && <blockquote>{asr}</blockquote>}
                    <small>
                      {speech.asr_test
                        ? speech.asr_test.ok
                          ? "最近录音识别成功"
                          : "最近测试失败"
                        : "尚未测试"}
                      ；实时 ASR 与电话链路需后续单独验收。
                    </small>
                  </section>
                </div>
              </>
            )}
            {page === "line" && <PhoneDial onStarted={load} />}
            {current && ["chat", "result"].includes(page) && (
              <Diagnostics
                id={current.id}
                closed={current.status === "closed"}
              />
            )}
          </main>
          <footer>
            咨询资料仅供授权业务使用 · 非医疗诊断 · AI 内容请结合原话核查
          </footer>
        </>
      )}
    </div>
  );
}
