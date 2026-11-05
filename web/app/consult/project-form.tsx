"use client";
import { projectFields } from "@/lib/procurement";
export default function ProjectForm({value,onChange,disabled=false}:{value:Record<string,string>;onChange:(v:Record<string,string>)=>void;disabled?:boolean}) {
  return <fieldset disabled={disabled}><legend>采购项目需求表</legend>
    <p>填写允许向供应商披露的内容，不填写内部预算底线或其他供应商的保密报价。未知参数写“待确认”。</p>
    {Object.entries(projectFields).map(([key,label])=><label key={key}>{label}{["project","scenario","outputs"].includes(key)?"（必填）":""}
      <textarea rows={2} maxLength={1200} value={value[key]||""} onChange={e=>onChange({...value,[key]:e.target.value})}/></label>)}
    <small>AI 只沟通与记录，不代您承诺订单、付款或成交。需求表随本次会话保存，不改变历史记录。</small>
  </fieldset>;
}
