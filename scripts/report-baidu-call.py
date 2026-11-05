"""Summarize provider-reported tokens and separately labelled latency boundaries."""
import json
from pathlib import Path
import statistics
import sys

d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
events=d['events']
usage={e['payload']['response_id']:e['payload'] for e in events if e['kind']=='voice.baidu_usage' and e['payload'].get('response_id')}
created={e['payload']['response_id'] for e in events if e['kind']=='voice.realtime_event' and e['payload'].get('type')=='response.created'}
keys={'input_audio':('input_token_details','audio_tokens'), 'input_text':('input_token_details','text_tokens'),
      'output_audio':('output_token_details','audio_tokens'), 'output_text':('output_token_details','text_tokens')}
totals={k:0 for k in keys}
rows=[]
for rid,p in usage.items():
    u=p.get('usage') or {}
    row={'response_id':rid,'status':p.get('status'),'reported_total_tokens':u.get('total_tokens')}
    row['complete_details']=all(isinstance(u.get(a,{}).get(b),(int,float)) for a,b in keys.values())
    for k,(a,b) in keys.items():
        row[k]=u.get(a,{}).get(b)
        if row[k] is not None:totals[k]+=row[k]
    rows.append(row)
prices={'input_audio':.016,'input_text':.002,'output_audio':.06,'output_text':.016}
cost=sum(totals[k]*prices[k]/1000 for k in keys)
states=[e['payload'] for e in events if e['kind']=='phone.state']
connected=next((p['at'] for p in states if p.get('state')=='connected'),None)
ended=next((p['at'] for p in reversed(states) if p.get('state') in ('ended','failed')),None)
duration=ended-connected if connected is not None and ended is not None else None
stops=[e['payload']['at'] for e in events if e['kind']=='voice.realtime_event' and e['payload'].get('type')=='input_audio_buffer.speech_stopped']
starts=[e['payload']['at'] for e in events if e['kind']=='voice.realtime_event' and e['payload'].get('type')=='input_audio_buffer.speech_started']
creation_times={e['payload']['response_id']:e['payload']['at'] for e in events if e['kind']=='voice.realtime_event' and e['payload'].get('type')=='response.created'}
model_metrics={e['payload']['request_id']:e['payload'] for e in events if e['kind']=='voice.metrics' and e['payload'].get('request_id')}
assistant_timings=[e['payload'] for e in events if e['kind']=='voice.turn_timing' and e['payload'].get('role')=='assistant']
latencies=[]
for e in events:
    if e['kind']!='voice.realtime_first_audio':continue
    p=e['payload'];at=p['at']
    prior=[s for s in stops if 0<=at-s<15]
    if prior:
        stop=max(prior)
        if not any(stop<s<at for s in starts):
            rid=p['response_id']
            candidates=[t for t in assistant_timings if 0<=t.get('metrics',{}).get('started_speaking_at',0)-at<1]
            matched=candidates[0] if len(candidates)==1 else None
            m=matched['metrics'] if matched else {}
            latencies.append({'response_id':rid,'seconds':at-stop,
                'speech_stopped_received_at':stop,'response_created_received_at':creation_times.get(rid),
                'first_audio_received_at':at,'sdk_model_ttft_s':model_metrics.get(rid,{}).get('ttft'),
                'assistant_output_started_at':m.get('started_speaking_at'),
                'assistant_output_stopped_at':m.get('stopped_speaking_at'),
                'event_stop_to_agent_output_s':m['started_speaking_at']-stop if m.get('started_speaking_at') else None,
                'assistant_interrupted':matched.get('interrupted') if matched else None,
                'output_match':'unique start within 1s of first audio; temporal heuristic' if matched else 'unmatched'})
sdk=[e['payload'] for e in events if e['kind']=='voice.turn_timing' and e['payload'].get('role')=='assistant']
sdk_times=[p['metrics']['e2e_latency'] for p in sdk if not p.get('interrupted') and p.get('metrics',{}).get('e2e_latency') is not None]
out={'session_id':d['id'],'route':'baidu-realtime','target_seconds':d.get('durationSeconds'),
     'connected_seconds':duration,'timed_hangup_requested':d.get('timedHangup'),'reason':d['session'].get('reason'),
     'usage_responses':len(usage),'responses_created':len(created),'responses_without_usage':sorted(created-set(usage)),
     'usage_details_complete':bool(rows) and all(r['complete_details'] for r in rows) and not (created-set(usage)),
     'tokens':totals,'reported_total_tokens':sum(r['reported_total_tokens'] or 0 for r in rows),
     'observed_model_list_price_cny':cost,'observed_model_cny_per_connected_minute':cost*60/duration if duration else None,
     'search_calls':None,'search_cost_cny':None,'actual_billed_cny':None,
     'price_source':'https://cloud.baidu.com/doc/SPEECH/s/Tmq8y6vdh','price_date':'2026-11-05',
     'latency_boundary':'provider speech_stopped receipt to first audio receipt in Agent; excludes endpoint decision and handset',
     'latency_pairing':'nearest preceding stop, no intervening start; heuristic, not audio-sample trace',
     'provider_latency_rows':latencies,'provider_latency_mean_s':statistics.mean(r['seconds'] for r in latencies) if latencies else None,
     'provider_latency_max_s':max((r['seconds'] for r in latencies),default=None),
     'sdk_complete_output_latency_s':sdk_times,
     'voice_errors':sum(e['kind'] in ('voice.error','voice.provider_failure') for e in events),'usage_rows':rows}
print(json.dumps(out,ensure_ascii=False,indent=2))
target=Path(__file__).resolve().parents[1]/'docs/performance'/('baidu-lite-'+d['repeat']+'-usage.json')
target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
