from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, TurnHandlingOptions, cli
from livekit.plugins import elevenlabs, openai, silero
from qwen_stt import QwenSTT

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
这是一场浏览器实时语音体验，不是电话外呼，也不能代替用户执行真实预约、付款或发送消息。
""".strip(),
        )


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def persona_voice(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    eleven_api_key = required("ELEVENLABS_API_KEY")
    session = AgentSession(
        stt=QwenSTT(),
        llm=openai.LLM.with_deepseek(
            api_key=required("DEEPSEEK_API_KEY"),
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            temperature=0.6,
        ),
        tts=elevenlabs.TTS(
            api_key=eleven_api_key,
            voice_id=required("TTS_VOICE_ID"),
            model=os.getenv("TTS_MODEL", "eleven_v4"),
            language="zh",
            enable_logging=False,
        ),
        vad=silero.VAD.load(
            min_speech_duration=0.08,
            min_silence_duration=0.35,
            prefix_padding_duration=0.3,
            activation_threshold=0.35,
        ),
        transcription_timeout=4.0,
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing={"min_delay": 0.25, "max_delay": 1.2},
            interruption={"enabled": True, "min_duration": 0.35},
            preemptive_generation={"enabled": True},
        ),
    )

    await session.start(agent=PersonaAssistant(), room=ctx.room)
    await ctx.connect()
    session.generate_reply(
        instructions="请用一句自然的中文主动打招呼，介绍你叫小禾，然后问用户今天想聊什么。"
    )


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    cli.run_app(server)
