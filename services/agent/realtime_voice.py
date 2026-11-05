"""Business ending for the opt-in duplex route, independent of model tools."""
import asyncio
import time

from livekit import api
from livekit.agents import Agent
from consultation_voice import INSTRUCTIONS, VoiceController
from qwen_realtime import MODEL
from realtime_control import explicit_end


class RealtimeAssistant(Agent):
    def __init__(self):
        instructions=INSTRUCTIONS.split('对方要求结束')[0]
        instructions+='\n开场说明只说一次；用户开始提问后直接回答问题，不再重复自我介绍或征求开始。用户明确说再见、挂断或聊到这里时，系统会负责告别和结束，请不要重复告别。不要声称已经挂断电话。'
        super().__init__(instructions=instructions)


class RealtimeController(VoiceController):
    def __init__(self,ctx,session,journal,model):
        super().__init__(ctx,session,journal)
        self.model=model
        self.route=getattr(model,'route','qwen-realtime')
        self.end_task=None
        self.close_lock=asyncio.Lock()
        model.transport.on_transcript=self.transcript

    def benchmark_config(self):
        if self.route=='doubao-realtime':
            return {'stage':'doubao-duplex-v1','route':self.route,
                'model':self.model.model,'voice':self.model.voice,
                'input_sample_rate':16000,'output_sample_rate':24000,
                'endpoint':'agent_room_output_not_handset','measurement_version':3,
                'turn_boundary':'provider_transcription_completed',
                'separate_asr_llm_tts_metrics':False,'preemptive_generation':False}
        return {'stage':'qwen-duplex-v1','route':'qwen-realtime',
            'model':MODEL,'voice':'longanqian','input_sample_rate':16000,
            'output_sample_rate':24000,'server_vad_silence_ms':500,
            'endpoint':'agent_room_output_not_handset','measurement_version':2,
            'separate_asr_llm_tts_metrics':False,'preemptive_generation':False}

    def transcript(self,text):
        if explicit_end(text):self.request_end('explicit_user_end')

    def request_end(self,reason):
        if self.finishing or self.closed:return
        self.finishing=True
        self.ending_requested=True
        # Gate provider output synchronously, before the next audio delta can
        # race with the async cancellation and goodbye work.
        self.model.mute_responses()
        self.session.input.set_audio_enabled(False)
        self.journal.emit('ending',{'reason':reason,'route':self.route})
        self.end_task=asyncio.create_task(self._finish())

    async def _finish(self):
        reason='farewell_played'
        try:
            await asyncio.wait_for(self.session.interrupt(force=True),5)
            text,frames=await self.model.farewell()
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
        await self.close_room(reason)

    async def watch(self):
        while not self.closed:
            await asyncio.sleep(2)
            try:
                status=await self.journal.request('heartbeat')
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
                release=await asyncio.wait_for(self.journal.request('release'),12)
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
