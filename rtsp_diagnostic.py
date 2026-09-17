#!/usr/bin/env python3
"""End-to-end diagnostic runner for rtsp_minimal.py.

Produces a timestamped directory under diagnostics/ containing raw logs and a
machine-readable event stream.  The test intentionally separates a direct
camera packet probe from the complete RTSP -> NVDEC -> NVENC -> WebRTC path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription


def stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, path: Path):
        self.handle = path.open("w", encoding="utf-8", buffering=1)

    def write(self, kind: str, **fields):
        self.handle.write(json.dumps({"time": stamp(), "kind": kind, **fields}) + "\n")

    def close(self):
        self.handle.close()


def read_proc_sample(pid: int) -> dict:
    result: dict = {}
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        result["proc_cpu_ticks"] = int(fields[13]) + int(fields[14])
        result["proc_rss_bytes"] = int(fields[23]) * os.sysconf("SC_PAGE_SIZE")
        result["proc_threads"] = len(list(Path(f"/proc/{pid}/task").iterdir()))
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        result["process_missing"] = True
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0]) * 1024
        result["mem_available_bytes"] = meminfo["MemAvailable"]
        result["swap_free_bytes"] = meminfo["SwapFree"]
    except (OSError, KeyError, ValueError):
        pass
    return result


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


async def direct_camera_probe(url: str, seconds: int, directory: Path, events: EventLog):
    packet_log = (directory / "camera_packets.csv").open("w", encoding="utf-8", buffering=1)
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
    pipeline = Gst.parse_launch(
        f'rtspsrc location="{escaped_url}" protocols=tcp latency=100 drop-on-latency=true '
        '! application/x-rtp,media=video,encoding-name=H264 '
        '! rtph264depay ! appsink name=sink max-buffers=100 drop=false sync=false'
    )
    sink = pipeline.get_by_name("sink")
    bus = pipeline.get_bus()
    events.write("camera_probe_start", seconds=seconds, pipeline="rtspsrc ! rtph264depay ! appsink")
    arrivals: list[float] = []
    pts_values: list[float] = []
    sizes: list[int] = []
    exit_code = 0
    pipeline.set_state(Gst.State.PLAYING)
    started = time.monotonic()
    try:
        while time.monotonic() - started < seconds:
            message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if message is not None:
                if message.type == Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    events.write("camera_pipeline_error", error=str(error), debug=debug)
                    exit_code = 1
                else:
                    events.write("camera_pipeline_eos")
                    exit_code = 2
                break
            sample = sink.emit("try-pull-sample", 100 * Gst.MSECOND)
            if sample is None:
                await asyncio.sleep(0)
                continue
            now = time.monotonic()
            buffer = sample.get_buffer()
            pts = None if buffer.pts == Gst.CLOCK_TIME_NONE else buffer.pts / Gst.SECOND
            size = buffer.get_size()
            packet_log.write(f"{stamp()},{now:.6f},{pts},{size}\n")
            arrivals.append(now)
            sizes.append(size)
            if pts is not None:
                pts_values.append(pts)
            await asyncio.sleep(0)
    finally:
        pipeline.set_state(Gst.State.NULL)
    packet_log.close()
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    summary = {
        "packets": len(arrivals),
        "duration_s": (arrivals[-1] - arrivals[0]) if len(arrivals) > 1 else 0,
        "requested_duration_s": seconds,
        "packet_rate": len(arrivals) / max(0.001, arrivals[-1] - arrivals[0]) if len(arrivals) > 1 else 0,
        "arrival_gap_max_ms": max(gaps, default=0) * 1000,
        "arrival_gap_p99_ms": (percentile(gaps, 0.99) or 0) * 1000,
        "bytes": sum(sizes),
        "exit_code": exit_code,
    }
    events.write("camera_probe_summary", **summary)
    return summary


async def wait_for_server(session: aiohttp.ClientSession, events: EventLog):
    for _ in range(100):
        try:
            async with session.get("http://127.0.0.1:8080/status") as response:
                if response.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(0.1)
    events.write("server_start_failed")
    raise RuntimeError("rtsp_minimal.py did not start within 10 seconds")


async def end_to_end_probe(url: str, seconds: int, directory: Path, events: EventLog):
    server_output = (directory / "rtsp_minimal.log").open("w", encoding="utf-8", buffering=1)
    tegra_output = (directory / "tegrastats.log").open("w", encoding="utf-8", buffering=1)
    server = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "rtsp_minimal.py", "--rtsp-url", url,
        stdout=server_output, stderr=subprocess.STDOUT,
    )
    tegra = await asyncio.create_subprocess_exec(
        "tegrastats", "--interval", "1000", stdout=tegra_output, stderr=subprocess.STDOUT
    )
    events.write("e2e_start", seconds=seconds, server_pid=server.pid)
    pc = RTCPeerConnection()
    frame_times: list[float] = []
    source_samples: list[tuple[float, int]] = []
    proc_samples: list[tuple[float, dict]] = []
    receiver_done = asyncio.Event()

    @pc.on("track")
    def on_track(track):
        events.write("webrtc_track", track_kind=track.kind)

        async def receive():
            try:
                while True:
                    frame = await track.recv()
                    now = time.monotonic()
                    frame_times.append(now)
                    if len(frame_times) == 1:
                        events.write("first_webrtc_frame", width=frame.width, height=frame.height)
            except Exception as exc:
                events.write("webrtc_receive_end", error=repr(exc))
            finally:
                receiver_done.set()

        asyncio.create_task(receive())

    pc.addTransceiver("video", direction="recvonly")
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await wait_for_server(session, events)
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            async with session.post(
                "http://127.0.0.1:8080/offer",
                json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            ) as response:
                response.raise_for_status()
                answer = await response.json()
            await pc.setRemoteDescription(RTCSessionDescription(**answer))
            started = time.monotonic()
            previous_frames = None
            last_frame_change = started
            while time.monotonic() - started < seconds and server.returncode is None:
                now = time.monotonic()
                try:
                    async with session.get("http://127.0.0.1:8080/status") as response:
                        status = await response.json()
                except Exception as exc:
                    events.write("status_error", error=repr(exc))
                    await asyncio.sleep(0.25)
                    continue
                frames = status.get("frames", 0)
                source_samples.append((now, frames))
                proc = read_proc_sample(server.pid)
                proc_samples.append((now, proc))
                if previous_frames is not None and frames == previous_frames and now - last_frame_change >= 0.5:
                    events.write("source_stall", stall_s=round(now - last_frame_change, 3), status=status)
                    last_frame_change = now  # rate-limit repeated events
                elif frames != previous_frames:
                    last_frame_change = now
                previous_frames = frames
                events.write("sample", source=status, webrtc_frames=len(frame_times), **proc)
                await asyncio.sleep(0.25)
    finally:
        await pc.close()
        if server.returncode is None:
            server.send_signal(signal.SIGINT)
        try:
            await asyncio.wait_for(server.wait(), timeout=5)
        except asyncio.TimeoutError:
            server.kill()
            await server.wait()
        if tegra.returncode is None:
            tegra.terminate()
        try:
            await asyncio.wait_for(tegra.wait(), timeout=3)
        except asyncio.TimeoutError:
            tegra.kill()
            await tegra.wait()
        server_output.close()
        tegra_output.close()

    frame_gaps = [b - a for a, b in zip(frame_times, frame_times[1:])]
    source_fps = 0.0
    if len(source_samples) > 1:
        source_fps = (source_samples[-1][1] - source_samples[0][1]) / (source_samples[-1][0] - source_samples[0][0])
    cpu_percentages = []
    clock_ticks = os.sysconf("SC_CLK_TCK")
    for (ta, a), (tb, b) in zip(proc_samples, proc_samples[1:]):
        if "proc_cpu_ticks" in a and "proc_cpu_ticks" in b:
            cpu_percentages.append((b["proc_cpu_ticks"] - a["proc_cpu_ticks"]) / clock_ticks / (tb - ta) * 100)
    summary = {
        "server_exit_code": server.returncode,
        "source_fps": source_fps,
        "source_frames": source_samples[-1][1] - source_samples[0][1] if len(source_samples) > 1 else 0,
        "webrtc_frames": len(frame_times),
        "webrtc_fps": len(frame_times) / max(0.001, frame_times[-1] - frame_times[0]) if len(frame_times) > 1 else 0,
        "webrtc_gap_max_ms": max(frame_gaps, default=0) * 1000,
        "webrtc_gap_p99_ms": (percentile(frame_gaps, 0.99) or 0) * 1000,
        "webrtc_gaps_over_100ms": sum(gap > 0.1 for gap in frame_gaps),
        "process_cpu_avg_percent": statistics.mean(cpu_percentages) if cpu_percentages else None,
        "process_cpu_max_percent": max(cpu_percentages, default=None),
        "process_rss_max_bytes": max((x.get("proc_rss_bytes", 0) for _, x in proc_samples), default=0),
    }
    events.write("e2e_summary", **summary)
    return summary


def analyze_tegra(path: Path) -> dict:
    text = path.read_text(errors="replace") if path.exists() else ""
    temps = [float(x) for x in re.findall(r"\w+@(\d+(?:\.\d+)?)C", text)]
    ram = [int(x) for x in re.findall(r"RAM (\d+)/", text)]
    gpu = [int(x) for x in re.findall(r"GR3D_FREQ (\d+)%", text)]
    power = [int(x) for x in re.findall(r"VDD_IN (\d+)mW", text)]
    return {
        "samples": len(text.splitlines()),
        "temperature_max_c": max(temps, default=None),
        "ram_used_max_mb": max(ram, default=None),
        "gpu_load_max_percent": max(gpu, default=None),
        "input_power_max_mw": max(power, default=None),
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--camera-seconds", type=int, default=30)
    parser.add_argument("--e2e-seconds", type=int, default=120)
    args = parser.parse_args()
    directory = Path("diagnostics") / datetime.now().strftime("%Y%m%d_%H%M%S")
    directory.mkdir(parents=True)
    events = EventLog(directory / "events.jsonl")
    try:
        camera = await direct_camera_probe(args.rtsp_url, args.camera_seconds, directory, events) if args.camera_seconds > 0 else None
        e2e = await end_to_end_probe(args.rtsp_url, args.e2e_seconds, directory, events) if args.e2e_seconds > 0 else None
        tegra = analyze_tegra(directory / "tegrastats.log") if args.e2e_seconds > 0 else None
        summary = {"created_at": stamp(), "rtsp_url": args.rtsp_url, "camera": camera, "end_to_end": e2e, "tegra": tegra}
        (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(directory)
        print(json.dumps(summary, indent=2))
    finally:
        events.close()


if __name__ == "__main__":
    asyncio.run(main())
