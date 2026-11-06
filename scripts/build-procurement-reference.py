"""Download official product pages, retain provenance, create searchable demo PDFs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'BigApple输出/采购知识库接入/演示资料'
SOURCES=[
 ('01-滚筒筛-Phoenix2100','滚筒筛公开产品参考','https://www.terex.com/ecotec/en/products/screening/trommel-screens/trommel-screens/phoenix-2100-trommel-screener','确认筛筒尺寸、筛孔、适用物料和含水率；不能把该型号参数当成当前供应商承诺。'),
 ('02-单轴破碎机-TSS390','单轴破碎机公开产品参考','https://www.terex.com/ecotec/en/products/shredding/slow-speed-shredders/slow-speed-shredder/tss-390-tracked-single-shaft-shredder','确认转子、刀具、电机或动力形式、产能工况与出料要求；不能用公开产品推导本项目选型。'),
 ('03-混合垃圾处理','混合垃圾处理场景公开参考','https://www.terex.com/ecotec/en/sitemap-links/applications/mixed-waste','确认混合物成分、瓶子和薄膜形态、前处理和分选目标；采购方十五吨的单位仍待内部确认。'),
]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--via-server',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    style=ParagraphStyle('body',fontName='STSong-Light',fontSize=10,leading=16,spaceAfter=8,wordWrap='CJK')
    title=ParagraphStyle('title',parent=style,fontSize=20,leading=28,textColor=colors.HexColor('#183c50'))
    metadata=[]
    for name,heading,url,questions in SOURCES:
        raw=OUT/(name+'.html')
        if not raw.exists():
            command=['curl','--fail','-L','--max-time','35','--retry','1','-sS',url]
            if args.via_server:
                import shlex
                command=['sshpass','-e','ssh','ubuntu@134.175.154.244',shlex.join(command)]
            data=subprocess.run(command,capture_output=True,check=True,timeout=90).stdout
            soup=BeautifulSoup(data,'html.parser')
            if not soup.title or 'Ecotec' not in soup.title.get_text():raise ValueError('Unexpected page')
            raw.write_bytes(data)
        soup=BeautifulSoup(raw.read_bytes(),'html.parser')
        for element in soup(['script','style','nav','header','footer']):element.decompose()
        body=soup.find('main') or soup.body
        lines=[x.strip() for x in body.get_text('\n',strip=True).splitlines() if x.strip()]
        text='\n'.join(lines)
        if len(text)<300:raise ValueError('Insufficient source content')
        fetched=datetime.now(timezone.utc).isoformat()
        notice='演示参考资料｜根据公开厂商网页整理，非厂家原版手册。与录音供应商无已核实关联，不是批准采购规格、报价或能力证明。产品版本以厂商确认文件为准。原文保留英文以避免翻译参数失真。'
        md=f'# {heading}\n\n{notice}\n\n来源：{url}\n\n获取时间：{fetched}\n\n采购追问建议（本项目整理，非厂商原话）：{questions}\n\n## 官网原文提取\n\n{text}\n'
        (OUT/(name+'.md')).write_text(md,encoding='utf-8')
        story=[Paragraph(escape(heading),title),Spacer(1,12)]
        for line in [notice,'来源：'+url,'获取时间：'+fetched,'采购追问建议（整理）：'+questions,'官网原文提取']+lines:
            story.append(Paragraph(escape(line),style))
        pdf=OUT/(name+'.pdf')
        def footer(canvas,doc):
            canvas.setFont('STSong-Light',8);canvas.drawString(42,24,f'公开参考 · 采购演示 · {doc.page}')
        SimpleDocTemplate(str(pdf),title=heading,author='Persona Voice · 公开资料整理',leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer)
        reader=PdfReader(pdf)
        extracted=''.join(p.extract_text() for p in reader.pages)
        if heading not in extracted:raise ValueError('PDF text verification failed')
        metadata.append({'name':name,'url':url,'downloaded_at':fetched,'source_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'pages':len(reader.pages),'chars':len(extracted)})
        print(name,len(reader.pages),'pages',flush=True)
    (OUT/'sources.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
