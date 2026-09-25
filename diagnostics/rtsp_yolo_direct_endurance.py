#!/usr/bin/env python3
"""Measure 20-minute browser/source-PTS sync for rtsp_yolo_direct."""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import sys
import time

import aiohttp


SNAPSHOT = """(() => {
  const current = typeof videoPts === 'number' ? videoPts : null;
  const same = current === null ? null : [...detections].reverse().find(
    item => item.generation === generation && item.ptsSeconds <= current + 0.005);
  const matched = same && current - same.ptsSeconds < 1 ? same : null;
  return {
    state: peer?.connectionState ?? null,
    iceState: peer?.iceConnectionState ?? null,
    videoReadyState: video.readyState,
    videoCurrentTime: video.currentTime,
    videoWidth: video.videoWidth,
    videoPts: current,
    yoloPts: matched?.ptsSeconds ?? null,
    gapMs: matched ? (current-matched.ptsSeconds)*1000 : null,
    inferenceMs: matched?.inferenceMs ?? null,
    yoloFps: matched?.yoloFps ?? null,
    videoFps,
    origin,
    generation,
    resultsBuffered: detections.length,
    status: status.textContent,
    transportStatus: document.getElementById('transport')?.textContent,
    pageUrl: location.href
  };
})()"""


async def cdp_call(session, url, method, params=None):
    async with session.ws_connect(url, timeout=8) as socket:
        await socket.send_json({"id": 1, "method": method, "params": params or {}})
        while True:
            message = await socket.receive(timeout=60 if method == "Page.navigate" else 8)
            if message.type != aiohttp.WSMsgType.TEXT:
                raise RuntimeError(f"CDP message: {message.type}")
            reply = json.loads(message.data)
            if reply.get("id") == 1:
                return reply


async def page_target(session, port):
    async with session.get(f"http://127.0.0.1:{port}/json") as response:
        response.raise_for_status()
        pages = await response.json()
    return next((page for page in pages if page.get("type") == "page"), None)


async def browser_snapshot(session, websocket_url):
    reply = await cdp_call(session, websocket_url, "Runtime.evaluate",
                           {"expression": SNAPSHOT, "returnByValue": True})
    result = reply.get("result", {}).get("result", {})
    if "value" not in result:
        raise RuntimeError(f"Browser evaluation failed: {reply}")
    return result["value"]


async def stop_process(process, timeout=12):
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


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    low = int(position)
    high = min(low+1, len(ordered)-1)
    weight = position-low
    return round(ordered[low]*(1-weight) + ordered[high]*weight, 2)


def summarize(samples, target_seconds):
    gaps = [sample["browser"]["gapMs"] for sample in samples
            if isinstance(sample.get("browser"), dict)
            and isinstance(sample["browser"].get("gapMs"), (int, float))]
    connected = [sample for sample in samples
                 if sample.get("browser", {}).get("state") == "connected"]
    healthy = [sample for sample in samples
               if sample.get("health", {}).get("healthy") is True]
    freezes = []
    backwards = []
    previous = None
    last_advance = None
    freezing = False
    for sample in samples:
        browser = sample.get("browser", {})
        pts = browser.get("videoPts")
        if not isinstance(pts, (int, float)):
            continue
        if previous and browser.get("generation") == previous["generation"]:
            delta = pts-previous["pts"]
            if delta < -0.1:
                backwards.append({"elapsedS": sample["elapsedS"],
                                  "deltaS": round(delta, 3)})
            if delta > 0.01:
                last_advance = sample["elapsedS"]
                freezing = False
            elif last_advance is not None and sample["elapsedS"]-last_advance > 4 and not freezing:
                freezes.append({"elapsedS": sample["elapsedS"],
                                "stalledForS": round(sample["elapsedS"]-last_advance, 2)})
                freezing = True
        else:
            last_advance = sample["elapsedS"]
            freezing = False
        previous = {"pts": pts, "elapsed": sample["elapsedS"],
                    "generation": browser.get("generation")}
    rtsp_statuses = [sample["health"]["rtsp"] for sample in samples
                     if isinstance(sample.get("health", {}).get("rtsp"), dict)]
    first_unhealthy = next((sample["elapsedS"] for sample in samples
                            if sample.get("health", {}).get("healthy") is False), None)
    last_packet_advance = None
    last_packet_count = -1
    last_video_advance = None
    last_video_pts = None
    last_video_generation = None
    for sample in samples:
        packet_count = sample.get("health", {}).get("rtsp", {}).get("packets")
        if isinstance(packet_count, int) and packet_count > last_packet_count:
            last_packet_count = packet_count
            last_packet_advance = sample["elapsedS"]
        browser = sample.get("browser", {})
        pts = browser.get("videoPts")
        generation = browser.get("generation")
        if isinstance(pts, (int, float)) and (
            generation != last_video_generation or
            last_video_pts is None or pts > last_video_pts + .01
        ):
            last_video_pts = pts
            last_video_generation = generation
            last_video_advance = sample["elapsedS"]
    return {
        "targetDurationS": target_seconds,
        "observedDurationS": round(samples[-1]["elapsedS"] if samples else 0, 2),
        "samples": len(samples),
        "connectedSamples": len(connected),
        "healthySamples": len(healthy),
        "unhealthySamples": sum(sample.get("health", {}).get("healthy") is False
                                for sample in samples),
        "notConnectedSamples": len(samples)-len(connected),
        "firstUnhealthyElapsedS": first_unhealthy,
        "lastRtspPacketAdvanceS": last_packet_advance,
        "lastVideoPtsAdvanceS": last_video_advance,
        "matchedPtsSamples": len(gaps),
        "gapMs": {"median": percentile(gaps, .5),
                  "p95": percentile(gaps, .95),
                  "p99": percentile(gaps, .99),
                  "max": round(max(gaps), 2) if gaps else None,
                  "over100": sum(value > 100 for value in gaps),
                  "over250": sum(value > 250 for value in gaps),
                  "over500": sum(value > 500 for value in gaps)},
        "videoPtsBackwards": backwards,
        "videoFreezeSamples": freezes,
        "rtspReconnectsEnd": rtsp_statuses[-1].get("reconnects") if rtsp_statuses else None,
        "rtspPacketsEnd": rtsp_statuses[-1].get("packets") if rtsp_statuses else None,
        "yoloFramesEnd": samples[-1].get("health", {}).get("yolo", {}).get("processed_frames") if samples else None,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--port", type=int, default=18085)
    parser.add_argument("--debug-port", type=int, default=19285)
    parser.add_argument("--browser-host", default="127.0.0.1",
                        help="address used by Chrome to open the test page")
    parser.add_argument("--model-path", default="yolo11s.engine")
    args = parser.parse_args()
    browser_url = f"http://{args.browser_host}:{args.port}/"
    run_dir = Path("diagnostics") / datetime.now().strftime(
        "direct_sync_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True)
    print(f"Run directory: {run_dir}", flush=True)
    server_log = (run_dir / "server_console.log").open("w", buffering=1)
    chrome_log = (run_dir / "chrome.log").open("w", buffering=1)
    samples_file = (run_dir / "samples.jsonl").open("w", buffering=1)
    server = chrome = None
    samples = []
    failure = None
    runtime = Path(f"/tmp/direct-sync-runtime-{os.getpid()}")
    profile = Path(f"/tmp/direct-sync-profile-{os.getpid()}")
    runtime.mkdir(mode=0o700)
    profile.mkdir()
    try:
        server = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", "rtsp_yolo_direct",
            "--rtsp-url", args.rtsp_url,
            "--host", "127.0.0.1" if args.browser_host == "127.0.0.1" else "0.0.0.0",
            "--port", str(args.port), "--model-path", args.model_path,
            "--log-dir", str(run_dir),
            stdout=server_log, stderr=asyncio.subprocess.STDOUT)
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            health_url = f"http://127.0.0.1:{args.port}/api/health"
            for _ in range(90):
                if server.returncode is not None:
                    raise RuntimeError(f"server exited: {server.returncode}")
                try:
                    async with session.get(health_url) as response:
                        health = await response.json()
                    if health.get("healthy") and health["rtsp"]["packets"] > 30:
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(1)
            else:
                raise RuntimeError("server did not become healthy within 90 seconds")
            browser_binary = (shutil.which("google-chrome") or
                              shutil.which("chromium") or
                              shutil.which("chromium-browser"))
            if browser_binary is None:
                raise RuntimeError("Chrome/Chromium executable not found")
            chrome = await asyncio.create_subprocess_exec(
                browser_binary, "--headless=new", "--no-sandbox",
                "--disable-dev-shm-usage", "--no-proxy-server", "--no-first-run",
                "--autoplay-policy=no-user-gesture-required",
                f"--remote-debugging-port={args.debug_port}",
                f"--user-data-dir={profile}",
                browser_url,
                stdout=chrome_log, stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)})
            target = None
            for _ in range(30):
                try:
                    target = await page_target(session, args.debug_port)
                except aiohttp.ClientError:
                    pass
                if target:
                    break
                await asyncio.sleep(1)
            if not target:
                raise RuntimeError("Chrome DevTools did not start")
            websocket = target["webSocketDebuggerUrl"]
            await cdp_call(session, websocket, "Page.navigate",
                           {"url": browser_url})
            for _ in range(60):
                try:
                    browser = await browser_snapshot(session, websocket)
                    if (browser.get("state") == "connected" and
                        browser.get("videoPts") is not None and
                        browser.get("gapMs") is not None):
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
            else:
                raise RuntimeError("browser did not reach synchronized playback")
            started = time.monotonic()
            target_seconds = args.minutes*60
            next_sample = started
            last_progress = -1
            while time.monotonic()-started < target_seconds:
                await asyncio.sleep(max(0, next_sample-time.monotonic()))
                if server.returncode is not None:
                    raise RuntimeError(f"server exited: {server.returncode}")
                if chrome.returncode is not None:
                    raise RuntimeError(f"Chrome exited: {chrome.returncode}")
                elapsed = time.monotonic()-started
                sample = {"elapsedS": round(elapsed, 3),
                          "time": datetime.now().astimezone().isoformat(
                              timespec="milliseconds")}
                try:
                    async with session.get(health_url) as response:
                        sample["health"] = await response.json()
                except Exception as exc:
                    sample["healthError"] = repr(exc)
                try:
                    sample["browser"] = await browser_snapshot(session, websocket)
                except Exception as exc:
                    sample["browserError"] = repr(exc)
                samples.append(sample)
                samples_file.write(json.dumps(sample, ensure_ascii=False)+"\n")
                minute = int(elapsed//60)
                if minute > last_progress:
                    last_progress = minute
                    gap = sample.get("browser", {}).get("gapMs")
                    print(f"minute {minute}/{args.minutes:g}: "
                          f"gap={None if gap is None else round(gap, 1)} ms, "
                          f"browser={sample.get('browser', {}).get('state')}, "
                          f"healthy={sample.get('health', {}).get('healthy')}",
                          flush=True)
                next_sample += 1
    except BaseException as exc:
        failure = repr(exc)
        print(f"Test stopped: {failure}", flush=True)
    finally:
        await stop_process(chrome)
        await stop_process(server)
        summary = summarize(samples, args.minutes*60)
        summary["failure"] = failure
        summary["serverExitCode"] = None if server is None else server.returncode
        summary["chromeExitCode"] = None if chrome is None else chrome.returncode
        (run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
        samples_file.close()
        chrome_log.close()
        server_log.close()
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    asyncio.run(main())
