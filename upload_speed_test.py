#!/usr/bin/env python3
"""測量對外 HTTP 上傳速度；需要 Python 3 與 curl，不需安裝 Python 套件。

    python3 upload_speed_test.py
    python3 upload_speed_test.py --size-mb 20 --runs 5 --output upload_result.json
    python3 upload_speed_test.py --ip-version 6

預設使用 Cloudflare 的上傳測試端點，傳送臨時產生的隨機資料。
來源：https://github.com/cloudflare/speedtest
速度 = 成功上傳的位元數 / 整次 HTTP 請求耗時，包含 DNS、建連與回應時間。
這是單條 HTTP 連線的有效吞吐量，不代表 GCP／Tailscale／TURN 路徑速度。
MB 使用十進位（1 MB = 1,000,000 bytes）；Mbps 是每秒百萬位元。
"""

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


DEFAULT_URL = "https://speed.cloudflare.com/__up"


def positive_number(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("必須是數字")
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必須是大於 0 的有限數字")
    return number


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("必須是整數")
    if number < 1:
        raise argparse.ArgumentTypeError("必須大於或等於 1")
    return number


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_payload(path, size_bytes):
    """以小區塊寫入隨機資料，不一次把整個測試檔案載入記憶體。"""
    with path.open("wb") as handle:
        remaining = size_bytes
        while remaining:
            chunk_size = min(remaining, 1024 * 1024)
            handle.write(os.urandom(chunk_size))
            remaining -= chunk_size


def upload_once(curl, payload, size_bytes, args, trial):
    command = [
        curl, "--disable", "--silent", "--show-error",
        "--output", os.devnull, "--write-out", "%{json}",
        "--connect-timeout", str(min(10, args.timeout)),
        "--max-time", str(args.timeout),
        "--request", "POST", "--header", "Content-Type: application/octet-stream",
        "--header", "Expect:", "--data-binary", "@" + str(payload),
    ]
    if args.ip_version != "auto":
        command.append("--ipv4" if args.ip_version == "4" else "--ipv6")
    command.append(args.url)
    result = {"trial": trial, "started_at": timestamp(), "ok": False}
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=args.timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return {**result, "error": "上傳逾時"}
    result["curl_exit_code"] = completed.returncode
    try:
        metrics = json.loads(completed.stdout)
        http_code = int(metrics["http_code"])
        uploaded = int(metrics["size_upload"])
        seconds = float(metrics["time_total"])
    except (ValueError, KeyError, TypeError):
        return {**result, "error": completed.stderr.strip() or "無法讀取 curl 測量結果"}
    result.update(http_code=http_code, uploaded_bytes=uploaded, seconds=seconds,
                  remote_ip=metrics.get("remote_ip", ""),
                  dns_seconds=metrics.get("time_namelookup"),
                  connect_seconds=metrics.get("time_connect"),
                  tls_seconds=metrics.get("time_appconnect"))
    if completed.returncode:
        result["error"] = completed.stderr.strip() or f"curl 錯誤 {completed.returncode}"
    elif not 200 <= http_code < 300:
        result["error"] = f"伺服器回傳 HTTP {http_code}"
    elif uploaded != size_bytes:
        result["error"] = f"資料未完整上傳：{uploaded}/{size_bytes} bytes"
    elif not math.isfinite(seconds) or seconds <= 0:
        result["error"] = "無效的測量時間"
    else:
        result.update(ok=True, upload_mbps=uploaded * 8 / seconds / 1_000_000,
                      upload_mb_per_second=uploaded / seconds / 1_000_000)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="測量對外上傳速度（預設 3 次，每次 10 MB，使用 IPv4）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--size-mb", type=positive_number, default=10,
                        help="每次上傳的資料量，單位 MB")
    parser.add_argument("--runs", type=positive_int, default=3, help="測試次數")
    parser.add_argument("--timeout", type=positive_number, default=60,
                        help="每次請求的逾時秒數")
    parser.add_argument("--ip-version", choices=("4", "6", "auto"), default="4",
                        help="IP 版本")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="接受 HTTP POST 測試資料的端點")
    parser.add_argument("--output", type=Path, help="另存 JSON 結果的檔案路徑")
    args = parser.parse_args()
    try:
        endpoint = urlsplit(args.url)
        valid_url = endpoint.scheme in ("http", "https") and bool(endpoint.hostname)
    except ValueError:
        valid_url = False
    if not valid_url:
        parser.error("--url 必須是有效的 http:// 或 https:// 網址")
    size_bytes = int(args.size_mb * 1_000_000)
    if size_bytes < 1:
        parser.error("--size-mb 至少須提供 1 byte 的資料量")
    curl = shutil.which("curl")
    if curl is None:
        parser.error("找不到 curl，請先安裝 curl")

    report = {"started_at": timestamp(), "endpoint": args.url,
              "ip_version": args.ip_version, "bytes_per_trial": size_bytes,
              "requested_trials": args.runs, "trials": [],
              "measurement": "單條 HTTP 連線；速度包含 DNS、建連與伺服器回應時間"}
    print(f"測試端點：{args.url}", flush=True)
    print(f"每次 {size_bytes / 1_000_000:.2f} MB，共 {args.runs} 次，"
          f"測試資料合計 {size_bytes * args.runs / 1_000_000:.2f} MB；"
          f"IP 版本：{args.ip_version}", flush=True)
    with tempfile.TemporaryDirectory(prefix="uav-upload-speed-") as directory:
        payload = Path(directory) / "payload.bin"
        make_payload(payload, size_bytes)
        for trial in range(1, args.runs + 1):
            print(f"[{trial}/{args.runs}] 上傳中…", flush=True)
            result = upload_once(curl, payload, size_bytes, args, trial)
            report["trials"].append(result)
            if result["ok"]:
                print(f"  {result['upload_mbps']:.2f} Mbps "
                      f"({result['upload_mb_per_second']:.2f} MB/s)，"
                      f"耗時 {result['seconds']:.3f} 秒，"
                      f"伺服器 {result['remote_ip']}", flush=True)
            else:
                print(f"  測試失敗：{result['error']}", flush=True)
            if trial < args.runs:
                time.sleep(1)

    successful = [trial for trial in report["trials"] if trial["ok"]]
    report.update(finished_at=timestamp(), successful_trials=len(successful),
                  failed_trials=args.runs - len(successful))
    if successful:
        speeds = [trial["upload_mbps"] for trial in successful]
        summary = {
            "median_mbps": statistics.median(speeds),
            "min_mbps": min(speeds), "max_mbps": max(speeds),
            "overall_mbps": sum(trial["uploaded_bytes"] for trial in successful) * 8
            / sum(trial["seconds"] for trial in successful) / 1_000_000,
        }
        report["summary"] = summary
        print(f"\n成功 {len(successful)}/{args.runs} 次", flush=True)
        print(f"上傳速度中位數：{summary['median_mbps']:.2f} Mbps", flush=True)
        print(f"最低／最高：{summary['min_mbps']:.2f}／{summary['max_mbps']:.2f} Mbps", flush=True)
        print(f"總資料量／總請求時間：{summary['overall_mbps']:.2f} Mbps", flush=True)
    else:
        print("\n沒有成功的測試，無法計算上傳速度。", flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(f"結果已儲存：{args.output.resolve()}", flush=True)
    return 0 if len(successful) == args.runs else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已停止測試。", file=sys.stderr)
        sys.exit(130)
    except OSError as error:
        print(f"錯誤：{error}", file=sys.stderr)
        sys.exit(1)
