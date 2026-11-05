"""Create the authorized realtime track issue, or append a reviewed report once."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publisher',Path(__file__).with_name('publish-latency-issues.py'))
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
parser=argparse.ArgumentParser()
parser.add_argument('--report',type=Path)
parser.add_argument('--marker')
args=parser.parse_args()
token=subprocess.check_output(['gh','auth','token'],text=True).strip()
def api(path,body=None):
    cmd=(['sshpass','-e'] if os.getenv('SSHPASS') else [])+['ssh','ubuntu@134.175.154.244','python3 -c '+shlex.quote(publisher.REMOTE)]
    result=subprocess.run(cmd,input=json.dumps({'token':token,'path':path,'body':body,'method':'POST' if body is not None else 'GET'}),capture_output=True,text=True)
    if result.returncode:raise RuntimeError('GitHub result uncertain; read existing issue before retry')
    return json.loads(result.stdout)
title='[独立路线] Qwen 原生全双工实时语音：打断、结束与双路线验收'
found=None
for page in range(1,21):
    batch=api(f'issues?state=all&per_page=100&page={page}')
    found=next((i for i in batch if i['title']==title and 'pull_request' not in i),None)
    if found or len(batch)<100:break
else:raise RuntimeError('Pagination limit')
if found is None:
    found=api('issues',{'title':title,'body':(root/'docs/performance/QWEN_DUPLEX_TRACK.md').read_text(encoding='utf-8')})
assert api('issues/'+str(found['number']))['title']==title
print(found['html_url'],flush=True)
if args.report:
    if not args.marker:raise RuntimeError('Report requires stable marker')
    marker='<!-- qwen-duplex:'+args.marker+' -->'
    for page in range(1,21):
        comments=api(f'issues/{found["number"]}/comments?per_page=100&page={page}')
        old=next((c for c in comments if marker in c['body']),None)
        if old:
            print(old['html_url']);break
        if len(comments)<100:
            body=marker+'\n'+args.report.read_text(encoding='utf-8')
            comment=api(f'issues/{found["number"]}/comments',{'body':body})
            assert api('issues/comments/'+str(comment['id']))['body']==body
            print(comment['html_url']);break
    else:raise RuntimeError('Pagination limit')
