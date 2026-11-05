// Archive a real completed procurement validation without overwriting earlier evidence.
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const id=process.argv[2];assert.match(id||'',/^[a-f0-9-]{36}$/);
 const root=path.resolve(__dirname,'..');const dir=path.join(root,'BigApple输出/采购模板验收',id);
 if(fs.existsSync(dir))throw Error('Archive already exists');
 const password=fs.readFileSync(path.join(root,'BigApple输出/consultation-access.txt'),'utf8').split('管理员密码：')[1].split('\n')[0].trim();
 const origin='https://phone.hehaizhao.site';const base=origin+'/api/consult/';
 const login=await fetch(base+'login',{method:'POST',headers:{Origin:origin,'X-Consultation':'1','Content-Type':'application/json'},body:JSON.stringify({password})});assert.ok(login.ok);
 const cookie=login.headers.getSetCookie().map(s=>s.split(';')[0]).join('; ');
 async function request(route,body){const r=await fetch(base+route,{method:body?'POST':'GET',headers:{Cookie:cookie,Origin:origin,'X-Consultation':'1','Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,`${route}: ${r.status}`);return r;}
 let session=await (await request('session?id='+id)).json();
 assert.equal(session.template.id,'procurement-screening-v1');assert.equal(session.status,'closed');
 if(session.report_status!=='ready')await request('report',{id});
 session=await (await request('session?id='+id)).json();assert.equal(session.report_status,'ready');
 const ids=new Set(session.messages.filter(m=>m.role==='user').map(m=>m.id));
 for(const fact of Object.values(session.facts))assert.ok(ids.has(fact.source));
 fs.mkdirSync(dir,{recursive:true});
 fs.writeFileSync(path.join(dir,'session.json'),JSON.stringify(session,null,2));
 for(const kind of ['report','transcript'])fs.writeFileSync(path.join(dir,kind+'.md'),await (await request('export?id='+id+'&kind='+kind)).text());
 await request('logout',{});console.log(dir);
})().catch(e=>{console.error(e.message);process.exitCode=1});
