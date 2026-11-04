"""Desktop gateway checks. --recover restarts available Shizuku/SIP, never dials."""
import argparse
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import sys
import time

RECEIVER = 'io.github.sparkcyf.voicesipagent/io.github.sparkcyf.voicesipagent.app.AdbControlReceiver'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--cold-restart', action='store_true', help='When idle, fully restart the gateway app instead of only its SIP stack')
    parser.add_argument('--serial')
    parser.add_argument('--interactive-ssh', action='store_true', help='Allow SSH to prompt for a password in a terminal')
    parser.add_argument('--server', default='ubuntu@134.175.154.244')
    args = parser.parse_args()
    if args.cold_restart: args.recover = True

    def execute(command, timeout=15):
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)

    if not shutil.which('adb'):
        print('缺少 adb：macOS 可安装 Android Platform Tools。')
        return 1
    devices = execute(['adb', 'devices']).stdout.splitlines()[1:]
    rows = [line.split() for line in devices if line.strip()]
    if args.serial:
        rows = [row for row in rows if row[0] == args.serial]
    if len(rows) != 1:
        print('未连接唯一 USB 设备；拔线测试时这是正常的。恢复需连接手机，多个设备请加 --serial。')
        ready = False
    elif rows[0][1] != 'device':
        print('USB 状态：' + rows[0][1] + '；请解锁手机并确认 USB 调试授权。')
        ready = False
    else:
        adb = ['adb', '-s', rows[0][0]]
        def status():
            return execute(adb + ['shell', 'am', 'broadcast', '-n', RECEIVER, '--es', 'op', 'status']).stdout
        result = status()
        print(result.strip())
        if 'calls=No cellular call' not in result and args.recover:
            print('无法确认无活动电话，跳过恢复；先手动确认电话已结束。')
            return 1
        if args.recover and 'shizuku=CONNECTED' not in result:
            paths = execute(adb + ['shell', 'pm', 'path', 'moe.shizuku.privileged.api']).stdout
            bases = [p.removeprefix('package:') for p in paths.splitlines() if p.endswith('/base.apk')]
            if bases:
                library = str(PurePosixPath(bases[0]).parent / 'lib/arm64/libshizuku.so')
                if re.fullmatch(r'/data/app/[A-Za-z0-9_~./+=-]+', library):
                    started = execute(adb + ['shell', library], timeout=25)
                    print('已尝试启动 Shizuku，退出码：', started.returncode)
            else:
                print('未发现 Shizuku；请在手机安装并按应用提示启动，授权 Voice SIP Agent。')
        if args.recover:
            check = status()
            if 'shizuku=CONNECTED' in check:
                if args.cold_restart:
                    print('当前无蜂窝通话；完整重启 Voice SIP Agent，保留应用数据和 SIP 配置。')
                    execute(adb + ['shell', 'am', 'force-stop', 'io.github.sparkcyf.voicesipagent'])
                    execute(adb + ['shell', 'am', 'start', '-n', 'io.github.sparkcyf.voicesipagent/.app.MainActivity'])
                else:
                    print(execute(adb + ['shell', 'am', 'broadcast', '-n', RECEIVER, '--es', 'op', 'sip-restart']).stdout.strip())
                for _ in range(10):
                    time.sleep(1)
                    check = status()
                    if 'ready=true' in check and 'shizuku=CONNECTED' in check: break
            else:
                print('Shizuku 尚未连接；请在手机确认授权，未强制修改权限。')
            result = status()
            print(result.strip())
        ready = all(token in result for token in ('ready=true', 'shizuku=CONNECTED', 'sip=ready', 'audioReady=true'))
        if not ready:
            print('手机仍未就绪。检查联网、后台运行权限、Shizuku 授权及 SIM 槽位；脚本不会自动更换 SIM 或号码。')

    remote = execute(['ssh', '-o', 'BatchMode=' + ('no' if args.interactive_ssh else 'yes'), '-o', 'ConnectTimeout=8', args.server,
                      'sudo -n asterisk -rx "pjsip show contacts"'], timeout=90 if args.interactive_ssh else 12)
    if remote.returncode:
        print('服务器检查未完成：需要可用的 SSH 密钥及 sudo 权限。可手动 SSH 后执行 pjsip show contacts；不要把服务器密码写入脚本。')
        return 1
    online = any('k60-test/' in line and re.search(r'\bAvail\b', line) for line in remote.stdout.splitlines())
    print('服务器 SIP 注册：' + ('在线' if online else '离线；恢复后可能需要等待重新注册'))
    if ready and not online:
        print('手机报告与服务器不一致；不要拨号。空闲时可加 --cold-restart 完整重启网关，再观察至少 6 分钟续注册。')
    print('检查不代表蜂窝音频已验证；必须通过授权通话确认实际听感。')
    return 0 if ready and online else 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.TimeoutExpired:
        print('检查超时；确认网络和 USB 状态后重试。')
        sys.exit(1)
