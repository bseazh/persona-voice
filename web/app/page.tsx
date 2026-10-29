'use client';

import { useEffect, useState } from 'react';
import { Activity, CheckCircle2, Clock3, PhoneCall, ShieldCheck } from 'lucide-react';

type Call = { id: string; phone_masked: string; status: string; mode: string; created_at: string; result?: { summary: string } };
const terminal = new Set(['completed', 'failed', 'busy', 'no_answer', 'declined', 'canceled', 'timed_out']);

export default function Home() {
  const [phone, setPhone] = useState('+8613800000000');
  const [goal, setGoal] = useState('询问明天下午三点是否可以安排两个人，并复述确认，但不执行真实预约。');
  const [calls, setCalls] = useState<Call[]>([]);
  const [active, setActive] = useState<Call | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function loadCalls() {
    const res = await fetch('/api/calls');
    if (res.ok) setCalls((await res.json()).items);
  }
  useEffect(() => { loadCalls(); }, []);
  useEffect(() => {
    if (!active || terminal.has(active.status)) return;
    const timer = setInterval(async () => {
      const res = await fetch(`/api/calls/${active.id}`);
      if (res.ok) {
        const next = await res.json();
        setActive(next);
        if (terminal.has(next.status)) { setBusy(false); loadCalls(); }
      }
    }, 700);
    return () => clearInterval(timer);
  }, [active]);

  async function start() {
    setBusy(true); setError('');
    const res = await fetch('/api/calls', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ phone_number: phone, task: { goal, language: 'zh-CN', questions: ['明天下午是否有时间？', '是否可以两个人？'], required_slots: ['available_time', 'party_size_supported'] }, mode: 'mock' }) });
    const body = await res.json();
    if (!res.ok) { setError(body.detail || '请求失败'); setBusy(false); return; }
    const detail = await fetch(body.status_url).then(r => r.json());
    setActive(detail); loadCalls();
  }

  return <main>
    <header><div className="brand"><span className="mark"><PhoneCall size={19}/></span><span>Persona Voice</span></div><div className="environment"><span></span> Mock 环境</div></header>
    <section className="workspace">
      <div className="intro"><div><p className="eyebrow">AI 外呼工作台</p><h1>发起一次可追踪的电话任务</h1><p className="sub">当前服务器仅运行模拟链路，不会拨打真实号码或产生电话费用。</p></div><div className="safety"><ShieldCheck size={20}/><div><strong>真实外呼已锁定</strong><small>需完成 SIP 与白名单配置后单独启用</small></div></div></div>
      <div className="grid">
        <section className="panel form-panel"><div className="panel-title"><h2>新建任务</h2><span>MOCK</span></div><label>目标号码 <small>E.164 格式</small></label><input value={phone} onChange={e => setPhone(e.target.value)} placeholder="+8613800000000"/><label>任务目标 <small>{goal.length}/1000</small></label><textarea value={goal} onChange={e => setGoal(e.target.value)} maxLength={1000}/>{error && <p className="error">{error}</p>}<button onClick={start} disabled={busy || !phone || !goal}><PhoneCall size={17}/>{busy ? '任务进行中' : '开始模拟通话'}</button></section>
        <section className="panel status-panel"><div className="panel-title"><h2>当前状态</h2><Activity size={18}/></div>{active ? <div className="active"><div className={`status-icon ${active.status === 'completed' ? 'done' : ''}`}>{active.status === 'completed' ? <CheckCircle2/> : <Clock3/>}</div><p className="status-name">{active.status}</p><p className="call-id">{active.id}</p><div className="steps">{['queued','dispatching','dialing','connected','completed'].map(step => <span key={step} className={step === active.status || active.status === 'completed' ? 'on' : ''}>{step}</span>)}</div>{active.result && <div className="result">{active.result.summary}</div>}</div> : <div className="empty"><PhoneCall size={28}/><p>尚未发起任务</p><small>状态事件将在这里实时更新</small></div>}</section>
      </div>
      <section className="history"><div className="section-heading"><div><p className="eyebrow">RECENT ACTIVITY</p><h2>最近任务</h2></div><span>{calls.length} 条记录</span></div><div className="table"><div className="row head"><span>创建时间</span><span>号码</span><span>模式</span><span>状态</span></div>{calls.map(call => <div className="row" key={call.id}><span>{new Date(call.created_at).toLocaleString('zh-CN')}</span><span>{call.phone_masked}</span><span>{call.mode}</span><span className={`badge ${call.status}`}>{call.status}</span></div>)}{calls.length === 0 && <div className="no-rows">暂无历史记录</div>}</div></section>
    </section>
  </main>;
}

