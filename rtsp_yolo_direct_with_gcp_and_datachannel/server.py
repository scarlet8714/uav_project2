"""HTTP/WebRTC signaling, peer watchdog, health, and structured event log."""

import asyncio
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import uuid

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.exceptions import OperationError
from aiortc.rtp import RtpPacket, is_rtcp

from .codec import preferences
from .diagnostics import format_event, format_status
from .inference import InferenceWorker
from .metadata import MetadataSender
from .source import RtspSource
from .turn import enforce_relay, require_relay_candidates, selected_pair
from .web import HTML, UI_REVISION


class EventLog:
    def __init__(self, directory):
        self.directory = Path(directory) / datetime.now().strftime(
            "gcp_datachannel_%Y%m%d_%H%M%S")
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
            if kind != "health_sample":
                print(f"[{line['time'][11:23]}] {format_event(kind, fields)}", flush=True)

    def close(self):
        with self.lock:
            self.handle.close()


def publish(app, message):
    for peer in tuple(app["peers"].values()):
        sender = peer.get("metadata")
        if sender is not None:
            sender.publish(message)


def peer_snapshot(peer_id, peer, now):
    track = peer.get("track")
    sender = peer.get("metadata")
    metadata = None if sender is None else sender.snapshot()
    return {"id": peer_id, "connection_state": peer["pc"].connectionState,
            "ice_state": peer["pc"].iceConnectionState,
            "age_s": round(now-peer["created_at"], 3),
            "sent_packets": peer["sent_packets"], "sent_bytes": peer["sent_bytes"],
            "sent_rtcp_packets": peer.get("sent_rtcp_packets", 0),
            "last_rtp_age_s": None if peer["last_rtp_at"] is None else
                round(now-peer["last_rtp_at"], 3),
            "last_send_error": peer.get("last_send_error"),
            "ice_pair": None if peer.get("ice_connection") is None else
                selected_pair(peer["ice_connection"]),
            "metadata_connected": metadata is not None and metadata["connected"],
            "metadata_queue_size": 0 if metadata is None else metadata["pending_results"],
            "metadata": metadata,
            "track": None if track is None else {
                "ready_state": track.readyState,
                "queue_size": track.queue.qsize(), "queue_capacity": track.queue.maxsize,
                "waiting_keyframe": track.wait_keyframe, "last_pts90k": track.last_pts}}


def health_snapshot(app, now=None):
    now = time.monotonic() if now is None else now
    rtsp, yolo = app["source"].status(), app["inference"].status()
    config = app["config"]
    return {"healthy": rtsp["connected"] and yolo["last_frame_age_s"] is not None
                       and yolo["last_frame_age_s"] < 3,
            "rtsp": rtsp, "yolo": yolo,
            "peers": [peer_snapshot(peer_id, peer, now)
                      for peer_id, peer in tuple(app["peers"].items())],
            "recent_peer_closures": list(app["recent_peer_closures"]),
            "settings": {"model_path": config.model_path, "tracker": config.tracker,
                         "transport": config.transport, "receive_max_delay_ms": 600,
                         "playout_delay_ms": config.playout_delay_ms,
                         "rtsp_timeout_s": config.rtsp_timeout, "infer_every_n_frames": 2,
                         "turn_url": config.turn.url, "ice_transport_policy": "relay",
                         "metadata_transport": "webrtc-datachannel",
                         "bundle_policy": "max-bundle",
                         "frontend_revision": UI_REVISION},
            "video_path": "H.264 packets -> WebRTC -> GCP TURN -> browser (no decode or re-encode)"}


async def close_peer(app, peer_id, reason):
    peer = app["peers"].get(peer_id)
    if peer is None or peer.get("closing"):
        return
    peer["closing"] = True
    snapshot = peer_snapshot(peer_id, peer, time.monotonic())
    closure = {"time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
               "reason": reason, **snapshot}
    app["recent_peer_closures"].append(closure)
    app["log"].write("peer_closing", peer_id=peer_id, reason=reason,
                     connection_state=peer["pc"].connectionState,
                     sent_packets=peer["sent_packets"],
                     sent_bytes=peer["sent_bytes"], last_rtp_age_s=snapshot["last_rtp_age_s"],
                     snapshot=snapshot)
    if peer.get("metadata") is not None:
        peer["metadata"].stop()
    try:
        await asyncio.wait_for(peer["pc"].close(), timeout=5)
    except Exception as exc:
        app["log"].write("peer_close_error", peer_id=peer_id,
                         error=repr(exc))
    finally:
        peer["track"].stop() if peer.get("track") else None
        app["peers"].pop(peer_id, None)


async def index(request):
    html = HTML.replace("__TURN_ICE_CONFIGURATION__", request.app["config"].turn.script_configuration())
    return web.Response(text=html, content_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Frontend-Revision": UI_REVISION})


async def offer(request):
    app = request.app
    params = await request.json()
    async with app["offer_lock"]:
        for old_id in tuple(app["peers"]):
            await close_peer(app, old_id, "superseded_by_new_offer")
        source = app["source"]
        if not source.ready:
            raise web.HTTPServiceUnavailable(text="RTSP source is reconnecting")
        pc = RTCPeerConnection(configuration=app["config"].turn.rtc_configuration())
        peer_id = uuid.uuid4().hex[:10]
        peer = {"pc": pc, "track": None, "origin": None,
                "generation": source.generation,
                "created_at": time.monotonic(), "connected_at": None,
                "disconnected_at": None, "closing": False,
                "sent_packets": 0, "sent_bytes": 0, "last_rtp_at": None,
                "sent_rtcp_packets": 0, "last_send_error": None,
                "ice_connection": None}
        app["peers"][peer_id] = peer
        peer["metadata"] = MetadataSender(app, peer_id, peer)
        app["log"].write("peer_created", peer_id=peer_id,
                         remote=request.remote,
                         client_revision=str(params.get("clientRevision", "unknown"))[:64],
                         client_reconnect_reason=str(params.get("reconnectReason", "unknown"))[:160])

        @pc.on("datachannel")
        def datachannel(channel):
            peer["metadata"].attach(channel)

        @pc.on("connectionstatechange")
        async def connection_changed():
            app["log"].write("peer_connection_state", peer_id=peer_id,
                             state=pc.connectionState)
            if pc.connectionState == "connected":
                pair = selected_pair(peer["ice_connection"])
                if pair is None or not pair["relay_verified"]:
                    await close_peer(app, peer_id, "relay_policy_violation")
                    return
                app["log"].write("turn_relay_connected", peer_id=peer_id, ice_pair=pair)
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
            peer["ice_connection"] = enforce_relay(video)
            video.setCodecPreferences(preferences(source.profile_id))
            try:
                await pc.setRemoteDescription(RTCSessionDescription(
                    sdp=params["sdp"], type=params["type"]))
            except OperationError as exc:
                raise web.HTTPBadRequest(text=(
                    f"Browser does not offer H.264 profile {source.profile_id}")) from exc
            if pc.sctp is None or pc.sctp.transport is not video.sender.transport:
                raise web.HTTPBadRequest(text="Metadata DataChannel must be bundled with video")
            track = source.new_track()
            peer["track"] = track
            video.sender.replaceTrack(track)
            transport = video.sender.transport
            send_rtp = transport._send_rtp

            async def capture_origin(data):
                rtcp = is_rtcp(data)
                if not rtcp and peer["origin"] is None and track.last_pts is not None:
                    try:
                        packet = RtpPacket.parse(data)
                        origin = (packet.timestamp - track.last_pts) & 0xFFFFFFFF
                        peer["origin"] = origin
                        peer["metadata"].origin_available()
                    except Exception:
                        pass
                try:
                    result = await send_rtp(data)
                except Exception as exc:
                    peer["last_send_error"] = repr(exc)
                    app["log"].write("rtp_send_error", peer_id=peer_id,
                                     error=peer["last_send_error"])
                    raise
                if rtcp:
                    peer["sent_rtcp_packets"] += 1
                else:
                    peer["sent_packets"] += 1
                    peer["sent_bytes"] += len(data)
                    peer["last_rtp_at"] = time.monotonic()
                return result

            transport._send_rtp = capture_origin
            await pc.setLocalDescription(await pc.createAnswer())
            try:
                require_relay_candidates(peer["ice_connection"])
            except RuntimeError as exc:
                raise web.HTTPBadGateway(text=str(exc)) from exc
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


async def health(request):
    return web.json_response(health_snapshot(request.app))


async def camera_status(request):
    source = request.app["source"].status()
    return web.json_response({"source": "rtsp", "rtsp": source,
                              "controls_supported": False,
                              "message": "RTSP camera controls are unavailable"})


async def camera_control(_request):
    raise web.HTTPBadRequest(text="RTSP camera controls are unavailable")


async def watchdog(app):
    input_stalled = False
    last_console_status = None
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        snapshot = health_snapshot(app, now)
        rtsp, yolo = snapshot["rtsp"], snapshot["yolo"]
        stalled = not rtsp["connected"] or yolo["last_frame_age_s"] is None or yolo["last_frame_age_s"] >= 3
        if stalled != input_stalled:
            input_stalled = stalled
            app["log"].write("input_stall" if stalled else "input_recovered",
                             rtsp=rtsp, yolo=yolo)
        app["log"].write("health_sample", rtsp=rtsp, yolo=yolo,
                         peer_count=len(snapshot["peers"]), peers=snapshot["peers"])
        if last_console_status is None or now-last_console_status >= 5:
            last_console_status = now
            stamp = datetime.now().astimezone().strftime("%H:%M:%S")
            print(f"[{stamp}] STATUS {format_status(snapshot)}", flush=True)
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
        app["log"].write)
    app["source"] = RtspSource(
        app["config"], loop, app["inference"].submit, app["log"].write)
    app["watchdog"] = asyncio.create_task(watchdog(app))
    app["log"].write("server_started", **health_snapshot(app)["settings"],
                     log_directory=str(app["log"].directory))


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
    app["recent_peer_closures"] = deque(maxlen=16)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/camera", camera_status)
    app.router.add_post("/api/camera/control", camera_control)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(cleanup)
    return app
