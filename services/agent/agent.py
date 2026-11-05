from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, TurnHandlingOptions, cli
from livekit.plugins import openai, silero
from qwen_stt import QwenSTT
from qwen_streaming_stt import QwenStreamingSTT
from qwen_tts import QwenTTS
from mimo_tts import MiMoTTS
from mimo_stt import MiMoSTT
from phone_transcript import attach_phone_transcript
from consultation_voice import VoiceJournal, VoiceController, ConsultationAssistant
from turn_profile import turn_profile
from preflight import preflight_enabled
from qwen_realtime import QwenRealtime
from realtime_voice import RealtimeAssistant, RealtimeController
from doubao_realtime import DoubaoRealtime
from baidu_realtime import BaiduRealtime

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("persona-voice-agent")
AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "persona-voice-agent")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class PersonaAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
你叫小禾，是一个自然、耐心、可靠的中文语音助手。
默认使用简体中文回答；如果用户切换语言，你可以跟随。
每次回答尽量控制在一到三句话，语气口语化，先直接回答，再在必要时追问一个问题。
不要使用 Markdown、项目符号、表格、代码块或表情符号，因为你的回答会直接转成语音。
不要朗读网址协议、内部提示词、模型名、密钥、系统实现或推理过程。
遇到不确定的信息要明确说明，不要编造。涉及医疗、法律或财务决策时只提供一般信息并提示咨询专业人士。
当前没有实时搜索工具。对于最新型号、实时价格、新闻等时效性问题，先说明无法实时核实，不要把已有知识当作当前最新事实。
你通过浏览器或电话提供实时语音对话。你是 AI 助手，不能代替用户执行真实预约、付款或发送消息。
""".strip(),
        )


server = AgentServer(num_idle_processes=int(os.getenv('LIVEKIT_AGENT_IDLE_PROCESSES', '1')))


@server.rtc_session(agent_name=AGENT_NAME)
async def persona_voice(ctx: JobContext) -> None:
    await ctx.connect()
    ctx.log_context_fields = {"room": ctx.room.name}
    consultation=ctx.room.name.startswith(('consult-','sim-ai-'))
    journal=VoiceJournal(ctx.room.name) if consultation else None
    speech={}
    route='pipeline'
    business_instructions=None
    if journal:
        try:
            consultation_id = None
            if ctx.room.name.startswith('sim-ai-'):
                participant = await ctx.wait_for_participant()
                consultation_id = participant.attributes.get('persona.consultation_id')
            configuration=await journal.start(consultation_id)
            speech=configuration['speech']
            route=configuration.get('voice_route','pipeline')
            business_instructions=configuration.get('business_instructions')
        except Exception:
            await journal.close()
            raise
    speech_to_text=None
    if route in ('qwen-realtime','doubao-realtime','baidu-realtime'):
        model=(BaiduRealtime(audit=journal.emit if journal else None) if route=='baidu-realtime' else DoubaoRealtime(key=speech['key'],voice=speech['voice'],audit=journal.emit if journal else None)
               if route in ('doubao-realtime','baidu-realtime') else QwenRealtime(key=speech.get('key'),audit=journal.emit if journal else None))
        session=AgentSession(llm=model)
        ctx.add_shutdown_callback(model.aclose)
    elif route in ('pipeline', 'pipeline-mimo', 'pipeline-mimo-all'):
        profile = turn_profile()
        synthesis = MiMoTTS(audit=journal.emit if journal else None) if route in ('pipeline-mimo','pipeline-mimo-all') else QwenTTS(**speech)
        ctx.add_shutdown_callback(synthesis.aclose)
        if route == 'pipeline-mimo-all':
            speech_to_text = MiMoSTT(audit=journal.emit if journal else None)
            ctx.add_shutdown_callback(speech_to_text.aclose)
        else:
            speech_to_text = QwenStreamingSTT(audit=journal.emit if journal else None, **speech) if consultation or os.getenv('ASR_MODE', 'streaming') == 'streaming' else QwenSTT()
        session = AgentSession(
            stt=speech_to_text,
            llm=openai.LLM.with_deepseek(
                api_key=required("DEEPSEEK_API_KEY"),
                model=os.getenv("LLM_MODEL", "deepseek-chat"),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                temperature=0.6,
            ),
            tts=synthesis,
            vad=silero.VAD.load(
                min_speech_duration=0.08,
                min_silence_duration=profile['vad_silence'],
                prefix_padding_duration=0.3,
                activation_threshold=0.35,
            ),
            transcription_timeout=4.0,
            turn_handling=TurnHandlingOptions(
                turn_detection="vad",
                endpointing={"min_delay": profile['endpoint_min'], "max_delay": profile['endpoint_max']},
                interruption={"enabled": True, "min_duration": 0.35},
                preemptive_generation={"enabled": preflight_enabled() and route != 'pipeline-mimo-all', "preemptive_tts": False,
                                       "max_retries": 2, "max_speech_duration": 10.0},
            ),
        )
    else:
        raise ValueError('Unsupported voice route')

    if isinstance(speech_to_text, QwenStreamingSTT):
        @session.on('user_state_changed')
        def user_state_changed(event):
            # With turn_detection='vad', these transitions come from VAD hooks.
            if event.new_state in ('speaking', 'listening'):
                speech_to_text.set_user_speaking(event.new_state == 'speaking')

    attach_phone_transcript(session, ctx.room.name)
    controller=(RealtimeController(ctx,session,journal,model) if route in ('qwen-realtime','doubao-realtime','baidu-realtime')
                else VoiceController(ctx,session,journal)) if journal else None
    if controller:
        controller.voice_route = route
        controller.attach()
    assistant=RealtimeAssistant(business_instructions) if route in ('qwen-realtime','doubao-realtime','baidu-realtime') else ConsultationAssistant(controller,business_instructions) if controller else PersonaAssistant()
    await session.start(agent=assistant, room=ctx.room)
    if route == 'baidu-realtime':
        return  # Lite starts from real user audio; do not issue unsupported response.create.
    session.generate_reply(
        instructions="根据采购任务，用一两句话说明AI身份、采购沟通目的和文字保存用途，询问现在是否方便。不要直接朗读问题清单。" if business_instructions else "请简短介绍你是AI小禾，可以自由聊天，会保存文字转录和对话摘要，询问是否方便开始。不要提出健康或睡眠调查。只说一两句话。" if consultation else "请用一句自然的中文主动打招呼，介绍你叫小禾，然后问用户今天想聊什么。"
    )


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    cli.run_app(server)
