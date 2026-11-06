"""Package verified public brochures and provenance; no credentials included."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'BigApple输出/采购知识库扩充'
OLD = ROOT / 'BigApple输出/采购知识库接入/演示资料'
DEST = OUT / 'official_pdf_v1'
DEST.mkdir(exist_ok=True)
sources = json.loads((OUT / 'sources.json').read_text(encoding='utf-8'))
for row in sources:
    row['file'] = row['model'] + '-厂商原版.pdf'
    shutil.copy2(OUT / row['file'], DEST / row['file'])
for row in json.loads((OLD / 'brochure-sources.json').read_text(encoding='utf-8')):
    shutil.copy2(OLD / row['file'], DEST / row['file'])
    sources.append({**row, 'model': row['file'].split('-')[0], 'pdf_url': row['url']})
for row in sources:
    assert hashlib.sha256((DEST / row['file']).read_bytes()).hexdigest() == row['sha256']
(DEST / 'sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
with zipfile.ZipFile(OUT / '采购设备-6型号官方PDF.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(DEST.iterdir()):
        archive.write(path, path.name)
print(f'{len(sources)} PDFs; {sum(r["pages"] for r in sources)} pages')
