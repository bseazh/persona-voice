"""Business ending for the opt-in duplex route, independent of model tools."""
import asyncio
import time

from livekit import api
from livekit.agents import Agent
from consultation_voice import INSTRUCTIONS, VoiceController
from qwen_realtime import MODEL
from realtime_control import explicit_end


class RealtimeAssistant(Agent):
    def __init__(self, instructions=None, knowledge=None):
        instructions=instructions or INSTRUCTIONS.split('对方要求结束')[0]
        instructions+='\n开场说明只说一次；用户开始提问后直接回答问题，不再重复自我介绍或征求开始。用户明确说再见、挂断或聊到这里时，系统会负责告别和结束，请不要重复告别。不要声称已经挂断电话。'
        if knowledge:
            from procurement_knowledge import INSTRUCTIONS as KNOWLEDGE_INSTRUCTIONS
            instructions += KNOWLEDGE_INSTRUCTIONS
        super().__init__(instructions=instructions, tools=[knowledge.tool()] if knowledge else [])


class RealtimeController(VoiceController):
    def __init__(self,ctx,session,journal,model):
        super().__init__(ctx,session,journal)
        self.model=model
        self.route=getattr(model,'route','qwen-realtime')
        self.end_task=None
        self.close_lock=asyncio.Lock()
        self.phone_deadline=None
        self.end_reason=None
        model.transport.on_transcript=self.transcript

    def update_phone_deadline(self, remaining):
        if isinstance(remaining,(int,float)) and not isinstance(remaining,bool) and 0 <= remaining <= 180:
            deadline=time.monotonic()+remaining
            # A delayed heartbeat must never extend the phone safety deadline.
            self.phone_deadline=min(self.phone_deadline,deadline) if self.phone_deadline is not None else deadline

    def phone_wrapup_due(self):
        return self.phone_deadline is not None and time.monotonic() >= self.phone_deadline-40

    def benchmark_config(self):
        if self.route=='baidu-realtime':
            return {'stage':'baidu-lite-v1','route':self.route,'model':self.model.model,
                'voice':self.model.voice,'input_sample_rate':16000,'output_sample_rate':24000,
                'endpoint':'agent_room_output_not_handset','separate_asr_llm_tts_metrics':False,
                'billing_source':'provider_response_usage_only','custom_instructions_supported':False}
        if self.route=='doubao-realtime':
            return {'stage':'doubao-duplex-v1','route':self.route,
                'model':self.model.model,'voice':self.model.voice,
                'input_sample_rate':16000,'output_sample_rate':24000,
                'endpoint':'agent_room_output_not_handset','measurement_version':3,
                'turn_boundary':'provider_transcription_completed',
                'separate_asr_llm_tts_metrics':False,'preemptive_generation':False}
        return {'stage':'qwen-duplex-v1','route':'qwen-realtime',
            'model':MODEL,'voice':'longanqian','input_sample_rate':16000,
            'output_sample_rate':24000,'turn_mode':self.model.turn_mode,
            'server_vad_silence_ms':500 if self.model.turn_mode=='server_vad' else None,
            'endpoint':'agent_room_output_not_handset','measurement_version':3,
            'phone_wrapup_reserve_seconds':40 if self.phone_deadline is not None else None,
            'wire_phase_timestamps':True,
            'separate_asr_llm_tts_metrics':False,'preemptive_generation':False}

    def transcript(self,text):
        if explicit_end(text):self.request_end('explicit_user_end')

    def request_end(self,reason):
        if self.finishing or self.closed:return
        self.end_reason=reason
        if self.route=='baidu-realtime':
            self.finishing=True
            self.journal.emit('ending',{'reason':reason,'route':self.route,'farewell':'not_requested_unsupported'})
            self.end_task=asyncio.create_task(self._finish_baidu(reason))
            return
        self.finishing=True
        self.ending_requested=True
        # Gate provider output synchronously, before the next audio delta can
        # race with the async cancellation and goodbye work.
        if reason!='phone_duration_limit':self.model.mute_responses()
        self.session.input.set_audio_enabled(False)
        self.journal.emit('ending',{'reason':reason,'route':self.route})
        self.end_task=asyncio.create_task(self._finish())

    async def _finish_baidu(self,reason):
        if reason=='explicit_user_end':
            # Wait for the provider's current answer to be scheduled and played.
            # Do not claim that this is a prescribed farewell: Lite has no such API.
            try:
                async with asyncio.timeout(15):
                    while self.session.current_speech is None:
                        await asyncio.sleep(.05)
                    handle=self.session.current_speech
                    await handle.wait_for_playout()
                    self.journal.emit('native_end_reply_played',{'interrupted':handle.interrupted})
            except Exception:
                self.journal.emit('native_end_reply_timeout',{})
        await self.close_room(reason)

    async def _finish(self):
        reason='farewell_played'
        try:
            async with asyncio.timeout(25 if self.end_reason=='phone_duration_limit' else 40):
                if self.end_reason=='phone_duration_limit':
                    speech=getattr(self.session,'current_speech',None)
                    if speech:
                        try:await asyncio.wait_for(asyncio.shield(speech.wait_for_playout()),5)
                        except TimeoutError:self.journal.emit('wrapup_drain_timeout',{'seconds':5})
                self.model.mute_responses()
                await asyncio.wait_for(self.session.interrupt(force=True),5)
                if self.route=='qwen-realtime' and self.end_reason=='phone_duration_limit':
                    text,frames=await self.model.farewell(reason='duration_limit')
                else:text,frames=await self.model.farewell()
                async def audio():
                    for frame in frames:yield frame
                handle=self.session.say(text,audio=audio())
                await asyncio.wait_for(handle.wait_for_playout(),15)
                if handle.interrupted or handle.exception():raise RuntimeError('farewell_not_played')
                self.journal.emit('farewell_played',{'text':text,'provider':getattr(self.model,'provider',MODEL)})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reason='farewell_playback_failed'
            self.journal.emit('farewell_failed',{'error_type':type(error).__name__})
        await self.close_room('phone_duration_limit_farewell_played' if reason=='farewell_played' and self.end_reason=='phone_duration_limit' else reason)

    async def watch(self):
        while not self.closed:
            await asyncio.sleep(2)
            if self.phone_wrapup_due():self.request_end('phone_duration_limit')
            try:
                status=await asyncio.wait_for(self.journal.request('heartbeat'),3)
                self.update_phone_deadline(status.get('phone_remaining_seconds'))
                if status['closed']:
                    await self.close_room('operator_force_end')
                    return
                if status['ending'] or time.monotonic()-self.started>900:
                    self.request_end('operator_end' if status['ending'] else 'duration_limit')
            except asyncio.CancelledError:raise
            except Exception:
                self.journal.emit('control_retry',{'operation':'heartbeat'})

    async def close_room(self,reason):
        async with self.close_lock:
            if self.closed:return
            self.finishing=True
            self.model.mute_responses()
            self.session.input.set_audio_enabled(False)
            if self.end_task and self.end_task is not asyncio.current_task():
                self.end_task.cancel()
            # Release the owned phone call before deleting the room, since
            # room teardown can start the LiveKit job's shutdown callbacks.
            try:
                release=await asyncio.wait_for(self.journal.request('release'),8 if self.end_reason=='phone_duration_limit' else 12)
                self.journal.emit('phone_release',release)
            except Exception:
                self.journal.emit('phone_release',{'confirmed':False,'error':'release_unconfirmed'})
            released=False
            for attempt in range(3):
                try:
                    await asyncio.wait_for(self.ctx.api.room.delete_room(
                        api.DeleteRoomRequest(room=self.ctx.room.name)),5)
                    released=True
                    break
                except Exception:
                    self.journal.emit('release_retry',{'attempt':attempt+1,'target':'livekit_room'})
                    await asyncio.sleep(.25)
            self.journal.emit('room_release',{'confirmed':released})
            self.closed=True
            self.journal.emit('closed',{'reason':reason if released else 'room_release_unconfirmed',
                'room_release_confirmed':released,'handset_release_confirmed':False})
            self.session.shutdown(drain=False)
            await self.journal.flush()
