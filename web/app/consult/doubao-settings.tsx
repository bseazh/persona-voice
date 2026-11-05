"use client";
import { useEffect, useState } from "react";

async function request(body?: unknown, test = false) {
  const response = await fetch('/api/consult/' + (test ? 'test-doubao' : 'doubao'), {
    method:body === undefined ? 'GET':'POST', cache:'no-store',
    headers:body === undefined ? {} : {'Content-Type':'application/json','X-Consultation':'1'},
    body:body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '请求失败');
  return data;
}
export default function DoubaoSettings() {
  const [key,setKey] = useState(''), [voice,setVoice] = useState('zh_male_xiaotian_jupiter_bigtts');
  const [configured,setConfigured] = useState(false), [tested,setTested] = useState(false);
  const [busy,setBusy] = useState(false), [message,setMessage] = useState(''), [audio,setAudio] = useState('');
  useEffect(()=>{request().then(s=>{setConfigured(s.configured);setVoice(s.voice);setTested(!!s.test?.ok);}).catch(e=>setMessage(e.message));},[]);
  async function act(test: boolean) {
    setBusy(true);setMessage('');
    try {
      if (test) {
        const result = await request({},true);
        setAudio('data:audio/wav;base64,'+result.audio);setTested(true);
        setMessage('连接与合成音频测试通过。请再进入豆包网页语音，验收真实识别、打断和结束。');
      } else {
        await request({key:key.trim(),voice});setKey('');setConfigured(true);setTested(false);setAudio('');
        setMessage('已加密保存到腾讯云服务器，不会替换千问 Key。请执行连接与音频测试。');
      }
    } catch(e) { setMessage(e instanceof Error ? e.message : '操作失败'); if(test)setTested(false); }
    finally {setBusy(false);}
  }
  return <section>
    <h2>豆包原生全双工 · Seeduplex</h2>
    <p>使用火山语音控制台的 API Key，需开通端到端实时语音 Seeduplex 服务。与千问配置独立。</p>
    <a href="https://console.volcengine.com/speech/new/setting/apikeys?projectName=default" target="_blank" rel="noreferrer">前往火山语音 API Key 管理</a>
    <label>豆包 API Key<input type="password" autoComplete="off" value={key} disabled={busy} onChange={e=>setKey(e.target.value)} placeholder={configured?'已保存，填写新 Key 可替换':'填写火山语音 API Key'}/></label>
    <label>音色<select value={voice} disabled={busy} onChange={e=>{setVoice(e.target.value);setMessage('更换音色请重新填写 Key 并保存。');}}>
      <option value="zh_male_xiaotian_jupiter_bigtts">小天</option><option value="zh_female_vv_jupiter_bigtts">Vivi</option>
    </select></label>
    <button disabled={busy || !key.trim()} onClick={()=>act(false)}>保存豆包 Key</button>
    <button disabled={busy || !configured || !!key.trim()} onClick={()=>act(true)}>测试连接与音频</button>
    <p>{configured?'已配置':'未配置'} · {tested?'最近连接与音频测试通过':'尚未通过连接与音频测试'}</p>
    <p>测试调用真实豆包服务，会消耗额度，不会拨打电话；不代表 ASR 或电话验收通过。密钥仅由服务器加密保存，不回显。</p>
    {message && <p role="status">{message}</p>}{audio && <audio controls src={audio}/>}
  </section>;
}
