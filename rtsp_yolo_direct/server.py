"""HTTP/WebRTC signaling, peer watchdog, health, and structured event log."""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import uuid

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.exceptions import OperationError

from .codec import preferences
from .inference import InferenceWorker
from .source import RtspSource
from .web import HTML


class EventLog:
    def __init__(self, directory):
        self.directory = Path(directory) / datetime.now().strftime(
            "direct_%Y%m%d_%H%M%S")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.handle = (self.directory / "events.jsonl").open(
            "a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()

    def write(self, kind, **fields):
        line = {"time": datetime.now().astimezone().isoformat(
                    timespec="milliseconds"),
                "monotonic": round(time.monotonic(), 6),
                "kind": kind, **fields}
        with self.lock:
            self.handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def close(self):
        with self.lock:
            self.handle.close()


def publish(app, message):
    for peer in tuple(app["peers"].values()):
        queue = peer.get("queue")
        if queue is None:
            continue
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(message)


async def close_peer(app, peer_id, reason):
    peer = app["peers"].get(peer_id)
    if peer is None or peer.get("closing"):
        return
    peer["closing"] = True
    app["log"].write("peer_closing", peer_id=peer_id, reason=reason,
                     connection_state=peer["pc"].connectionState,
                     sent_packets=peer["sent_packets"],
                     sent_bytes=peer["sent_bytes"])
    try:
        await asyncio.wait_for(peer["pc"].close(), timeout=5)
    except Exception as exc:
        app["log"].write("peer_close_error", peer_id=peer_id,
                         error=repr(exc))
    finally:
        peer["track"].stop() if peer.get("track") else None
        queue = peer.get("queue")
        if queue is not None:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({"type": "end"})
        app["peers"].pop(peer_id, None)


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def offer(request):
    app = request.app
    params = await request.json()
    async with app["offer_lock"]:
        for old_id in tuple(app["peers"]):
            await close_peer(app, old_id, "superseded_by_new_offer")
        source = app["source"]
        if not source.ready:
            raise web.HTTPServiceUnavailable(text="RTSP source is reconnecting")
        pc = RTCPeerConnection()
        peer_id = uuid.uuid4().hex[:10]
        peer = {"pc": pc, "track": None, "origin": None,
                "generation": source.generation, "queue": None,
                "created_at": time.monotonic(), "connected_at": None,
                "disconnected_at": None, "closing": False,
                "sent_packets": 0, "sent_bytes": 0, "last_rtp_at": None}
        app["peers"][peer_id] = peer
        app["log"].write("peer_created", peer_id=peer_id,
                         remote=request.remote)

        @pc.on("connectionstatechange")
        async def connection_changed():
            app["log"].write("peer_connection_state", peer_id=peer_id,
                             state=pc.connectionState)
            if pc.connectionState == "connected":
                peer["connected_at"] = time.monotonic()
            if pc.connectionState in ("failed", "closed"):
                await close_peer(app, peer_id, "connection_"+pc.connectionState)

        @pc.on("iceconnectionstatechange")
        async def ice_changed():
            app["log"].write("peer_ice_state", peer_id=peer_id,
                             state=pc.iceConnectionState)
            if pc.iceConnectionState == "disconnected":
                peer["disconnected_at"] = time.monotonic()
            elif pc.iceConnectionState in ("connected", "completed"):
                peer["disconnected_at"] = None
            elif pc.iceConnectionState in ("failed", "closed"):
                await close_peer(app, peer_id, "ice_"+pc.iceConnectionState)

        try:
            video = pc.addTransceiver("video", direction="sendonly")
            video.setCodecPreferences(preferences(source.profile_id))
            try:
                await pc.setRemoteDescription(RTCSessionDescription(
                    sdp=params["sdp"], type=params["type"]))
            except OperationError as exc:
                raise web.HTTPBadRequest(text=(
                    f"Browser does not offer H.264 profile {source.profile_id}")) from exc
            track = source.new_track()
            peer["track"] = track
            video.sender.replaceTrack(track)
            transport = video.sender.transport
            send_rtp = transport._send_rtp

            async def capture_origin(data):
                if peer["origin"] is None and track.last_pts is not None:
                    try:
                        from aiortc.rtp import RtpPacket
                        packet = RtpPacket.parse(data)
                        origin = (packet.timestamp - track.last_pts) & 0xFFFFFFFF
                        peer["origin"] = origin
                        queue = peer.get("queue")
                        if queue is not None:
                            if queue.full():
                                queue.get_nowait()
                            queue.put_nowait({"type": "origin", "rtpOrigin": origin})
                    except Exception:
                        pass
                result = await send_rtp(data)
                peer["sent_packets"] += 1
                peer["sent_bytes"] += len(data)
                peer["last_rtp_at"] = time.monotonic()
                return result

            transport._send_rtp = capture_origin
            await pc.setLocalDescription(await pc.createAnswer())
            app["log"].write("offer_answered", peer_id=peer_id,
                             generation=source.generation)
            return web.json_response({"sdp": pc.localDescription.sdp,
                                      "type": pc.localDescription.type,
                                      "peerId": peer_id,
                                      "generation": source.generation})
        except Exception as exc:
            app["log"].write("offer_error", peer_id=peer_id,
                             error=repr(exc))
            await close_peer(app, peer_id, "offer_error")
            raise


async def events(request):
    app = request.app
    peer_id = request.match_info["peer_id"]
    peer = app["peers"].get(peer_id)
    if peer is None:
        raise web.HTTPNotFound()
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    queue = asyncio.Queue(maxsize=32)
    peer["queue"] = queue
    if peer["origin"] is not None:
        queue.put_nowait({"type": "origin", "rtpOrigin": peer["origin"]})
    try:
        while not ws.closed:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if message["type"] == "end":
                break
            await ws.send_json(message)
    except (ConnectionError, RuntimeError):
        pass
    finally:
        if peer.get("queue") is queue:
            peer["queue"] = None
        await ws.close()
    return ws


async def health(request):
    app = request.app
    now = time.monotonic()
    rtsp = app["source"].status()
    yolo = app["inference"].status()
    return web.json_response({
        "healthy": rtsp["connected"] and yolo["last_frame_age_s"] is not None
                   and yolo["last_frame_age_s"] < 3,
        "rtsp": rtsp, "yolo": yolo,
        "peers": [{"id": peer_id, "connection_state": peer["pc"].connectionState,
                   "ice_state": peer["pc"].iceConnectionState,
                   "age_s": round(now-peer["created_at"], 3),
                   "sent_packets": peer["sent_packets"],
                   "sent_bytes": peer["sent_bytes"],
                   "last_rtp_age_s": None if peer["last_rtp_at"] is None else
                       round(now-peer["last_rtp_at"], 3)}
                  for peer_id, peer in tuple(app["peers"].items())],
        "video_path": "H.264 packets -> WebRTC (no decode or re-encode)"})


async def camera_status(request):
    source = request.app["source"].status()
    return web.json_response({"source": "rtsp", "rtsp": source,
                              "controls_supported": False,
                              "message": "RTSP camera controls are unavailable"})


async def camera_control(_request):
    raise web.HTTPBadRequest(text="RTSP camera controls are unavailable")


async def capture(request):
    accepted, result = await asyncio.to_thread(
        request.app["inference"].request_capture)
    return web.json_response(result, status=200 if accepted else 429)


async def watchdog(app):
    input_stalled = False
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        rtsp = app["source"].status()
        yolo = app["inference"].status()
        stalled = not rtsp["connected"] or yolo["last_frame_age_s"] is None or yolo["last_frame_age_s"] >= 3
        if stalled != input_stalled:
            input_stalled = stalled
            app["log"].write("input_stall" if stalled else "input_recovered",
                             rtsp=rtsp, yolo=yolo)
        app["log"].write("health_sample", rtsp=rtsp, yolo=yolo,
                         peer_count=len(app["peers"]))
        for peer_id, peer in tuple(app["peers"].items()):
            pc = peer["pc"]
            reason = None
            if peer["generation"] != app["source"].generation or not rtsp["connected"]:
                reason = "source_reconnected_or_stalled"
            elif pc.connectionState in ("new", "connecting") and now-peer["created_at"] > 15:
                reason = "connection_timeout"
            elif peer["disconnected_at"] and now-peer["disconnected_at"] > 5:
                reason = "disconnected_timeout"
            if reason:
                await close_peer(app, peer_id, reason)


async def startup(app):
    loop = asyncio.get_running_loop()
    app["offer_lock"] = asyncio.Lock()
    app["peers"] = {}
    app["inference"] = InferenceWorker(
        app["config"], loop, lambda result: publish(app, result),
        app["log"].write, app["log"].directory / "captures")
    app["source"] = RtspSource(
        app["config"], loop, app["inference"].submit, app["log"].write)
    app["watchdog"] = asyncio.create_task(watchdog(app))
    app["log"].write("server_started")


async def shutdown(app):
    app["watchdog"].cancel()
    await asyncio.gather(app["watchdog"], return_exceptions=True)
    for peer_id in tuple(app["peers"]):
        await close_peer(app, peer_id, "server_shutdown")
    await asyncio.to_thread(app["source"].close)
    await asyncio.to_thread(app["inference"].close)
    app["log"].write("server_stopped")


async def cleanup(app):
    app["log"].close()


def create_app(config):
    app = web.Application()
    app["config"] = config
    app["log"] = EventLog(config.log_dir)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/events/{peer_id}", events)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/camera", camera_status)
    app.router.add_post("/api/camera/control", camera_control)
    app.router.add_post("/api/capture", capture)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(cleanup)
    return app
