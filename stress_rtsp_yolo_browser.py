#!/usr/bin/env python3
"""Run a real-Chromium endurance test against yolo_final_rtsp_resilient.py."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

import aiohttp


class JsonLog:
    def __init__(self, path):
        self.handle = path.open("w", encoding="utf-8", buffering=1)

    def write(self, kind, **fields):
        self.handle.write(json.dumps({
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic": round(time.monotonic(), 6),
            "kind": kind,
            **fields,
        }, ensure_ascii=False) + "\n")

    def close(self):
        self.handle.close()


async def terminate(process, timeout=10):
    if process is None or process.returncode is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        await asyncio.wait_for(process.wait(), timeout)
    except asyncio.TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def wait_for_healthy(session, url, log, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            async with session.get(url) as response:
                last = await response.json()
            if last.get("healthy") and last.get("rtsp", {}).get("frames", 0) > 0:
                return last
        except Exception as exc:
            last = {"error": repr(exc)}
        await asyncio.sleep(1)
    log.write("startup_unhealthy", health=last)
    raise RuntimeError(f"camera/YOLO did not become healthy: {last}")


async def devtools_target(session, port):
    async with session.get(f"http://127.0.0.1:{port}/json") as response:
        targets = await response.json()
    for target in targets:
        if target.get("type") == "page":
            return target
    return None


async def cdp_call(session, websocket_url, method, params=None):
    async with session.ws_connect(websocket_url, timeout=5) as socket:
        await socket.send_json({"id": 1, "method": method, "params": params or {}})
        while True:
            message = await socket.receive(timeout=60 if method == "Page.navigate" else 5)
            if message.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(message.data)
                if data.get("id") == 1:
                    return data
            else:
                raise RuntimeError(f"unexpected CDP websocket message: {message.type}")


async def browser_snapshot(session, port):
    target = await devtools_target(session, port)
    if target is None:
        return {"error": "no Chromium page target"}
    expression = """(() => ({
      url: location.href,
      peerState: (typeof peer !== 'undefined' && peer) ? peer.connectionState : null,
      iceState: (typeof peer !== 'undefined' && peer) ? peer.iceConnectionState : null,
      videoCurrentTime: document.querySelector('video')?.currentTime ?? null,
      videoReadyState: document.querySelector('video')?.readyState ?? null,
      videoWidth: document.querySelector('video')?.videoWidth ?? null,
      videoHeight: document.querySelector('video')?.videoHeight ?? null,
      status: document.getElementById('connection-status')?.textContent ?? null
    }))()"""
    reply = await cdp_call(
        session, target["webSocketDebuggerUrl"], "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
    )
    try:
        return reply["result"]["result"]["value"]
    except KeyError:
        return {"error": reply}


async def reload_browser(session, port):
    target = await devtools_target(session, port)
    if target is None:
        raise RuntimeError("no Chromium page target")
    await cdp_call(session, target["webSocketDebuggerUrl"], "Page.reload", {"ignoreCache": True})


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--refresh-seconds", type=float, default=45)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--debug-port", type=int, default=9223)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--browser-host", default="127.0.0.1",
                        help="address Chromium uses to open the video page")
    args = parser.parse_args()
    browser_url = f"http://{args.browser_host}:{args.port}/"

    run_dir = Path("diagnostics") / datetime.now().strftime("browser_stress_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True)
    log = JsonLog(run_dir / "stress_events.jsonl")
    server_file = (run_dir / "server_console.log").open("w", encoding="utf-8", buffering=1)
    chrome_file = (run_dir / "chromium.log").open("w", encoding="utf-8", buffering=1)
    tegra_file = (run_dir / "tegrastats.log").open("w", encoding="utf-8", buffering=1)
    server = chromium = tegra = None
    samples = []
    errors = []
    refreshes = 0
    input_stalled = False
    started = time.monotonic()
    try:
        server = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "yolo_final_rtsp_resilient.py",
            "--rtsp-url", args.rtsp_url, "--port", str(args.port),
            "--log-dir", str(run_dir / "server_diagnostics"),
            stdout=server_file, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "MPLCONFIGDIR": "/tmp/matplotlib-cache"},
        )
        tegra = await asyncio.create_subprocess_exec(
            "tegrastats", "--interval", "1000",
            stdout=tegra_file, stderr=asyncio.subprocess.STDOUT,
        )
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            health_url = f"http://127.0.0.1:{args.port}/api/health"
            initial = await wait_for_healthy(session, health_url, log)
            log.write("server_healthy", health=initial)

            chromium_path = (shutil.which("chromium") or shutil.which("chromium-browser")
                             or shutil.which("google-chrome"))
            if chromium_path is None:
                raise RuntimeError("Chromium executable not found")
            runtime_dir = Path(f"/tmp/chromium-runtime-{os.getpid()}")
            profile_dir = Path(f"/tmp/chromium-profile-{os.getpid()}")
            runtime_dir.mkdir(mode=0o700)
            profile_dir.mkdir()
            chromium = await asyncio.create_subprocess_exec(
                chromium_path,
                "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--no-proxy-server", "--no-first-run",
                "--autoplay-policy=no-user-gesture-required",
                f"--remote-debugging-port={args.debug_port}",
                f"--user-data-dir={profile_dir}",
                browser_url,
                stdout=chrome_file, stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "XDG_RUNTIME_DIR": str(runtime_dir)},
            )
            for _ in range(30):
                try:
                    if await devtools_target(session, args.debug_port):
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
            else:
                raise RuntimeError("Chromium DevTools did not start")

            target = await devtools_target(session, args.debug_port)
            await cdp_call(session, target["webSocketDebuggerUrl"], "Page.navigate",
                           {"url": browser_url})
            for _ in range(60):
                snapshot = await browser_snapshot(session, args.debug_port)
                if (snapshot.get("peerState") == "connected"
                        and (snapshot.get("videoCurrentTime") or 0) > 0
                        and (snapshot.get("videoWidth") or 0) > 0):
                    log.write("browser_playing", browser=snapshot)
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError(f"Chromium did not start playback: {snapshot}")

            test_started = time.monotonic()
            end_at = test_started + args.minutes * 60
            next_refresh = test_started + args.refresh_seconds
            previous_video_time = None
            stagnant_samples = 0
            while time.monotonic() < end_at:
                if server.returncode is not None:
                    raise RuntimeError(f"server exited early: {server.returncode}")
                if chromium.returncode is not None:
                    raise RuntimeError(f"Chromium exited early: {chromium.returncode}")
                try:
                    async with session.get(health_url) as response:
                        health = await response.json()
                    browser = await browser_snapshot(session, args.debug_port)
                    sample = {"elapsed_s": round(time.monotonic() - test_started, 3), "health": health, "browser": browser}
                    samples.append(sample)
                    log.write("sample", **sample)
                    yolo_age = health.get("yolo", {}).get("last_frame_age_s")
                    currently_stalled = yolo_age is None or yolo_age >= 5
                    if currently_stalled and not input_stalled:
                        input_stalled = True
                        message = f"input stalled near {sample['elapsed_s']}s (YOLO age={yolo_age})"
                        errors.append(message)
                        log.write("input_stall", **sample)
                    elif not currently_stalled and input_stalled:
                        input_stalled = False
                        log.write("input_recovered", **sample)
                    video_time = browser.get("videoCurrentTime")
                    if browser.get("peerState") == "connected" and video_time is not None:
                        if previous_video_time is not None and video_time <= previous_video_time:
                            stagnant_samples += 1
                        else:
                            stagnant_samples = 0
                        if stagnant_samples >= 5:
                            errors.append(f"video stagnant near {sample['elapsed_s']}s")
                            log.write("video_stagnant", **sample)
                        previous_video_time = video_time
                except Exception as exc:
                    errors.append(f"sample error: {exc!r}")
                    log.write("sample_error", error=repr(exc))

                if time.monotonic() >= next_refresh:
                    try:
                        await reload_browser(session, args.debug_port)
                        refreshes += 1
                        log.write("browser_reload", count=refreshes)
                    except Exception as exc:
                        errors.append(f"reload error: {exc!r}")
                        log.write("browser_reload_error", error=repr(exc))
                    next_refresh += args.refresh_seconds
                await asyncio.sleep(1)

        max_peers = max((len(x["health"].get("peers", [])) for x in samples), default=0)
        encoder_errors = sum(len(x["health"].get("recent_encoder_errors", [])) for x in samples[-1:])
        connected_samples = sum(x["browser"].get("peerState") == "connected" for x in samples)
        advancing_samples = 0
        previous = None
        for sample in samples:
            current = sample["browser"].get("videoCurrentTime")
            if previous is not None and current is not None and current > previous:
                advancing_samples += 1
            if current is not None:
                previous = current
        summary = {
            "requested_minutes": args.minutes,
            "elapsed_s": round(time.monotonic() - test_started, 3),
            "samples": len(samples),
            "browser_refreshes": refreshes,
            "max_server_peers": max_peers,
            "connected_samples": connected_samples,
            "video_advancing_samples": advancing_samples,
            "encoder_errors": encoder_errors,
            "input_stalled_at_end": input_stalled,
            "observed_errors": errors,
            "server_exit_code_before_cleanup": server.returncode,
            "chromium_exit_code_before_cleanup": chromium.returncode,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.write("summary", **summary)
        print(run_dir)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    except Exception as exc:
        log.write("fatal", error=repr(exc), elapsed_s=round(time.monotonic() - started, 3))
        (run_dir / "FAILED.txt").write_text(repr(exc) + "\n", encoding="utf-8")
        raise
    finally:
        await terminate(chromium)
        await terminate(server)
        await terminate(tegra)
        server_file.close()
        chrome_file.close()
        tegra_file.close()
        log.close()


if __name__ == "__main__":
    asyncio.run(main())
