"""Render the reviewed, source-cited RAG demo corpus into a matching PDF."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak, Spacer
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'BigApple输出/采购知识库接入/采购演示知识资料.pdf'
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
body=ParagraphStyle('body',fontName='STSong-Light',fontSize=10,leading=16,spaceAfter=7,wordWrap='CJK')
title=ParagraphStyle('title',parent=body,fontSize=17,leading=24,textColor=colors.HexColor('#183c50'),spaceAfter=16)
heading=ParagraphStyle('heading',parent=body,fontSize=12,leading=18,textColor=colors.HexColor('#183c50'),spaceBefore=7)
story=[]
for i,source in enumerate(sorted((ROOT/'knowledge/procurement-demo').glob('*.md'))):
    if i:story.append(PageBreak())
    for line in source.read_text(encoding='utf-8').splitlines():
        if not line:continue
        style=title if line.startswith('# ') else heading if line.startswith('## ') else body
        clean=line.lstrip('# ').replace('\u00a0',' ').replace('–','-')
        story.append(Paragraph(escape(clean),style))
def footer(canvas,doc):
    canvas.setFont('STSong-Light',8);canvas.drawString(40,24,f'采购演示 / 公开资料参考 / 2026-11-06 / 第 {doc.page} 页')
SimpleDocTemplate(str(out),title='采购演示知识资料',leftMargin=40,rightMargin=40,topMargin=40,bottomMargin=40).build(story,onFirstPage=footer,onLaterPages=footer)
reader=PdfReader(out)
assert all(page.extract_text().strip() for page in reader.pages)
assert '368' in ''.join(p.extract_text() for p in reader.pages)
print(out,len(reader.pages),'pages')
