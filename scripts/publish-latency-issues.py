"""Publish the five authorized stage issues; token stays in process memory.

Uses existing gh authentication and SSH transport when local GitHub connectivity is
unavailable. Requires SSH access (sshpass uses SSHPASS, never a CLI password).
Lists issues/comments before writes; reruns do not duplicate known entries.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/performance'
REMOTE = '''import json,sys,urllib.request
p=json.load(sys.stdin)
req=urllib.request.Request('https://api.github.com/repos/bseazh/persona-voice/'+p['path'],data=json.dumps(p['body']).encode() if p.get('body') is not None else None,headers={'Authorization':'Bearer '+p['token'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'persona-latency-report'},method=p['method'])
try:
 with urllib.request.urlopen(req,timeout=40) as r: print(r.read().decode())
except urllib.error.HTTPError as e:
 print(json.dumps({'status':e.code,'error':'GitHub request rejected'}));sys.exit(1)
'''

def main():
    token = subprocess.check_output(['gh','auth','token'],text=True).strip()
    def api(path, body=None):
        cmd = (['sshpass','-e'] if os.getenv('SSHPASS') else []) + ['ssh','-o','ConnectTimeout=10','ubuntu@134.175.154.244','python3 -c '+shlex.quote(REMOTE)]
        p=subprocess.run(cmd,input=json.dumps({'token':token,'path':path,'body':body,'method':'GET' if body is None else 'POST'}),capture_output=True,text=True)
        if p.returncode: raise RuntimeError('GitHub relay failed; inspect existing issues before retry')
        return json.loads(p.stdout)
    existing=[]
    for page in range(1,21):
        batch=api(f'issues?state=all&per_page=100&page={page}');existing.extend(batch)
        if len(batch)<100:break
    else:raise RuntimeError('Issue pagination limit reached')
    results=[]
    names=['01-baseline','02-asr','03-tts','04-preemptive','05-concise']
    titles=['[时延优化 1/5] 基线：两次有效电话与分段耗时','[时延优化 2/5] ASR 识别收尾：优化前后对照','[时延优化 3/5] TTS 双向流式：优化前后对照','[时延优化 4/5] 提前生成：优化前后对照','[时延优化 5/5] 简短发言：优化前后对照']
    for name,title in zip(names,titles):
        found=next((i for i in existing if i['title']==title and 'pull_request' not in i),None)
        if not found:
            body=(DOCS/(name+'.md')).read_text(encoding='utf-8')
            for link in ['TEST_RESULT_TEMPLATE.md','README.md','measurements.json']:
                body=body.replace(']('+link+')','](https://github.com/bseazh/persona-voice/blob/main/docs/performance/'+link+')')
            body+='\n\n## 执行规则\n\n- 每次测试完成立即追加 Markdown 评论，失败也记录；会话 ID 去重，不覆盖历史。\n- 每阶段至少两通有效测试，每通至少五轮。未接通不计有效测试。\n- 记录代码版本、配置、逐段耗时/占比、优化前后差异、人工反馈和保留/回滚决策。\n- 后续阶段以紧邻前一阶段为对照。换手机或 SIM 后重建基线。\n- 当前四项优化均未实施；无实测数据不声称有收益。\n'
            found=api('issues',{'title':title,'body':body})
        results.append({'stage':name,'number':found['number'],'url':found['html_url']})
        print(found['html_url'],flush=True)
    baseline=results[0]['number']
    comments=api(f'issues/{baseline}/comments?per_page=100')
    data=json.loads((DOCS/'measurements.json').read_text(encoding='utf-8'))
    for a in data['attempts']:
        marker='<!-- latency-session:'+a['session_id']+' -->'
        if any(marker in c['body'] for c in comments):continue
        body=f'''{marker}
## 历史基线第 {a['repeat']} 次拨号结果（2026-11-05，补录）

- 会话 ID：`{a['session_id']}`
- 结果：`{a['status']}`，有效轮数 **0**；未进入 AI 对话。
- 拨号至结束：**{a['ended_at']-a['dialing_at']:.3f} 秒**，来源为 phone.state 的 dialing/ended 时间戳。这不是 AI 响应耗时。
- ASR、轮次收尾、LLM、TTS、总响应、占比：**N/A**。
- 代码追溯：计时改动随后归档于 `962a25c`；当时为未提交的计时补丁，不能把该提交宣称为当时完整线上版本。
- 人工听感：没有已确认反馈；不推断接听手机是否响铃。
- 原因：确认未接通；具体原因尚未确定，不归因于 ASR/TTS。
- 决策：不计有效基线，不计算优化收益。换卡后另建两通有效基线。
- 证据：[measurements.json](https://github.com/bseazh/persona-voice/blob/main/docs/performance/measurements.json)
'''
        comment=api(f'issues/{baseline}/comments',{'body':body})
        assert marker in api(f'issues/comments/{comment["id"]}')['body']
        print(comment['html_url'],flush=True)
    for entry in results:
        verified=api('issues/'+str(entry['number']))
        assert verified['state']=='open' and verified['body']
    (DOCS/'issues.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
