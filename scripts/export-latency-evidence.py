"""Export only timing evidence, never phone numbers, message text or credentials."""
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
allowed={'started_speaking_at','stopped_speaking_at','transcription_delay','end_of_turn_delay',
         'on_user_turn_completed_delay','llm_node_ttft','llm_node_ttfs','tts_node_ttfb',
         'playback_latency','e2e_latency'}
source=Path(sys.argv[1])
data=json.loads(source.read_text(encoding='utf-8'))
events=[]
for e in data['events']:
    p=e['payload']
    if e['kind']=='voice.turn_timing':
        payload={'role':p.get('role'),'message_id':p.get('message_id'),
                 'interrupted':p.get('interrupted'),
                 'metrics':{k:v for k,v in p.get('metrics',{}).items() if k in allowed and isinstance(v,(int,float))}}
    elif e['kind']=='phone.state':
        payload={k:p[k] for k in ('at','state','reason') if k in p}
    elif e['kind'] in ('voice.farewell_played','voice.error','voice.closed'):
        payload={k:p[k] for k in ('type','recoverable','reason') if k in p}
    else:continue
    events.append({'kind':e['kind'],'payload':payload})
output={'session_id':data['id'],'source':'consultation API / SDK timing v1',
        'application_revision':'ee37753','status':data['session']['status'],
        'reason':data['session'].get('reason'),'events':events}
target=root/'docs/performance'/f'{source.stem}-timings.json'
target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(target)
