// Offline estimate from private phone captures. Never exports transcript text.
import fs from 'node:fs';
const calls = [1, 2].map(n => {
  const raw = JSON.parse(fs.readFileSync(`BigApple输出/latency-benchmark/baidu-lite-two-min-v2-${n}.json`, 'utf8'));
  const usage = JSON.parse(fs.readFileSync(`docs/performance/baidu-lite-${n}-usage.json`, 'utf8'));
  const messages = raw.session.messages.filter(m => m.role === 'assistant');
  const timings = raw.events.filter(e => e.kind === 'voice.turn_timing' && e.payload.role === 'assistant').map(e => e.payload);
  const spans = timings.map(t => [t.metrics?.started_speaking_at, t.metrics?.stopped_speaking_at]).filter(([s,e]) => Number.isFinite(s) && Number.isFinite(e) && e >= s).sort((a,b) => a[0]-b[0]);
  const merged = [];
  for (const [s,e] of spans) {
    const last = merged.at(-1);
    if (last && s <= last[1]) last[1] = Math.max(last[1],e);
    else merged.push([s,e]);
  }
  const characters = messages.reduce((sum,m) => sum + [...m.text].length, 0);
  const spokenCharacters = messages.reduce((sum,m) => sum + [...m.text.replace(/[\p{P}\p{Z}\s]/gu, '')].length, 0);
  return {call:n,session_id:raw.id,connected_seconds:usage.connected_seconds,assistant_messages:messages.length,
    assistant_interrupted:messages.filter(m=>m.interrupted).length,transcript_codepoints:characters,
    transcript_without_punctuation_space:spokenCharacters,output_interval_count:spans.length,
    agent_output_seconds:merged.reduce((sum,[s,e])=>sum+e-s,0)};
});
const total = key => calls.reduce((sum,c)=>sum+c[key],0);
const minutes = total('connected_seconds')/60;
const charactersPerMinute = total('transcript_codepoints')/minutes;
const result = {source:'Two existing Baidu Lite calls; offline estimate, not standalone TTS or billing measurement',
  character_rule:'Unicode code points including punctuation/space; not a verified provider billing rule',calls,
  connected_minutes:minutes,transcript_codepoints:total('transcript_codepoints'),
  transcript_characters_per_call_minute:charactersPerMinute,
  agent_output_seconds:total('agent_output_seconds'),
  agent_output_fraction:total('agent_output_seconds')/total('connected_seconds'),
  streaming_tts_cny_per_call_minute_estimate:Object.fromEntries(Object.entries({basic:2,premium:2.7,large_model_and_ultimate:3.5}).map(([k,v])=>[k,charactersPerMinute*v/10000])),
  price_source:'https://cloud.baidu.com/doc/SPEECH/s/Ql9misjot',price_checked:'2026-11-05',
  limitations:['Saved transcript may omit generated but interrupted speech; does not measure submitted TTS text.',
    'Agent output timing is not handset playout.', 'No ASR/LLM/telephony/search/server costs included.']};
fs.writeFileSync('docs/performance/baidu-tts-budget.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
