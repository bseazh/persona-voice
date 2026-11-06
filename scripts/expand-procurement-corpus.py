"""Fetch manufacturer-linked PDFs for distinct comparable equipment models."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'BigApple输出/采购知识库扩充'
PAGES={
 'Phoenix1600':'https://www.terex.com/ecotec/en/products/screening/trommel-screens/trommel-screens/phoenix-1600-trommel-screener',
 'Phoenix3300':'https://www.terex.com/ecotec/en/products/screening/trommel-screens/trommel-screens/phoenix-3300-trommel-screener',
 'TDS820':'https://www.terex.com/ecotec/en/products/shredding/slow-speed-shredders/slow-speed-shredder/tds-820',
 'TDS825':'https://www.terex.com/ecotec/en/products/shredding/slow-speed-shredders/slow-speed-shredder/tds-825-pre-shredder',
}
def fetch(url):
    cmd=shlex.join(['curl','--fail','-L','--max-time','35','--retry','1','-sS',url])
    return subprocess.run(['sshpass','-e','ssh','ubuntu@134.175.154.244',cmd],capture_output=True,check=True,timeout=85).stdout
def one(item):
    model,page=item
    html=OUT/(model+'.html')
    if not html.exists():html.write_bytes(fetch(page))
    soup=BeautifulSoup(html.read_bytes(),'html.parser')
    links=[urljoin(page,a['href']) for a in soup.select('a[href]') if '.pdf' in a['href'].lower()]
    if not links:raise ValueError(f'No manufacturer PDF: {model}')
    matching=[u for u in links if model.lower() in u.lower().replace('-','').replace('_','')]
    if not matching:raise ValueError(f'No model-matched PDF: {model}: {links}')
    url=matching[0];pdf=OUT/(model+'-厂商原版.pdf')
    if not pdf.exists():
        data=fetch(url)
        if not data.startswith(b'%PDF'):raise ValueError('Not a PDF')
        pdf.write_bytes(data)
    reader=PdfReader(pdf)
    text='\n\n'.join(f'## PDF 第 {i+1} 页\n{p.extract_text()}' for i,p in enumerate(reader.pages))
    if len(text)<500:raise ValueError('OCR required: '+model)
    (OUT/(model+'-原文.md')).write_text(f'# {model} 官方原版资料\n来源：{url}\n产品页：{page}\n公开参考，非采购批准规格；版本以原文为准。\n\n'+text,encoding='utf-8')
    result={'model':model,'page_url':page,'pdf_url':url,'pages':len(reader.pages),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'retrieved_at':datetime.now(timezone.utc).isoformat()}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(one,PAGES.items()))
    (OUT/'sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
