#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import importlib.util
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
    if not (WEB_OUT / "index.html").exists():
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", check=True)
    os.environ["STATIC_DIR"] = str(WEB_OUT)
    sys.path.insert(0, str(ROOT / "services" / "api"))
    import uvicorn

    print("本地语音页面：http://127.0.0.1:5050")
    print("按 Control+C 停止；服务仅监听本机，不对局域网或公网开放。")
    uvicorn.run("app.main:app", host="127.0.0.1", port=5050)


if __name__ == "__main__":
    main()
