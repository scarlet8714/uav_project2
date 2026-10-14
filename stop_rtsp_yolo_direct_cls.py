#!/usr/bin/env python3
"""Stop servers launched with python3 -m rtsp_yolo_direct_cls on Linux."""

import argparse
import os
from pathlib import Path
import signal
import time


def server_identity(pid):
    """Return start time to distinguish a server from a reused PID."""
    try:
        directory = Path('/proc') / str(pid)
        args = directory.joinpath('cmdline').read_bytes().split(b'\0')
        if not args or not Path(os.fsdecode(args[0])).name.startswith('python'):
            return None
        if not any(args[i:i + 2] == [b'-m', b'rtsp_yolo_direct_cls']
                   for i in range(len(args) - 1)):
            return None
        fields = directory.joinpath('stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return fields[19]  # /proc stat field 22: process start time
    except (OSError, ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description='停止 rtsp_yolo_direct_cls 伺服器')
    parser.add_argument('--timeout', type=float, default=15,
                        help='等待正常關閉的秒數（預設 15）')
    parser.add_argument('--force', action='store_true',
                        help='逾時後以 SIGKILL 強制停止')
    options = parser.parse_args()
    if not 0 <= options.timeout < float('inf'):
        parser.error('--timeout 必須是有限的非負數')

    targets = {}
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            pid = int(entry.name)
            identity = server_identity(pid)
            if identity is not None and pid != os.getpid():
                targets[pid] = identity
    if not targets:
        print('沒有找到執行中的 rtsp_yolo_direct_cls。')
        return 0

    failed = False
    for pid, identity in targets.items():
        try:
            if server_identity(pid) == identity:
                os.kill(pid, signal.SIGTERM)
                print(f'已要求正常停止 PID {pid}。')
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f'沒有權限停止 PID {pid}，請以啟動該程序的使用者執行。')
            failed = True

    deadline = time.monotonic() + options.timeout
    pending = targets
    while True:
        pending = {pid: identity for pid, identity in pending.items()
                   if server_identity(pid) == identity}
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    if pending and options.force:
        for pid, identity in pending.items():
            try:
                if server_identity(pid) == identity:
                    os.kill(pid, signal.SIGKILL)
                    print(f'已送出強制停止訊號至 PID {pid}。')
            except ProcessLookupError:
                pass
            except PermissionError:
                print(f'沒有權限強制停止 PID {pid}。')
                failed = True
    elif pending:
        print('等待逾時，仍在執行的 PID：' + ', '.join(map(str, pending)))
        print('需要強制停止時，請加上 --force。')
        return 1
    else:
        print('rtsp_yolo_direct_cls 已停止。')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
