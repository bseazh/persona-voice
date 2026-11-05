"""Read private benchmark JSON; print numeric-only latency and usage summary."""
import json
import math
from pathlib import Path
import statistics
import sys

d = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
events = d['events']
usage = [e['payload'] for e in events if e['kind'] == 'voice.provider_usage']
submitted = {p['attempt_id']:p for p in usage if p.get('model') == 'mimo-v2.5-asr' and p.get('phase') == 'submitted'}
completed = {p['attempt_id']:p for p in usage if p.get('model') == 'mimo-v2.5-asr' and p.get('phase') == 'completed'}
tts = {p['attempt_id']:p for p in usage if p.get('model') == 'mimo-v2.5-tts'}
seconds = sum(p['input_audio_seconds'] for p in submitted.values())
rounded = sum(math.ceil(p['input_audio_seconds']) for p in submitted.values())
turns = [e['payload'] for e in events if e['kind'] == 'voice.turn_timing' and e['payload'].get('role') == 'assistant']
complete_turns = [p['metrics']['e2e_latency'] for p in turns if not p.get('interrupted') and 'e2e_latency' in p['metrics']]
llm = [e['payload'] for e in events if e['kind'] == 'voice.metrics' and e['payload'].get('type') == 'LLMMetrics']
states = [e['payload'] for e in events if e['kind'] == 'phone.state']
connected = next((p['at'] for p in states if p.get('state') == 'connected'), None)
ended = next((p['at'] for p in reversed(states) if p.get('state') in ('ended','failed')), None)
def tokens(items):
    return {key: sum(p.get('usage',{}).get(key,0) for p in items)
            for key in ('prompt_tokens','completion_tokens','total_tokens')}
provider_seconds = sum(p.get('usage',{}).get('seconds',0) for p in completed.values())
cost = provider_seconds * .5 / 3600
call_seconds = ended-connected if ended and connected else None
out = {
    'session_id': d['id'], 'phone_state': d['session'].get('phone_state'),
    'reason': d['session'].get('reason'),
    'connected_to_end_seconds': ended-connected if ended and connected else None,
    'complete_timed_turns': len(complete_turns),
    'latency_mean_s': statistics.mean(complete_turns) if complete_turns else None,
    'latency_max_s': max(complete_turns) if complete_turns else None,
    'latency_values_s': complete_turns,
    'asr_submitted_requests': len(submitted), 'asr_completed_requests': len(completed),
    'speech_usage_observed': bool(submitted and tts),
    'asr_submitted_audio_s': seconds,
    'asr_provider_usage_seconds': provider_seconds,
    'asr_provider_seconds_coverage': sum('seconds' in p.get('usage',{}) for p in completed.values()),
    'asr_tokens': tokens(completed.values()),
    'tts_tokens': tokens(tts.values()),
    'tts_usage_coverage': sum(bool(p.get('usage')) for p in tts.values()),
    'asr_estimate_cny_provider_seconds': cost,
    'speech_estimate_cny_per_call_minute': cost*60/call_seconds if call_seconds else None,
    'asr_estimate_cny_prorated': seconds * .5 / 3600,
    'asr_estimate_cny_if_each_request_rounded_up': rounded * .5 / 3600,
    'tts_requests_observed': len(tts),
    'tts_complete_requests': sum(p.get('complete') is True for p in tts.values()),
    'tts_received_audio_s': sum(p.get('received_audio_seconds',0) for p in tts.values()),
    'tts_input_characters': sum(p.get('input_characters',0) for p in tts.values()),
    'tts_estimate_cny_current_promotion': 0,
    'llm_prompt_tokens_observed': sum(p.get('prompt_tokens',0) for p in llm),
    'llm_completion_tokens_observed': sum(p.get('completion_tokens',0) for p in llm),
    'farewell_count': sum(e['kind']=='voice.farewell_played' for e in events),
    'voice_errors': sum(e['kind']=='voice.error' for e in events),
    'pricing_date': '2026-11-05',
    'pricing_source': 'https://mimo.mi.com/static/docs/price/pay-as-you-go.md',
    'cost_scope': 'MiMo speech only; estimate not invoice; excludes DeepSeek, report, SIM and server',
    'caveats': 'Submitted audio includes padding/retries; cancelled TTS output may be partial; no handset latency measurement.'
}
print(json.dumps(out,ensure_ascii=False,indent=2))
