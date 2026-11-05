// Real public text consultation with disclosed synthetic supplier replies; no phone call.
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const dir=path.join(root,'BigApple输出/采购模板验收');
fs.mkdirSync(dir,{recursive:true});const state=path.join(dir,'session.json');
(async()=>{
if(fs.existsSync(state))throw Error('Existing validation; inspect before retry');
const password=fs.readFileSync(path.join(root,'BigApple输出/consultation-access.txt'),'utf8').split('管理员密码：')[1].split('\n')[0].trim();
const base='https://phone.hehaizhao.site/api/consult/';
let r=await fetch(base+'login',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://phone.hehaizhao.site','X-Consultation':'1'},body:JSON.stringify({password})});assert.ok(r.ok);
const cookie=r.headers.getSetCookie().map(x=>x.split(';')[0]).join('; ');
async function api(route,body){const response=await fetch(base+route,{method:body?'POST':'GET',headers:{Cookie:cookie,'Content-Type':'application/json',Origin:'https://phone.hehaizhao.site','X-Consultation':'1'},body:body?JSON.stringify(body):undefined});if(!response.ok)throw Error(route+' '+response.status);return response.json();}
const project={project:'验收：生活垃圾分选设备沟通',supplier:'虚构供应商，仅用于验收',scenario:'生活垃圾分选，不进行塑料清洗造粒',capacity:'十五吨，单位待确认',outputs:'分出瓶子和薄膜',constraints:'先核实单机供货与整线责任，不承诺付款'};
const created=await api('create',{title:project.project,template:'procurement-screening-v1',project,mode:'text',consent:true});fs.writeFileSync(state,JSON.stringify(created));
const results=[];
for(const text of [null,'方便。我们主要做破碎机和滚筒筛，只供单机，整线需要您找集成商。','你们说的十五吨是每天还是每小时？我们报价前需要确认。','电机用我们长期合作的供应商，不是皖南，具体型号我稍后发配置清单。','项目案例客户名称不方便透露，可以提供脱敏供货清单。发货前希望付款九成，这只是我们的条件，还要双方谈。']){
let s=await api('turn',{id:created.id,requestId:crypto.randomUUID(),...(text?{text}:{})});results.push(s.messages.at(-1));console.log(s.messages.at(-1).text);
}
await api('turn',{id:created.id,requestId:crypto.randomUUID(),finish:true});
await api('report',{id:created.id});const s=await api('session?id='+created.id);
assert.equal(s.status,'closed');assert.equal(s.report_status,'ready');assert.equal(s.template.id,'procurement-screening-v1');
assert.ok(!Object.keys(s.facts).some(k=>['schedule','onset','habits'].includes(k)));
const ids=new Set(s.messages.filter(m=>m.role==='user').map(m=>m.id));for(const f of Object.values(s.facts))assert.ok(ids.has(f.source));
for(const kind of ['report','transcript']){let r=await fetch(base+'export?id='+created.id+'&kind='+kind,{headers:{Cookie:cookie}});assert.ok(r.ok);let text=await r.text();assert.ok(!text.includes('睡眠调研报告'));fs.writeFileSync(path.join(dir,kind+'.md'),text);}
fs.writeFileSync(path.join(dir,'result.json'),JSON.stringify({test_data:'synthetic_supplier_real_LLM',session:s,results},null,2));console.log('Validated',created.id);
})().catch(e=>{console.error(e.message);process.exitCode=1});
