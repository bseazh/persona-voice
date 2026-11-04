"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import VoiceRoom from "./voice-room";
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
  created_at: string;
  ended_at?: string;
  reason?: string;
  report_status: string;
  messages: Message[];
  facts: Record<string, { value: string; source: string }>;
  risks: { text: string; source: string }[];
  report?: { summary: string; next_steps: string[]; limitations: string };
  lease_until?: string;
};
type Speech = {
  configured: boolean;
  workspace: string;
  asr_test?: { ok: boolean; at: string };
  tts_test?: { ok: boolean; at: string };
};
type Line = {
  caller: string;
  recipient: string;
  sim: number;
  online: boolean;
  busy: boolean;
  status_available: boolean;
  reason: string;
};
const fields: Record<string, string> = {
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
    [title, setTitle] = useState("睡眠与生活习惯咨询"),
    [consent, setConsent] = useState(false);
  const [speech, setSpeech] = useState<Speech>({
      configured: false,
      workspace: "llm-w115702gcv6zwvwy",
    }),
    [key, setKey] = useState(""),
    [audio, setAudio] = useState(""),
    [asr, setAsr] = useState(""),
    [line, setLine] = useState<Line | null>(null);
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
      const c = await api("create", { title, consent, mode });
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
      if (next === "line") setLine(await api("line"));
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
        <span className="cw-tag">实时语音 / 文字 · 睡眠调研</span>
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
                    <h2>新建睡眠调研</h2>
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
                    <p>
                      了解作息、入睡、白天状态及生活习惯。AI
                      每次聚焦一个问题，支持跳过或随时结束。
                    </p>
                    <label>
                      咨询标题
                      <input
                        value={title}
                        maxLength={80}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </label>
                    <div className="cw-disclaimer">
                      本服务是生活习惯调研，不是医疗诊断或治疗。请勿输入身份证、住址等身份信息。文字会保存在服务器用于生成报告，可在结果页删除；不会录音。明显不适请寻求专业医疗帮助。
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
                    <small>由 DeepSeek 生成回答，非预设回复。</small>
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
                    <h2>睡眠调研报告</h2>
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
                <h1>千问语音配置</h1>
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
                      必须与该空间匹配。此配置用于工作台测试，尚不启用手机通话。
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
            {page === "line" && (
              <>
                <div className="cw-kicker">PHONE LINE</div>
                <h1>电话线路</h1>
                <p>先保存线路偏好。本阶段不下发手机控制命令，不开放拨号。</p>
                {line && (
                  <div className="cw-grid">
                    <section>
                      <h2>当前网关</h2>
                      <p className="cw-status">
                        {!line.status_available
                          ? "状态暂不可用"
                          : line.online
                            ? "● SIP 已注册"
                            : "○ SIP 未注册"}
                      </p>
                      <p>{line.busy ? "当前有通话" : "当前无电话通道"}</p>
                      <small>
                        注册成功不代表 Shizuku、SIM、音频与模型均已通过检查。
                      </small>
                      <button
                        className="cw-secondary"
                        onClick={() => navigation("line")}
                      >
                        刷新状态
                      </button>
                    </section>
                    <section>
                      <h2>线路偏好</h2>
                      <label>
                        主叫号码备注
                        <input
                          value={line.caller}
                          onChange={(e) =>
                            setLine({ ...line, caller: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        测试接听号码
                        <input
                          value={line.recipient}
                          onChange={(e) =>
                            setLine({ ...line, recipient: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        计划使用 SIM
                        <select
                          value={line.sim}
                          onChange={(e) =>
                            setLine({ ...line, sim: Number(e.target.value) })
                          }
                        >
                          <option value={1}>SIM 1</option>
                          <option value={2}>SIM 2</option>
                        </select>
                      </label>
                      <small>
                        主叫号码由实体 SIM
                        决定。此处不会更改实际卡槽或网关白名单。
                      </small>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            const r = await api("line", {
                              caller: line.caller,
                              recipient: line.recipient,
                              sim: line.sim,
                            });
                            setNotice(r.notice);
                          })
                        }
                      >
                        保存线路偏好
                      </button>
                      <button disabled>拨打电话（尚未开放）</button>
                      <p>{line.reason}</p>
                    </section>
                  </div>
                )}
              </>
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
