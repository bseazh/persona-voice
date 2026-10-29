from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import CreateCall, CreateCallResponse
from .store import Store


store = Store(settings.database_path)


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
        "livekit_configured": settings.livekit_configured,
        "sip_configured": settings.sip_configured,
        "stepfun_configured": settings.stepfun_configured,
        "elevenlabs_configured": settings.elevenlabs_configured,
        "mode": "real-ready" if settings.enable_real_calls and settings.livekit_configured and settings.sip_configured else "mock",
    }


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


static_dir = Path(__file__).resolve().parent.parent / "static"
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
