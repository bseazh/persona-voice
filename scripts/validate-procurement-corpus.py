"""Exercise the real production retrieval adapter against six brochure models."""
import asyncio
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'services/agent'))
from procurement_knowledge import ProcurementKnowledge

CASES = [
    ('Phoenix 1600', '筛筒长度和直径', ['4.9', '1.54']),
    ('Phoenix 2100', '筛筒长度和直径', ['6.45', '1.94']),
    ('Phoenix 3300', '筛筒长度和直径', ['9.31', '2.32']),
    ('TSS 390', '轴长与发动机功率', ['3000', '368']),
    ('TDS 820', '轴长与不同地区发动机功率', ['2000', '331', '371']),
    ('TDS 825', '轴长与发动机功率', ['2500', '566']),
]

async def main():
    client = ProcurementKnowledge()
    results = []
    for model, question, expected in CASES:
        started = time.monotonic()
        result = await client.search(f'{model} {question}')
        matching = [r for r in result.get('results', []) if model.replace(' ', '').lower() in r['content'].replace(' ', '').lower()]
        content = '\n'.join(r['content'] for r in matching).replace(',', '')
        passed = bool(matching) and all(value in content for value in expected)
        entry = {'model': model, 'question': question, 'expected': expected, 'passed': passed,
                 'elapsed_ms': round((time.monotonic() - started) * 1000), 'response': result}
        results.append(entry)
        print(json.dumps({k: v for k, v in entry.items() if k != 'response'}, ensure_ascii=False), flush=True)
    target = ROOT / 'BigApple输出/采购知识库扩充/retrieval-validation.json'
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    if not all(r['passed'] for r in results):
        raise SystemExit(1)

if __name__ == '__main__':
    asyncio.run(main())
