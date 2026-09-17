#!/usr/bin/env python3
"""Resilient RTSP + YOLO + Jetson H.264 WebRTC server.

This keeps ``yolo_final_rtsp.py`` unchanged and adds the failure containment
needed for unattended operation: one peer / NVENC session at a time, bounded
encoder queues, encoder-output and connection watchdogs, browser reconnect,
and structured health/error logging.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import threading
import time
import uuid
import weakref

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
import aiortc.rtcrtpsender as rtcrtpsender

from minimal_control_ui import build_page
import webrtc_yolo_minimal_jetson_h264 as h264_hw
import yolo_final as original
import yolo_final_rtsp as base


ENCODER_STALL_SECONDS = 3.0
CONNECT_TIMEOUT_SECONDS = 15.0
DISCONNECT_GRACE_SECONDS = 5.0

settings = None
event_log = None
offer_lock = None
watchdog_task = None
peer_meta = {}
closing_peers = set()
encoders = weakref.WeakValueDictionary()
recent_encoder_errors = []
input_stalled = False


class JsonEventLog:
    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()

    def write(self, kind, **fields):
        record = {
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic": round(time.monotonic(), 6),
            "kind": kind,
            **fields,
        }
        with self.lock:
            self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self):
        with self.lock:
            self.handle.close()


def log_event(kind, **fields):
    if event_log is not None:
        event_log.write(kind, **fields)


class MonitoredYoloGpsProcessor(original.YoloGpsProcessor):
    def __init__(self, parsed_settings):
        self.processed_frames = 0
        self.last_processed_at = None
        self.last_process_error = None
        super().__init__(parsed_settings)

    def _process(self, frame):
        try:
            annotated = super()._process(frame)
        except Exception as exc:
            self.last_process_error = repr(exc)
            log_event("yolo_error", error=repr(exc))
            raise
        self.processed_frames += 1
        self.last_processed_at = time.monotonic()
        self.last_process_error = None
        return annotated


class ResilientJetsonH264Encoder(h264_hw.JetsonH264Encoder):
    def __init__(self, bitrate=h264_hw.DEFAULT_H264_BITRATE):
        self.encoder_id = uuid.uuid4().hex[:10]
        self.created_at = time.monotonic()
        self.last_input_at = None
        self.last_output_at = None
        self.input_frames = 0
        self.output_access_units = 0
        self.last_error = None
        self.closed_at = None
        super().__init__(bitrate)
        encoders[self.encoder_id] = self
        log_event("encoder_created", encoder_id=self.encoder_id, bitrate=self._target_bitrate)

    def _pipeline_text(self, width, height):
        text = super()._pipeline_text(width, height)
        # Never let an unhealthy NVENC pipeline block aiortc's sender thread.
        return text.replace(
            "appsrc name=src is-live=false block=true format=time ",
            "appsrc name=src is-live=false block=false max-buffers=1 "
            "leaky-type=downstream format=time ",
        )

    def encode(self, frame, force_keyframe=False):
        now = time.monotonic()
        self.last_input_at = now
        self.input_frames += 1
        try:
            payloads, timestamp = super().encode(frame, force_keyframe)
            now = time.monotonic()
            if payloads:
                self.last_output_at = now
                self.output_access_units += 1
                self.last_error = None
            baseline = self.last_output_at or self.created_at
            if self.input_frames > 5 and now - baseline > ENCODER_STALL_SECONDS:
                raise RuntimeError(
                    f"NVENC produced no access unit for {now - baseline:.2f}s"
                )
            return payloads, timestamp
        except Exception as exc:
            self.last_error = repr(exc)
            recent_encoder_errors.append({
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "encoder_id": self.encoder_id,
                "error": repr(exc),
            })
            del recent_encoder_errors[:-20]
            log_event(
                "encoder_error",
                encoder_id=self.encoder_id,
                input_frames=self.input_frames,
                output_access_units=self.output_access_units,
                error=repr(exc),
            )
            raise

    def close(self):
        was_open = getattr(self, "pipeline", None) is not None
        super().close()
        if was_open:
            self.closed_at = time.monotonic()
            log_event(
                "encoder_closed",
                encoder_id=self.encoder_id,
                input_frames=self.input_frames,
                output_access_units=self.output_access_units,
                error=self.last_error,
            )


def encoder_factory(codec):
    if codec.mimeType.lower() == "video/h264":
        return ResilientJetsonH264Encoder(settings.h264_bitrate)
    return h264_hw.software_get_encoder(codec)


def encoder_snapshot():
    now = time.monotonic()
    return [
        {
            "id": encoder.encoder_id,
            "input_frames": encoder.input_frames,
            "output_access_units": encoder.output_access_units,
            "last_input_age_s": None if encoder.last_input_at is None else round(now - encoder.last_input_at, 3),
            "last_output_age_s": None if encoder.last_output_at is None else round(now - encoder.last_output_at, 3),
            "error": encoder.last_error,
            "pipeline_active": encoder.pipeline is not None,
        }
        for encoder in list(encoders.values())
    ]


async def close_peer(pc, reason):
    if pc in closing_peers:
        return
    closing_peers.add(pc)
    meta = peer_meta.get(pc, {})
    log_event(
        "peer_closing",
        peer_id=meta.get("id"),
        reason=reason,
        connection_state=pc.connectionState,
        ice_state=pc.iceConnectionState,
    )
    try:
        await asyncio.wait_for(pc.close(), timeout=5.0)
    except asyncio.TimeoutError:
        log_event("peer_close_timeout", peer_id=meta.get("id"), reason=reason)
    except Exception as exc:
        log_event("peer_close_error", peer_id=meta.get("id"), reason=reason, error=repr(exc))
    finally:
        original.pcs.discard(pc)
        peer_meta.pop(pc, None)
        closing_peers.discard(pc)


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    async with offer_lock:
        # This application has one operator view.  Closing the old peer first
        # guarantees that a browser refresh cannot accumulate NVENC sessions.
        for old_pc in list(original.pcs):
            await close_peer(old_pc, "superseded_by_new_offer")

        pc = RTCPeerConnection()
        peer_id = uuid.uuid4().hex[:10]
        now = time.monotonic()
        peer_meta[pc] = {
            "id": peer_id,
            "created_at": now,
            "connected_at": None,
            "disconnected_at": None,
        }
        original.pcs.add(pc)
        log_event("peer_created", peer_id=peer_id, remote=request.remote)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            meta = peer_meta.get(pc)
            log_event("peer_connection_state", peer_id=peer_id, state=pc.connectionState)
            if meta is not None and pc.connectionState == "connected":
                meta["connected_at"] = time.monotonic()
            if pc.connectionState in ("failed", "closed"):
                await close_peer(pc, f"connection_{pc.connectionState}")

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            meta = peer_meta.get(pc)
            log_event("peer_ice_state", peer_id=peer_id, state=pc.iceConnectionState)
            if meta is not None:
                if pc.iceConnectionState == "disconnected":
                    meta["disconnected_at"] = time.monotonic()
                elif pc.iceConnectionState in ("connected", "completed"):
                    meta["disconnected_at"] = None
            if pc.iceConnectionState in ("failed", "closed"):
                await close_peer(pc, f"ice_{pc.iceConnectionState}")

        try:
            video = pc.addTransceiver("video", direction="sendonly")
            video.setCodecPreferences(h264_hw.constrained_baseline_codecs())
            await pc.setRemoteDescription(remote_offer)
            video.sender.replaceTrack(original.CameraVideoTrack(original.processor))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            log_event("offer_answered", peer_id=peer_id)
            return web.json_response({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            })
        except Exception as exc:
            log_event("offer_error", peer_id=peer_id, error=repr(exc))
            await close_peer(pc, "offer_error")
            raise


async def health(_request):
    now = time.monotonic()
    processor = original.processor
    rtsp = None
    if processor is not None:
        try:
            rtsp = processor.camera_manager.status().get("rtsp")
        except Exception as exc:
            rtsp = {"error": repr(exc)}
    peers = [
        {
            "id": meta["id"],
            "connection_state": pc.connectionState,
            "ice_state": pc.iceConnectionState,
            "age_s": round(now - meta["created_at"], 3),
        }
        for pc, meta in list(peer_meta.items())
    ]
    return web.json_response({
        "healthy": bool(processor and processor.last_processed_at and now - processor.last_processed_at < 3),
        "rtsp": rtsp,
        "yolo": None if processor is None else {
            "processed_frames": processor.processed_frames,
            "last_frame_age_s": None if processor.last_processed_at is None else round(now - processor.last_processed_at, 3),
            "last_error": processor.last_process_error,
        },
        "peers": peers,
        "encoders": encoder_snapshot(),
        "recent_encoder_errors": recent_encoder_errors,
    })


async def watchdog_loop():
    global input_stalled
    while True:
        await asyncio.sleep(1.0)
        now = time.monotonic()
        processor = original.processor
        yolo_fresh = bool(
            processor
            and processor.last_processed_at
            and now - processor.last_processed_at < 3.0
        )
        yolo_age = (
            None
            if not processor or processor.last_processed_at is None
            else now - processor.last_processed_at
        )
        currently_stalled = yolo_age is None or yolo_age >= 3.0
        if currently_stalled and not input_stalled:
            input_stalled = True
            log_event("input_stall", yolo_age_s=None if yolo_age is None else round(yolo_age, 3))
        elif not currently_stalled and input_stalled:
            input_stalled = False
            log_event("input_recovered", yolo_age_s=round(yolo_age, 3))
        snapshots = encoder_snapshot()
        log_event(
            "health_sample",
            yolo_frames=None if processor is None else processor.processed_frames,
            yolo_age_s=None if not processor or processor.last_processed_at is None else round(now - processor.last_processed_at, 3),
            peer_count=len(original.pcs),
            peers=[{"id": m["id"], "state": p.connectionState, "ice": p.iceConnectionState} for p, m in list(peer_meta.items())],
            encoders=snapshots,
        )
        for pc, meta in list(peer_meta.items()):
            age = now - meta["created_at"]
            reason = None
            if pc.connectionState in ("new", "connecting") and age > CONNECT_TIMEOUT_SECONDS:
                reason = "watchdog_connect_timeout"
            elif meta.get("disconnected_at") and now - meta["disconnected_at"] > DISCONNECT_GRACE_SECONDS:
                reason = "watchdog_disconnected_timeout"
            elif pc.connectionState == "connected" and yolo_fresh:
                active = [item for item in snapshots if item["pipeline_active"]]
                if active and any(item["error"] for item in active):
                    reason = "watchdog_encoder_error"
                elif active and all(
                    item["last_output_age_s"] is not None
                    and item["last_output_age_s"] > ENCODER_STALL_SECONDS
                    for item in active
                ):
                    reason = "watchdog_encoder_stall"
            if reason:
                await close_peer(pc, reason)


async def resilience_startup(_app):
    global offer_lock, watchdog_task
    offer_lock = asyncio.Lock()
    watchdog_task = asyncio.create_task(watchdog_loop())
    log_event("server_started")


async def resilience_shutdown(_app):
    global watchdog_task
    if watchdog_task is not None:
        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)
        watchdog_task = None
    for pc in list(original.pcs):
        await close_peer(pc, "server_shutdown")
    log_event("server_stopped")


RESILIENT_WEBRTC_SCRIPT = r"""
const statusElement = document.getElementById("connection-status");
const videoElement = document.getElementById("video");
let peer = null;
let generation = 0;
let retryTimer = null;
let retrySeconds = 1;
let lastVideoFrameAt = 0;
let stopped = false;

function scheduleReconnect(reason) {
  if (stopped || retryTimer) return;
  statusElement.textContent = `WebRTC: reconnecting (${reason})`;
  if (peer) { peer.close(); peer = null; }
  const delay = retrySeconds * 1000;
  retrySeconds = Math.min(retrySeconds * 2, 8);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    startWebRTC();
  }, delay);
}

async function startWebRTC() {
  const mine = ++generation;
  if (peer) peer.close();
  const pc = new RTCPeerConnection();
  peer = pc;
  lastVideoFrameAt = performance.now();
  statusElement.textContent = "WebRTC: connecting";
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = event => {
    videoElement.srcObject = event.streams[0];
    videoElement.play().catch(() => {});
  };
  pc.onconnectionstatechange = () => {
    if (pc !== peer) return;
    statusElement.textContent = "WebRTC: " + pc.connectionState;
    if (pc.connectionState === "connected") retrySeconds = 1;
    if (["failed", "closed"].includes(pc.connectionState)) {
      scheduleReconnect("connection " + pc.connectionState);
    }
  };
  pc.oniceconnectionstatechange = () => {
    if (pc === peer && pc.iceConnectionState === "failed") {
      scheduleReconnect("ICE failed");
    }
  };
  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise((resolve, reject) => {
      if (pc.iceGatheringState === "complete") return resolve();
      const timeout = setTimeout(() => reject(new Error("ICE gathering timeout")), 10000);
      const check = () => {
        if (pc.iceGatheringState === "complete") {
          clearTimeout(timeout);
          pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", check);
    });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    const response = await fetch("/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pc.localDescription),
      signal: controller.signal
    });
    clearTimeout(timeout);
    if (!response.ok) throw new Error(await response.text());
    if (mine !== generation || pc !== peer) return pc.close();
    await pc.setRemoteDescription(await response.json());
  } catch (error) {
    console.error(error);
    if (pc === peer) scheduleReconnect(error.message);
  }
}

if (videoElement.requestVideoFrameCallback) {
  const sawFrame = () => {
    lastVideoFrameAt = performance.now();
    videoElement.requestVideoFrameCallback(sawFrame);
  };
  videoElement.requestVideoFrameCallback(sawFrame);
} else {
  videoElement.addEventListener("timeupdate", () => { lastVideoFrameAt = performance.now(); });
}

setInterval(() => {
  if (!peer || stopped) return;
  if (peer.connectionState === "connected" && performance.now() - lastVideoFrameAt > 4000) {
    scheduleReconnect("no decoded video frame");
  }
}, 1000);

setInterval(async () => {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const health = await response.json();
    if (!health.healthy) {
      const age = health.yolo?.last_frame_age_s;
      statusElement.textContent = `Input stalled${age == null ? "" : ` (${age}s)`}; WebRTC: ${peer?.connectionState}`;
    }
  } catch (_) {}
}, 2000);

window.addEventListener("pagehide", () => {
  stopped = true;
  if (retryTimer) clearTimeout(retryTimer);
  if (peer) peer.close();
});
startWebRTC();
"""


def build_app():
    app = web.Application()
    app.router.add_get("/", original.index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/camera", original.camera_status)
    app.router.add_post("/api/camera/control", original.camera_control)
    app.router.add_post("/api/capture", original.capture_frames)
    app.on_startup.append(original.on_startup)
    app.on_startup.append(resilience_startup)
    app.on_shutdown.append(resilience_shutdown)
    app.on_shutdown.append(original.on_shutdown)
    return app


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtsp-url", default=base.rtsp_hw.DEFAULT_RTSP_URL)
    parser.add_argument("--rtsp-latency", type=int, default=100)
    parser.add_argument("--rtsp-timeout", type=float, default=5.0)
    parser.add_argument("--fps", type=int, default=original.CAMERA_FPS)
    parser.add_argument("--model-path", default=original.MODEL_PATH)
    parser.add_argument("--h264-bitrate", type=int, default=h264_hw.DEFAULT_H264_BITRATE)
    parser.add_argument("--host", default=original.HTTP_HOST)
    parser.add_argument("--port", type=int, default=original.HTTP_PORT)
    parser.add_argument("--log-dir", default="diagnostics")
    args = parser.parse_args()
    if args.rtsp_latency < 0 or args.rtsp_timeout <= 0:
        parser.error("invalid RTSP latency/timeout")
    if args.fps <= 0 or 90_000 % args.fps:
        parser.error("--fps must be a positive divisor of 90000")
    args.h264_bitrate = h264_hw.JetsonH264Encoder._clamp_bitrate(args.h264_bitrate)
    return args


def configure(parsed_settings):
    global settings, event_log
    settings = parsed_settings
    run_dir = Path(settings.log_dir) / datetime.now().strftime("resilient_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    settings.run_dir = str(run_dir)
    event_log = JsonEventLog(run_dir / "events.jsonl")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(run_dir / "server.log"), logging.StreamHandler()],
    )
    base.configure(settings)
    original.YoloGpsProcessor = MonitoredYoloGpsProcessor
    rtcrtpsender.get_encoder = encoder_factory
    original.HTML = build_page(
        "YOLO GPS RTSP WebRTC stream (resilient)",
        '<video id="video" autoplay playsinline muted></video>',
        RESILIENT_WEBRTC_SCRIPT,
        source_options=(("rtsp", "RTSP / H.264"),),
    )
    log_event("configured", settings={
        "rtsp_url": settings.rtsp_url,
        "fps": settings.fps,
        "model_path": settings.model_path,
        "h264_bitrate": settings.h264_bitrate,
        "port": settings.port,
    })
    return run_dir


if __name__ == "__main__":
    run_directory = configure(parse_args())
    Gst = base.rtsp_hw.gst_import()
    base.rtsp_hw.check_gstreamer(Gst)
    h264_hw.check_jetson_encoder(Gst)
    print(f"Diagnostic log directory: {run_directory}")
    print(f"Open http://<device-ip>:{settings.port} in a browser")
    try:
        web.run_app(build_app(), host=settings.host, port=settings.port)
    finally:
        if event_log is not None:
            event_log.close()
