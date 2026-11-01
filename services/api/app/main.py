from __future__ import annotations

import asyncio
import base64
import binascii
import os
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .deepseek import DeepSeekClient, DeepSeekConfig, DeepSeekError
from .elevenlabs import ElevenLabsConfig, ElevenLabsError, ElevenLabsSpeechClient
from .models import ConversationRequest, CreateCall, CreateCallResponse
from .store import Store


store = Store(settings.database_path)
conversation_audio: OrderedDict[str, bytes] = OrderedDict()


async def run_mock(call_id: str) -> None:
    for status in ("dispatching", "dialing", "connected"):
        await asyncio.sleep(settings.mock_step_delay)
        store.set_status(call_id, status)
    await asyncio.sleep(settings.mock_step_delay)
    store.set_status(call_id, "completed", {
        "outcome": "success",
        "summary": "模拟通话已完成；未拨打真实电话，也未执行真实预约。",
        "slots": {"available_time": "15:00", "party_size_supported": True},
        "simulated": True,
    })


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


app = FastAPI(title="Persona Voice API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "database": "ready",
        "real_calls_enabled": settings.enable_real_calls,
        "local_conversation_enabled": settings.enable_local_conversation,
        "livekit_configured": settings.livekit_configured,
        "sip_configured": settings.sip_configured,
        "stepfun_configured": settings.stepfun_configured,
        "elevenlabs_configured": settings.elevenlabs_configured,
        "deepseek_configured": settings.deepseek_configured,
        "mode": "real-ready" if settings.enable_real_calls and settings.livekit_configured and settings.sip_configured else "mock",
    }


def _speech_client() -> ElevenLabsSpeechClient:
    return ElevenLabsSpeechClient(ElevenLabsConfig(
        api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        base_url=os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1"),
        tts_model=os.getenv("TTS_MODEL", "eleven_v4"),
        voice_id=os.getenv("TTS_VOICE_ID", ""),
        output_format=os.getenv("TTS_OUTPUT_FORMAT", "mp3_44100_128"),
        asr_model=os.getenv("STT_MODEL", "scribe_v2"),
        language=os.getenv("STT_LANGUAGE", "zh"),
    ))


def _llm_client() -> DeepSeekClient:
    return DeepSeekClient(DeepSeekConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
    ))


@app.post("/api/conversation")
async def converse(payload: ConversationRequest, response: Response) -> dict:
    if not settings.enable_local_conversation:
        raise HTTPException(403, "语音对话接口仅在本地启动模式下开放")
    if not settings.elevenlabs_configured or not settings.deepseek_configured:
        raise HTTPException(503, "ElevenLabs 或 DeepSeek 尚未配置")
    try:
        audio = base64.b64decode(payload.audio_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(400, "音频数据无效") from error
    if not audio or len(audio) > 12_000_000:
        raise HTTPException(413, "音频为空或超过 12 MB")
    mime = payload.mime_type.split(";", 1)[0].lower()
    extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav"}
    if mime not in extensions:
        raise HTTPException(415, "浏览器录音格式不受支持")
    try:
        speech = _speech_client()
        transcript = await asyncio.to_thread(
            speech.transcribe,
            audio,
            filename=f"recording.{extensions[mime]}",
            content_type=mime,
        )
        answer = await asyncio.to_thread(
            _llm_client().reply,
            transcript,
            [message.model_dump() for message in payload.history],
        )
        answer_audio = await asyncio.to_thread(speech.synthesize, answer)
    except (ElevenLabsError, DeepSeekError, ValueError) as error:
        status = getattr(error, "status_code", 502)
        raise HTTPException(502 if status >= 500 else status, str(error)) from error
    audio_id = uuid.uuid4().hex
    conversation_audio[audio_id] = answer_audio
    while len(conversation_audio) > 20:
        conversation_audio.popitem(last=False)
    audio_url = f"/api/conversation/audio/{audio_id}"
    response.headers["X-Persona-Audio-Url"] = audio_url
    response.headers["X-Persona-Conversation-Version"] = "2"
    response.headers["Cache-Control"] = "no-store"
    return {
        "transcript": transcript,
        "answer": answer,
        "audio_url": audio_url,
        "conversation_version": 2,
    }


@app.get("/api/conversation/audio/{audio_id}")
def conversation_audio_file(audio_id: str) -> Response:
    if not settings.enable_local_conversation:
        raise HTTPException(403, "语音对话接口仅在本地启动模式下开放")
    audio = conversation_audio.get(audio_id)
    if audio is None:
        raise HTTPException(404, "回复音频不存在或已经过期")
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline; filename=reply.mp3"},
    )


@app.post("/api/calls", status_code=202, response_model=CreateCallResponse)
async def create_call(payload: CreateCall, idempotency_key: str | None = Header(default=None, max_length=100)) -> dict:
    if idempotency_key:
        existing = store.by_idempotency(idempotency_key)
        if existing:
            return {"call_id": existing["id"], "status": existing["status"], "mode": existing["mode"], "status_url": f"/api/calls/{existing['id']}"}

    if store.active_count() >= settings.max_concurrent_calls:
        raise HTTPException(409, "已有通话正在进行，请等待其结束")

    if payload.mode == "real":
        if not payload.confirmed:
            raise HTTPException(400, "真实外呼需要显式确认")
        if not settings.enable_real_calls:
            raise HTTPException(403, "服务器未启用真实外呼")
        if payload.phone_number not in settings.allowed_numbers:
            raise HTTPException(403, "号码不在外呼白名单")
        if not settings.livekit_configured:
            raise HTTPException(503, "LiveKit 尚未配置")
        if not settings.sip_configured:
            raise HTTPException(503, "SIP 外呼线路尚未配置")
        raise HTTPException(503, "真实 dispatch 尚未接入；为防止误拨，本次未发起呼叫")

    call_id = f"call_{uuid.uuid4().hex[:20]}"
    call = store.create(call_id, payload.phone_number, payload.task.model_dump(), payload.mode, idempotency_key)
    asyncio.create_task(run_mock(call_id))
    return {"call_id": call_id, "status": call["status"], "mode": payload.mode, "status_url": f"/api/calls/{call_id}"}


@app.get("/api/calls/{call_id}")
def get_call(call_id: str) -> dict:
    call = store.get(call_id)
    if not call:
        raise HTTPException(404, "call not found")
    return call


@app.get("/api/calls")
def list_calls(limit: int = Query(default=25, ge=1, le=100)) -> dict:
    return {"items": store.list(limit)}


static_dir = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
if static_dir.exists():
    assets = static_dir / "_next"
    if assets.exists():
        app.mount("/_next", StaticFiles(directory=assets), name="next-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        candidate = static_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
