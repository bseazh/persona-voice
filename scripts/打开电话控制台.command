#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo '账号 operator；控制台密码见 BigApple输出/android-gateway/phone-console-access.txt（如已由管理员配置）。'
echo '请在下面输入 SSH 登录密码（输入时不显示）；若已配置 SSH 密钥则无需输入。'
(
  for _ in $(seq 1 60); do
    if curl --max-time 1 -s -o /dev/null http://127.0.0.1:5055; then
      open http://127.0.0.1:5055
      exit 0
    fi
    sleep 1
  done
) &
bash scripts/open-phone-console.sh
