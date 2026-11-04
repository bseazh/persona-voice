#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo '连接 USB 并解锁手机。仅在无蜂窝通话时恢复 Shizuku 并完整重启网关应用；保留配置，不拨号、不重启手机。'
python3 scripts/gateway-check.py --cold-restart --interactive-ssh || true
read -r -p '按回车关闭窗口…'
