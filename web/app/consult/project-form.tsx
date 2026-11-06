"use client";
import { projectFields, procurementDemo } from "@/lib/procurement";
export default function ProjectForm({value,onChange,disabled=false}:{value:Record<string,string>;onChange:(v:Record<string,string>)=>void;disabled?:boolean}) {
  return <fieldset disabled={disabled}><legend>采购项目需求表</legend>
    <p>Demo 阶段可全部留空，直接使用生活垃圾分选示例。填写部分信息时，其余项目保持未知。仅填写允许向供应商披露的内容。</p>
    <button type="button" onClick={()=>onChange({...procurementDemo})}>填入演示背景</button>
    {Object.entries(projectFields).map(([key,label])=><label key={key}>{label}（选填）
      <textarea rows={2} maxLength={1200} value={value[key]||""} onChange={e=>onChange({...value,[key]:e.target.value})}/></label>)}
    <small>AI 只沟通与记录，不代您承诺订单、付款或成交。需求表随本次会话保存，不改变历史记录。</small>
  </fieldset>;
}
