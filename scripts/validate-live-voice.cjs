// Real browser/WebRTC/ASR/LLM/TTS validation. Test microphone uses known spoken audio.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'..');const out=path.join(root,'BigApple输出/voice-consultation-validation');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage({viewport:{width:1440,height:1000},permissions:['microphone']});
 let id;let finished=false;const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
   const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
   let context,destination;
   navigator.mediaDevices.getUserMedia=async constraints=>{
     if(!constraints.audio)return original(constraints);
     context??=new AudioContext({sampleRate:48000});destination??=context.createMediaStreamDestination();await context.resume();
     return destination.stream.clone();
   };
   window.__speak=async base64=>{
     await context.resume();const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
     const buffer=await context.decodeAudioData(bytes.buffer);const source=context.createBufferSource();source.buffer=buffer;source.connect(destination);source.start();
     return buffer.duration;
   };
 });
 async function get(route){return page.evaluate(async route=>{const r=await fetch('/api/consult/'+route);return r.json();},route);}
 async function waitUntil(check,timeout=90000){const start=Date.now();while(Date.now()-start<timeout){if(await check())return;await page.waitForTimeout(500);}throw Error('Timed out waiting for voice milestone');}
 async function speak(name){return page.evaluate(base64=>window.__speak(base64),fs.readFileSync(path.join(out,name+'.wav')).toString('base64'));}
 try{
   await page.goto('https://phone.hehaizhao.site/consult');
   const password=fs.readFileSync(path.join(root,'BigApple输出/consultation-access.txt'),'utf8').split('管理员密码：')[1].split('\n')[0];
   await page.getByLabel('工作台管理员密码').fill(password);await page.getByRole('button',{name:'登录工作台',exact:true}).click();
   await page.getByLabel('咨询标题').fill('真实语音链路验收 · 合成测试输入');
   await page.getByLabel('咨询方式').selectOption('voice');
   await page.getByRole('checkbox').check();
   const created=page.waitForResponse(r=>r.url().endsWith('/api/consult/create')&&r.request().method()==='POST');
   await page.getByRole('button',{name:'创建语音咨询',exact:true}).click();id=(await(await created).json()).id;
   await page.getByRole('button',{name:'连接麦克风并开始',exact:true}).click();
   await waitUntil(async()=>{const c=await get('session?id='+id);return c.messages?.some(m=>m.role==='assistant');});
   console.log('Opening received; publishing known speech through WebRTC.');
   await speak('answer');
   await waitUntil(async()=>{const c=await get('session?id='+id);return c.messages?.some(m=>m.role==='user');});
   await waitUntil(async()=>await page.getByRole('status').filter({hasText:'小禾正在回答'}).count()>0,45000);
   await speak('interrupt');
   await waitUntil(async()=>{const c=await get('session?id='+id);return c.messages?.filter(m=>m.role==='user').length>=2;});
   await waitUntil(async()=>{const c=await get('session?id='+id);return c.messages?.some(m=>m.interrupted);},30000);
   await page.screenshot({path:path.join(out,'conversation.png'),fullPage:true});
   console.log('Two spoken turns and interruption persisted; requesting graceful end.');
   await page.getByRole('button',{name:'结束咨询并生成报告',exact:true}).click();
   await waitUntil(async()=>{const c=await get('session?id='+id);return c.status==='closed'&&c.report_status==='ready';},120000);
   const c=await get('session?id='+id),events=await get('events?id='+id);
   const goodbye=events.find(e=>e.kind==='voice.farewell_played'),closed=events.find(e=>e.kind==='voice.closed');
   if(!goodbye||!closed||goodbye.seq>=closed.seq)throw Error('Farewell did not complete before archive');
   if(errors.length)throw Error(errors.join('\n'));
   for(const kind of ['report','transcript']){
     const content=await page.evaluate(async({id,kind})=>{const r=await fetch('/api/consult/export?id='+id+'&kind='+kind);if(!r.ok)throw Error('Export failed');return r.text();},{id,kind});
     fs.writeFileSync(path.join(out,kind+'.md'),content);
   }
   const result={passed:true,id,messages:c.messages.length,interruptions:c.messages.filter(m=>m.interrupted).length,reason:c.reason,report_status:c.report_status,events:events.length};
   fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
   await page.screenshot({path:path.join(out,'report.png'),fullPage:true});
   console.log(JSON.stringify(result));finished=true;
 }catch(e){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});console.error(e.message);if(id)console.error('Test session: '+id);process.exitCode=1;}
 finally{
   if(id&&!finished)await page.evaluate(async id=>fetch('/api/consult/voice-abort',{method:'POST',headers:{'Content-Type':'application/json','X-Consultation':'1'},body:JSON.stringify({id})}),id).catch(()=>{});
   await browser.close();
 }
})();
