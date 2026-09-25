"""One RTSP H.264 input, direct WebRTC video, Jetson-decoded YOLO boxes.

The page prints the source PTS of the displayed video frame and the source
PTS of the detection used for its Canvas overlay.  No video re-encoding.
"""

import argparse
import asyncio
from collections import deque
from fractions import Fraction
import json
import threading
import time
import uuid

from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
import av
import numpy as np
from ultralytics import YOLO

import rtsp_direct_stream as direct


HTML = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTSP / YOLO timestamp test</title>
<style>
body{background:#111;color:#eee;font-family:sans-serif;margin:16px}
#stage{position:relative;display:inline-block;max-width:100%}
video{display:block;width:min(100%,1280px);background:#000}
canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#status{white-space:pre-wrap;font-family:monospace}
</style></head><body><h2>RTSP direct video + YOLO timestamp test</h2>
<div id="stage"><video id="video" autoplay playsinline muted></video>
<canvas id="overlay"></canvas></div><pre id="status">Connecting…</pre>
<script>
const video = document.getElementById('video');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const status = document.getElementById('status');
const pc = new RTCPeerConnection();
pc.addTransceiver('video', {direction:'recvonly'});
let origin = null;
let detections = [];
let lastRtp = null;
let lastVideoPts = null;
let socket;
pc.ontrack = event => { video.srcObject = event.streams[0]; };
pc.onconnectionstatechange = () => { status.dataset.connection = pc.connectionState; };

function draw(now, metadata) {
  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (origin !== null && Number.isFinite(metadata.rtpTimestamp)) {
    lastRtp = metadata.rtpTimestamp >>> 0;
    lastVideoPts = ((lastRtp - origin) >>> 0) / 90000;
  }
  const selected = lastVideoPts === null ? null :
    [...detections].reverse().find(d => d.ptsSeconds <= lastVideoPts + 0.005);
  if (selected && lastVideoPts - selected.ptsSeconds < 1.0) {
    const sx = canvas.width / selected.width;
    const sy = canvas.height / selected.height;
    ctx.strokeStyle = '#00ff66'; ctx.fillStyle = '#00ff66';
    ctx.lineWidth = Math.max(2, canvas.width / 600);
    ctx.font = `${Math.max(16, canvas.width / 60)}px sans-serif`;
    for (const box of selected.boxes) {
      ctx.strokeRect(box.x1*sx, box.y1*sy,
                     (box.x2-box.x1)*sx, (box.y2-box.y1)*sy);
      ctx.fillText(`${box.label} ${box.confidence.toFixed(2)} @ ${selected.ptsSeconds.toFixed(3)}s`,
                   box.x1*sx+3, Math.max(18, box.y1*sy-5));
    }
  }
  ctx.fillStyle = 'rgba(0,0,0,.7)';
  ctx.fillRect(0, 0, Math.min(canvas.width, 690), 75);
  ctx.fillStyle = 'white'; ctx.font = '18px monospace';
  const videoText = lastVideoPts === null ? 'unavailable' : lastVideoPts.toFixed(3)+' s';
  const boxText = selected ? selected.ptsSeconds.toFixed(3)+' s' : 'waiting';
  const gap = selected ? ((lastVideoPts-selected.ptsSeconds)*1000).toFixed(0)+' ms' : '--';
  ctx.fillText(`Video source PTS: ${videoText}`, 12, 25);
  ctx.fillText(`YOLO source PTS:  ${boxText}   gap: ${gap}`, 12, 52);
  status.textContent = `WebRTC: ${pc.connectionState}\n`+
    `Video PTS: ${videoText} | YOLO PTS: ${boxText} | gap: ${gap}\n`+
    `YOLO results buffered: ${detections.length}`;
  video.requestVideoFrameCallback(draw);
}
if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw);
else status.textContent = 'This browser needs requestVideoFrameCallback.';

async function start() {
  await pc.setLocalDescription(await pc.createOffer());
  if (pc.iceGatheringState !== 'complete') await new Promise(resolve => {
    pc.addEventListener('icegatheringstatechange', function check() {
      if (pc.iceGatheringState === 'complete') {
        pc.removeEventListener('icegatheringstatechange', check); resolve();
      }
    });
  });
  const response = await fetch('/offer', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(pc.localDescription)});
  if (!response.ok) throw new Error(await response.text());
  const answer = await response.json();
  await pc.setRemoteDescription({sdp:answer.sdp,type:answer.type});
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//`+
    `${location.host}/events/${answer.peerId}`);
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === 'origin') origin = message.rtpOrigin >>> 0;
    if (message.type === 'detection') {
      detections.push(message);
      if (detections.length > 180) detections.shift();
    }
  };
}
start().catch(error => { console.error(error); status.textContent = error.message; });
window.addEventListener('beforeunload', () => { socket?.close(); pc.close(); });
</script></body></html>"""


def gst_import():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    for name in ("appsrc", "h264parse", "nvv4l2decoder", "nvvidconv", "appsink"):
        if Gst.ElementFactory.find(name) is None:
            raise RuntimeError(f"Missing GStreamer element: {name}")
    return Gst


class EncodedTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.queue = asyncio.Queue(maxsize=120)
        self.wait_keyframe = True
        self.last_pts = None
        source.tracks.add(self)

    def feed(self, packet):
        if self.readyState != "live":
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            self.wait_keyframe = True
        if self.wait_keyframe:
            if not packet.is_keyframe:
                return
            self.wait_keyframe = False
        self.queue.put_nowait(packet)

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        packet = await self.queue.get()
        if packet is None:
            raise MediaStreamError
        self.last_pts = int(packet.pts)
        return packet

    def stop(self):
        super().stop()
        self.source.tracks.discard(self)
        if not self.queue.full():
            self.queue.put_nowait(None)


class SharedSource:
    def __init__(self, settings, loop):
        self.settings = settings
        self.loop = loop
        self.Gst = gst_import()
        self.container = av.open(settings.rtsp_url, format="rtsp",
                                 options={"rtsp_transport": settings.transport},
                                 timeout=settings.timeout)
        self.stream = self.container.streams.video[0]
        if self.stream.codec_context.name != "h264":
            raise RuntimeError("RTSP source must be H.264")
        self.profile_id = direct.source_profile_id(self.stream.codec_context.extradata)
        direct.register_source_codec(self.profile_id)
        self.model = YOLO(settings.model_path, task="detect")
        self.tracks = set()
        self.listeners = set()
        self.running = True
        self.packet_count = 0
        self.detection_count = 0
        self.error = None
        self.pipeline = self.Gst.parse_launch(
            "appsrc name=source is-live=true block=false format=time "
            "caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
            "h264parse ! nvv4l2decoder ! nvvidconv ! "
            "video/x-raw,format=BGRx ! "
            "appsink name=sink max-buffers=1 drop=true sync=false")
        self.appsrc = self.pipeline.get_by_name("source")
        self.sink = self.pipeline.get_by_name("sink")
        if self.pipeline.set_state(self.Gst.State.PLAYING) == self.Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Cannot start Jetson H.264 decoder")
        self.input_thread = threading.Thread(target=self._read, daemon=True,
                                             name="rtsp-demux")
        self.yolo_thread = threading.Thread(target=self._infer, daemon=True,
                                            name="yolo-decoder")
        self.input_thread.start()
        self.yolo_thread.start()

    def _emit(self, message):
        for queue in tuple(self.listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    def _read(self):
        try:
            iterator = iter(self.container.demux(self.stream))
            first = next(iterator)
            while first.size == 0:
                first = next(iterator)
            pending = []
            if first.pts is None:
                pending.append(first)
                following = next(iterator)
                while following.pts is None or following.size == 0:
                    following = next(iterator)
                step = int(self.stream.time_base.denominator /
                           float(self.stream.average_rate or 30))
                base = following.pts - step
                first.pts = base
                pending.append(following)
            else:
                base = first.pts
                pending.append(first)
            for packet in pending:
                self._handle_packet(packet, base)
            for packet in iterator:
                if not self.running:
                    break
                if packet.size and packet.pts is not None:
                    self._handle_packet(packet, base)
        except Exception as exc:
            if self.running:
                self.error = repr(exc)
                print(f"[RTSP] {self.error}", flush=True)
        finally:
            self.loop.call_soon_threadsafe(self._end_tracks)

    def _handle_packet(self, packet, base):
        pts = max(0, int((packet.pts - base) * packet.time_base * 90000))
        packet.pts = pts
        packet.time_base = Fraction(1, 90000)
        self.packet_count += 1
        data = bytes(packet)
        buffer = self.Gst.Buffer.new_allocate(None, len(data), None)
        buffer.fill(0, data)
        buffer.pts = pts * self.Gst.SECOND // 90000
        flow = self.appsrc.emit("push-buffer", buffer)
        if flow != self.Gst.FlowReturn.OK:
            raise RuntimeError(f"Decoder input failed: {flow.value_nick}")
        self.loop.call_soon_threadsafe(self._feed_tracks, packet)

    def _feed_tracks(self, packet):
        for track in tuple(self.tracks):
            track.feed(packet)

    def _end_tracks(self):
        for track in tuple(self.tracks):
            track.stop()

    def _infer(self):
        while self.running:
            sample = self.sink.emit("try-pull-sample", self.Gst.SECOND)
            if sample is None:
                continue
            buffer = sample.get_buffer()
            if buffer.pts == self.Gst.CLOCK_TIME_NONE:
                continue
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value("width"), caps.get_value("height")
            mapped, info = buffer.map(self.Gst.MapFlags.READ)
            if not mapped:
                continue
            try:
                stride = info.size // height
                image = np.ndarray((height, width, 4), dtype=np.uint8,
                                   buffer=info.data, strides=(stride, 4, 1))
                bgr = image[:, :, :3].copy()
            finally:
                buffer.unmap(info)
            pts = int(buffer.pts * 90000 // self.Gst.SECOND)
            started = time.monotonic()
            try:
                result = self.model.predict(bgr, imgsz=(544, 960), conf=0.4,
                                            iou=0.45, verbose=False)[0]
                boxes = []
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cls = int(box.cls[0])
                    boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                  "label": str(result.names[cls]),
                                  "confidence": float(box.conf[0])})
                self.detection_count += 1
                message = {"type": "detection", "pts90k": pts,
                           "ptsSeconds": pts / 90000, "width": width,
                           "height": height, "boxes": boxes,
                           "inferenceMs": round((time.monotonic()-started)*1000, 1)}
                self.loop.call_soon_threadsafe(self._emit, message)
            except Exception as exc:
                self.error = f"YOLO: {exc!r}"
                print(f"[YOLO] {self.error}", flush=True)

    def close(self):
        self.running = False
        self.pipeline.set_state(self.Gst.State.NULL)
        self.container.close()
        self.input_thread.join(timeout=3)
        self.yolo_thread.join(timeout=3)


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def offer(request):
    app = request.app
    pc = RTCPeerConnection()
    peer_id = uuid.uuid4().hex
    app["peers"][peer_id] = {"pc": pc, "origin": None}

    @pc.on("connectionstatechange")
    async def changed():
        print(f"[WebRTC] {peer_id}: {pc.connectionState}", flush=True)
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            app["peers"].pop(peer_id, None)

    try:
        params = await request.json()
        transceiver = pc.addTransceiver("video", direction="sendonly")
        transceiver.setCodecPreferences(direct.h264_codecs(app["source"].profile_id))
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=params["sdp"], type=params["type"]))
        track = EncodedTrack(app["source"])
        transceiver.sender.replaceTrack(track)
        transport = transceiver.sender.transport
        send_rtp = transport._send_rtp

        async def capture_origin(data):
            if app["peers"].get(peer_id, {}).get("origin") is None and track.last_pts is not None:
                try:
                    from aiortc.rtp import RtpPacket
                    rtp = RtpPacket.parse(data)
                    origin = (rtp.timestamp - track.last_pts) & 0xFFFFFFFF
                    app["peers"][peer_id]["origin"] = origin
                    app["source"]._emit({"type": "origin", "peerId": peer_id,
                                          "rtpOrigin": origin})
                except Exception:
                    pass
            return await send_rtp(data)

        transport._send_rtp = capture_origin
        await pc.setLocalDescription(await pc.createAnswer())
        return web.json_response({"sdp": pc.localDescription.sdp,
                                  "type": pc.localDescription.type,
                                  "peerId": peer_id})
    except Exception:
        await pc.close()
        app["peers"].pop(peer_id, None)
        raise


async def events(request):
    app = request.app
    peer = app["peers"].get(request.match_info["peer_id"])
    if peer is None:
        raise web.HTTPNotFound()
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    queue = asyncio.Queue(maxsize=32)
    app["source"].listeners.add(queue)
    try:
        if peer["origin"] is not None:
            await ws.send_json({"type": "origin", "rtpOrigin": peer["origin"]})
        while not ws.closed:
            message = await queue.get()
            if message.get("type") == "origin" and message.get("peerId") != request.match_info["peer_id"]:
                continue
            await ws.send_str(json.dumps(message))
    except (ConnectionError, RuntimeError):
        pass
    finally:
        app["source"].listeners.discard(queue)
        await ws.close()
    return ws


async def status(request):
    source = request.app["source"]
    return web.json_response({"sourceProfileLevelId": source.profile_id,
                              "packets": source.packet_count,
                              "detections": source.detection_count,
                              "error": source.error,
                              "peers": len(request.app["peers"])})


async def shutdown(app):
    await asyncio.gather(*(item["pc"].close() for item in app["peers"].values()),
                         return_exceptions=True)
    await asyncio.to_thread(app["source"].close)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--model-path", default="yolo11s.engine")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = web.Application()
    app["source"] = SharedSource(args, loop)
    app["peers"] = {}
    app.router.add_get("/", index)
    app.router.add_get("/status", status)
    app.router.add_post("/offer", offer)
    app.router.add_get("/events/{peer_id}", events)
    app.on_shutdown.append(shutdown)
    print(f"RTSP direct video + Jetson YOLO: http://<device-ip>:{args.port}/", flush=True)
    web.run_app(app, host=args.host, port=args.port, loop=loop)


if __name__ == "__main__":
    main()
