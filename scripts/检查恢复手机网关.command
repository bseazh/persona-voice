#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo '连接 USB 并解锁手机。将检查状态并尝试恢复 Shizuku / SIP，不拨号、不重启手机。'
python3 scripts/gateway-check.py --recover --interactive-ssh || true
read -r -p '按回车关闭窗口…'
