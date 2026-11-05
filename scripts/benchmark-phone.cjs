// One explicitly requested call per invocation. Never retry with a new request ID.
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const base = 'https://phone.hehaizhao.site/api/consult/';
const stage = process.argv[2];
const repeat = process.argv[3];
const voiceRoute = process.argv[4] || 'pipeline';
if (!['pipeline','qwen-realtime','doubao-realtime'].includes(voiceRoute)) throw Error('Unknown voice route');
if (!/^[a-z0-9-]+$/.test(stage || '') || !/^[12]$/.test(repeat || '')) throw Error('Usage: node scripts/benchmark-phone.cjs baseline 1');
(async () => {
  const dir = path.join(root, 'BigApple输出', 'latency-benchmark');
  fs.mkdirSync(dir, {recursive:true, mode:0o700});
  const prefix = path.join(dir, `${stage}-${repeat}`);
  const revision = execFileSync('git', ['rev-parse', 'HEAD'], {cwd:root, encoding:'utf8'}).trim();
  if (fs.existsSync(prefix+'.request.json')) throw Error('Attempt already exists: inspect it; do not redial');
  const password = fs.readFileSync(path.join(root,'BigApple输出/consultation-access.txt'),'utf8').split('管理员密码：')[1].split('\n')[0].trim();
  const login = await fetch(base+'login', {method:'POST',headers:{'Content-Type':'application/json',Origin:'https://phone.hehaizhao.site','X-Consultation':'1'},body:JSON.stringify({password})});
  if (!login.ok) throw Error('Login failed '+login.status);
  const cookie = login.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
  async function api(route, body) {
    const r=await fetch(base+route,{method:body?'POST':'GET',headers:{Cookie:cookie,'Content-Type':'application/json',Origin:'https://phone.hehaizhao.site','X-Consultation':'1'},body:body?JSON.stringify(body):undefined});
    if(!r.ok)throw Error(route+' status '+r.status);
    return r.json();
  }
  const line=await api('line?route='+voiceRoute);
  console.log(JSON.stringify({ready:line.dial_enabled,checks:line.checks}));
  if(!line.dial_enabled)throw Error('Line unavailable; no call made');
  if(line.caller!=='13660199577' || line.recipient!=='19221659824')throw Error('Configured phone pair changed; inspect before dialing');
  const request={requestId:crypto.randomUUID(),number:line.recipient,sim:2,template:'free-chat-v1',consent:true,voiceRoute,title:`时延测试 ${stage} 第${repeat}通`};
  fs.writeFileSync(prefix+'.request.json',JSON.stringify({stage,repeat,request,at:new Date().toISOString()},null,2),{mode:0o600,flag:'wx'});
  const result=await api('phone-dial',request);
  console.log('Submitted '+result.id);
  let last='';
  for(let i=0;i<55;i++) {
    const s=await api('session?id='+result.id);
    const status=JSON.stringify({status:s.status,phone:s.phone_state,messages:s.messages?.length,reason:s.reason});
    if(status!==last){console.log(status);last=status;}
    if(s.status==='closed') {
      await new Promise(r=>setTimeout(r,3000));
      const events=await api('events?id='+result.id);
      fs.writeFileSync(prefix+'.json',JSON.stringify({stage,repeat,revision,id:result.id,session:s,events},null,2),{mode:0o600});
      console.log('Saved '+prefix+'.json');return;
    }
    await new Promise(r=>setTimeout(r,5000));
  }
  throw Error('Observation timed out; inspect existing ID before further action');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
