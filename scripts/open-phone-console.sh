#!/usr/bin/env bash
set -euo pipefail
target="${PHONE_SSH_TARGET:-ubuntu@134.175.154.244}"
echo '保持此窗口打开。隧道建立后打开 http://127.0.0.1:5055'
echo '登录用户名 operator；使用单独的控制台密码。Ctrl+C 关闭隧道，不会挂断电话。'
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -N -L 127.0.0.1:5055:127.0.0.1:5055 "$target"
