"""Publish one reviewed Markdown test result with a session-ID deduplication key."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('issue',type=int)
parser.add_argument('session_id')
parser.add_argument('report',type=Path)
parser.add_argument('--entry',choices=('result','summary','correction','plan','verification'),default='result')
args=parser.parse_args()
assert re.fullmatch(r'[0-9a-f-]{36}',args.session_id)
spec=importlib.util.spec_from_file_location('publisher',Path(__file__).with_name('publish-latency-issues.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
token=subprocess.check_output(['gh','auth','token'],text=True).strip()
def api(path,body=None):
    cmd=(['sshpass','-e'] if os.getenv('SSHPASS') else [])+['ssh','ubuntu@134.175.154.244','python3 -c '+shlex.quote(module.REMOTE)]
    p=subprocess.run(cmd,input=json.dumps({'token':token,'path':path,'body':body,'method':'GET' if body is None else 'POST'}),capture_output=True,text=True)
    if p.returncode:raise RuntimeError('Publish uncertain; inspect comments before retry')
    return json.loads(p.stdout)
marker='<!-- latency-session:'+args.session_id+('' if args.entry=='result' else ':'+args.entry)+' -->'
for page in range(1,101):
    comments=api(f'issues/{args.issue}/comments?per_page=100&page={page}')
    existing=next((c for c in comments if marker in c['body']),None)
    if existing:
        print(existing['html_url']);raise SystemExit(0)
    if len(comments)<100:break
else:raise RuntimeError('Pagination exceeded')
report=args.report.read_text(encoding='utf-8')
report=re.sub(r'\]\(([A-Za-z0-9_-]+\.(?:md|json))\)',
              r'](https://github.com/bseazh/persona-voice/blob/main/docs/performance/\1)',report)
body=marker+'\n'+report
assert args.session_id in body
comment=api(f'issues/{args.issue}/comments',{'body':body})
assert api(f'issues/comments/{comment["id"]}')['body']==body
print(comment['html_url'])
