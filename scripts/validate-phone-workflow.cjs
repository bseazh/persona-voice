// Public UI validation; --dial makes ONE authorized call to the existing test recipient.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),out=path.join(root,'BigApple输出/phone-workflow-validation');
fs.mkdirSync(out,{recursive:true,mode:0o700});
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let id;
 async function api(route,body){return page.evaluate(async({route,body})=>{const r=await fetch('/api/consult/'+route,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Consultation':'1'}:{},body:body?JSON.stringify(body):undefined});return{status:r.status,data:await r.json()};},{route,body});}
 try {
  await page.goto('https://phone.hehaizhao.site/consult');
  if((await api('line')).status!==401)throw Error('Anonymous line access not rejected');
  const password=fs.readFileSync(path.join(root,'BigApple输出/consultation-access.txt'),'utf8').split('管理员密码：')[1].split('\n')[0];
  await page.getByLabel('工作台管理员密码').fill(password);await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  await page.getByRole('button',{name:'电话线路',exact:true}).click();
  await page.getByRole('heading',{name:'拨打咨询电话',exact:true}).waitFor();
  await page.getByText('私有拨号服务',{exact:false}).first().waitFor();
  await page.screenshot({path:path.join(out,'preflight.png'),fullPage:true});
  const line=(await api('line')).data;
  console.log(JSON.stringify({phase:'preflight',ready:line.dial_enabled,checks:line.checks.map(c=>({id:c.id,ok:c.ok}))}));
  const bad=await api('phone-dial',{requestId:crypto.randomUUID(),number:'13660199577',sim:1,template:'sleep-v1',consent:true});
  if(bad.status!==400)throw Error('Wrong SIM was not rejected');
  if(process.argv.includes('--dial')) {
   if(!line.dial_enabled)throw Error('Line not ready; no call made');
   await page.getByLabel('接听号码',{exact:true}).fill('13660199577');
   await page.getByLabel('咨询标题',{exact:true}).fill('公网拨号流程验收');
   await page.getByRole('checkbox').check();
   page.once('dialog',dialog=>dialog.accept());
   const submitted=page.waitForResponse(r=>r.url().endsWith('/api/consult/phone-dial')&&r.request().method()==='POST');
   await page.getByRole('button',{name:'拨打并进入实时对话',exact:true}).click();
   const response=await submitted,payload=response.request().postDataJSON();
   id=(await response.json()).id;if(!id)throw Error('No consultation ID');
   const repeated=await api('phone-dial',payload);
   if(repeated.data.id!==id)throw Error('Idempotent replay mismatch');
   console.log('Dial submitted; duplicate request returned same session: '+id);
   const started=Date.now();let c;
   while(Date.now()-started<260000){
    c=(await api('session?id='+id)).data;
    if(c.status==='closed'&&c.report_status==='ready')break;
    await page.waitForTimeout(3000);
   }
   if(c.status!=='closed')throw Error('Call not archived before timeout; inspect without redialing');
   const events=(await api('events?id='+id)).data;
   const result={id,status:c.status,reason:c.reason,report_status:c.report_status,room:c.room_name,messages:c.messages.length,phone_events:events.filter(e=>e.kind.startsWith('phone.')).map(e=>({kind:e.kind,state:e.payload.state})),errors};
   fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result));
   await page.screenshot({path:path.join(out,'archive.png'),fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
