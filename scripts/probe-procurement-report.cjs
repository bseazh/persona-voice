// Real DeepSeek regression against an existing local transcript; no session mutation.
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('../web/node_modules/typescript');
const root=path.resolve(__dirname,'..');
const context={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root,'web/lib/procurement.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
const p=context.exports;
(async()=>{
  const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8')).session;
  const output=path.join(root,'BigApple输出/采购知识库接入');
  fs.mkdirSync(output,{recursive:true});
  fs.writeFileSync(path.join(output,'procurement-business-instructions.txt'),p.procurementInstructions(input.template.project),{mode:0o600});
  if(!process.env.DEEPSEEK_API_KEY)throw Error('Missing server-side DeepSeek key');
  const response=await fetch('https://api.deepseek.com/v1/chat/completions',{
    method:'POST',headers:{Authorization:`Bearer ${process.env.DEEPSEEK_API_KEY}`,'Content-Type':'application/json'},
    body:JSON.stringify({model:process.env.LLM_MODEL || 'deepseek-chat',max_tokens:3000,temperature:0.3,response_format:{type:'json_object'},messages:[
      {role:'system',content:p.procurementReportPrompt},
      {role:'user',content:JSON.stringify({project:input.template.project,messages:input.messages})}
    ]}),signal:AbortSignal.timeout(60000)
  });
  if(!response.ok)throw Error('DeepSeek HTTP '+response.status);
  const result=await response.json();
  const raw=JSON.parse(result.choices[0].message.content);
  fs.writeFileSync(path.join(output,'procurement-report-last-raw.json'),JSON.stringify(raw,null,2),{mode:0o600});
  const report=p.groundedProcurementReport(raw,input.template.project,input.messages);
  const filename=path.join(output,`procurement-report-regression-${Date.now()}.json`);
  fs.writeFileSync(filename,JSON.stringify({input_session:input.id,raw,report,usage:result.usage},null,2),{mode:0o600});
  console.log(JSON.stringify(report,null,2));console.log(filename);
})().catch(e=>{console.error(e.message);process.exitCode=1;});
