"""Download official linked brochures; keep URLs, hashes and extracted text for QA."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'BigApple输出/采购知识库接入/演示资料'
sources=[('TSS390-厂商原版-2026.pdf','https://www.terex.com/docs/librariesprovider6/default-document-library/tss-390_brochure_en_2026_web.pdf?sfvrsn=f2a09242_1'),
         ('Phoenix2100-厂商原版.pdf','https://www.terex.com/docs/librariesprovider6/default-document-library/phoenix-2100.pdf?sfvrsn=c04e48d0_2')]
results=[]
for name,url in sources:
    target=OUT/name
    if not target.exists():
        command=shlex.join(['curl','--fail','-L','--max-time','50','--retry','1','-sS',url])
        data=subprocess.run(['sshpass','-e','ssh','ubuntu@134.175.154.244',command],capture_output=True,check=True,timeout=115).stdout
        if not data.startswith(b'%PDF'):raise ValueError('Not a PDF')
        target.write_bytes(data)
    reader=PdfReader(target)
    text='\n'.join(f'## 第 {i+1} 页\n{p.extract_text()}' for i,p in enumerate(reader.pages))
    (OUT/(name+'.md')).write_text(f'# 厂商公开手册：{name}\n\n来源：{url}\n\n公开演示参考；非录音供应商能力证明、非采购批准配置。英文原版以厂商最新确认文件为准。\n\n'+text,encoding='utf-8')
    results.append({'file':name,'url':url,'pages':len(reader.pages),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    print(name,len(reader.pages),'pages',flush=True)
(OUT/'brochure-sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
