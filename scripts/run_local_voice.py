#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import importlib.util
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_OUT = ROOT / "web" / "out"


def load_env(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def main() -> None:
    if importlib.util.find_spec("uvicorn") is None:
        venv_python = ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            raise SystemExit("缺少 Python 依赖，请先创建 .venv 并安装 services/api/requirements.txt")
        os.execv(venv_python, [str(venv_python), __file__])
    load_env(ROOT / ".env")
    os.environ["ENABLE_LOCAL_CONVERSATION"] = "true"
    tunnel = start_elevenlabs_tunnel()
    if not (WEB_OUT / "index.html").exists():
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", check=True)
    os.environ["STATIC_DIR"] = str(WEB_OUT)
    sys.path.insert(0, str(ROOT / "services" / "api"))
    import uvicorn

    print("本地语音页面：http://127.0.0.1:5050")
    print("按 Control+C 停止；服务仅监听本机，不对局域网或公网开放。")
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=5050)
    finally:
        if tunnel:
            tunnel.terminate()
            tunnel.wait(timeout=5)


def start_elevenlabs_tunnel() -> subprocess.Popen[str] | None:
    key = Path(os.getenv("ELEVENLABS_TUNNEL_KEY", Path.home() / ".ssh" / "persona_voice_tunnel"))
    if not key.exists():
        return None
    host = os.getenv("ELEVENLABS_TUNNEL_HOST", "ubuntu@134.175.154.244")
    local_port = os.getenv("ELEVENLABS_TUNNEL_PORT", "18443")
    tunnel = subprocess.Popen(
        [
            "ssh", "-N", "-L", f"127.0.0.1:{local_port}:api.elevenlabs.io:443",
            "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", host,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1)
    if tunnel.poll() is not None:
        error = tunnel.stderr.read().strip() if tunnel.stderr else "unknown SSH error"
        raise SystemExit(f"ElevenLabs SSH 隧道启动失败：{error}")
    os.environ["ELEVENLABS_CURL_CONNECT_TO"] = f"api.elevenlabs.io:443:127.0.0.1:{local_port}"
    print("ElevenLabs 云端网络隧道：已连接")
    return tunnel


if __name__ == "__main__":
    main()
