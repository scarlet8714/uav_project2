"""Relay an H.264 RTSP stream to a browser with WebRTC on NVIDIA Jetson.

Both codec stages are hardware accelerated:

    RTSP / H.264 -> nvv4l2decoder -> BGR frame
    BGR frame -> nvv4l2h264enc -> H.264 RTP / WebRTC

Run:
    python rtsp_minimal.py
    python rtsp_minimal.py --rtsp-url rtsp://192.168.144.135/live

Then open ``http://<jetson-ip>:8080`` in a browser.
"""

import argparse
import asyncio
import fractions
import threading
import time

from aiohttp import web
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from aiortc import VideoStreamTrack
from aiortc.codecs import get_encoder as software_get_encoder
from aiortc.codecs import h264
from aiortc.codecs.base import Encoder
import aiortc.rtcrtpsender as rtcrtpsender
import av
import numpy as np


DEFAULT_RTSP_URL = "rtsp://192.168.144.135/live"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_FPS = 30
DEFAULT_BITRATE = 3_000_000
MIN_BITRATE = 500_000
MAX_BITRATE = 20_000_000
H264_PROFILE_LEVEL_ID = "42e01f"

settings = None
source = None
pcs = set()


HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RTSP WebRTC relay</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; text-align: center; }
    video { width: min(100%, 1280px); margin-top: 16px; background: #000; }
    #status { margin: 12px; }
  </style>
</head>
<body>
  <h2>RTSP WebRTC relay</h2>
  <div id="status">WebRTC: connecting</div>
  <video id="video" autoplay playsinline muted></video>
  <script>
    const statusElement = document.getElementById("status");
    const peer = new RTCPeerConnection();
    peer.addTransceiver("video", { direction: "recvonly" });
    peer.ontrack = event => {
      document.getElementById("video").srcObject = event.streams[0];
    };
    peer.onconnectionstatechange = () => {
      statusElement.textContent = "WebRTC: " + peer.connectionState;
    };

    async function start() {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await new Promise(resolve => {
        if (peer.iceGatheringState === "complete") return resolve();
        const check = () => {
          if (peer.iceGatheringState === "complete") {
            peer.removeEventListener("icegatheringstatechange", check);
            resolve();
          }
        };
        peer.addEventListener("icegatheringstatechange", check);
      });
      const response = await fetch("/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(peer.localDescription)
      });
      if (!response.ok) throw new Error(await response.text());
      await peer.setRemoteDescription(await response.json());
    }
    start().catch(error => {
      console.error(error);
      statusElement.textContent = "Error: " + error.message;
    });
  </script>
</body>
</html>
"""


def gst_import():
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise RuntimeError("PyGObject and GStreamer 1.0 are required") from exc
    Gst.init(None)
    return Gst


def check_gstreamer(Gst):
    required = (
        "rtspsrc",
        "rtph264depay",
        "h264parse",
        "nvv4l2decoder",
        "nvvidconv",
        "appsink",
        "appsrc",
        "nvv4l2h264enc",
    )
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    if missing:
        raise RuntimeError(
            "Missing required GStreamer elements: " + ", ".join(missing)
        )


class RtspHardwareSource:
    """Continuously decode RTSP H.264 with NVDEC and retain the latest frame."""

    def __init__(self, url, latency_ms, tcp_timeout_seconds):
        self.Gst = gst_import()
        check_gstreamer(self.Gst)
        self.url = url
        self.latency_ms = latency_ms
        self.tcp_timeout_us = int(tcp_timeout_seconds * 1_000_000)
        self.pipeline = None
        self.sink = None
        self.frame = None
        self.sequence = 0
        self.last_error = None
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(
            target=self._run, name="rtsp-hardware-decoder", daemon=True
        )
        self.thread.start()

    def _make(self, factory, name):
        element = self.Gst.ElementFactory.make(factory, name)
        if element is None:
            raise RuntimeError(f"Cannot create GStreamer element {factory}")
        return element

    def _build_pipeline(self):
        Gst = self.Gst
        pipeline = Gst.Pipeline.new("rtsp-decode")
        rtsp = self._make("rtspsrc", "rtsp")
        depay = self._make("rtph264depay", "depay")
        parser = self._make("h264parse", "parser")
        decoder = self._make("nvv4l2decoder", "decoder")
        converter = self._make("nvvidconv", "converter")
        capsfilter = self._make("capsfilter", "raw-caps")
        sink = self._make("appsink", "sink")

        rtsp.set_property("location", self.url)
        rtsp.set_property("latency", self.latency_ms)
        rtsp.set_property("drop-on-latency", True)
        rtsp.set_property("protocols", 4)  # GstRtsp.RTSPLowerTrans.TCP
        rtsp.set_property("tcp-timeout", self.tcp_timeout_us)
        capsfilter.set_property(
            "caps", Gst.Caps.from_string("video/x-raw,format=BGRx")
        )
        sink.set_property("max-buffers", 1)
        sink.set_property("drop", True)
        sink.set_property("sync", False)

        for element in (rtsp, depay, parser, decoder, converter, capsfilter, sink):
            pipeline.add(element)
        if not depay.link(parser):
            raise RuntimeError("Cannot link rtph264depay to h264parse")
        if not parser.link(decoder):
            raise RuntimeError("Cannot link h264parse to nvv4l2decoder")
        if not decoder.link(converter):
            raise RuntimeError("Cannot link nvv4l2decoder to nvvidconv")
        if not converter.link(capsfilter) or not capsfilter.link(sink):
            raise RuntimeError("Cannot link nvvidconv to appsink")

        def on_rtsp_pad_added(_element, pad):
            target = depay.get_static_pad("sink")
            if target.is_linked():
                return
            caps = pad.get_current_caps() or pad.query_caps(None)
            structure = caps.get_structure(0)
            media = structure.get_string("media")
            encoding = structure.get_string("encoding-name")
            if media == "video" and encoding and encoding.upper() == "H264":
                result = pad.link(target)
                if result != Gst.PadLinkReturn.OK:
                    print(f"RTSP video pad link failed: {result.value_nick}")

        rtsp.connect("pad-added", on_rtsp_pad_added)
        self.pipeline = pipeline
        self.sink = sink

    def _set_error(self, message):
        with self.lock:
            self.last_error = message
        print(message)

    def _read_sample(self, sample):
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")
        buffer = sample.get_buffer()
        mapped, info = buffer.map(self.Gst.MapFlags.READ)
        if not mapped:
            return
        try:
            stride = info.size // height
            if stride < width * 4:
                raise RuntimeError(f"Invalid BGRx row stride: {stride}")
            bgrx = np.ndarray(
                (height, width, 4),
                dtype=np.uint8,
                buffer=info.data,
                strides=(stride, 4, 1),
            )
            frame = bgrx[:, :, :3].copy()
        finally:
            buffer.unmap(info)
        with self.lock:
            self.frame = frame
            self.sequence += 1
            self.last_error = None

    def _run_once(self):
        self._build_pipeline()
        result = self.pipeline.set_state(self.Gst.State.PLAYING)
        if result == self.Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Cannot start RTSP hardware decoder pipeline")

        bus = self.pipeline.get_bus()
        while self.running:
            message = bus.pop_filtered(
                self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS
            )
            if message is not None:
                if message.type == self.Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    raise RuntimeError(f"RTSP pipeline error: {error}; debug={debug}")
                raise RuntimeError("RTSP pipeline reached end of stream")

            sample = self.sink.emit("try-pull-sample", self.Gst.SECOND)
            if sample is not None:
                self._read_sample(sample)

    def _run(self):
        while self.running:
            try:
                self._run_once()
            except Exception as exc:
                if self.running:
                    self._set_error(f"{exc}; reconnecting in 1 second")
            finally:
                if self.pipeline is not None:
                    self.pipeline.set_state(self.Gst.State.NULL)
                self.pipeline = None
                self.sink = None
            if self.running:
                time.sleep(1.0)

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def status(self):
        with self.lock:
            frame = self.frame
            return {
                "connected": frame is not None and self.last_error is None,
                "frames": self.sequence,
                "resolution": (
                    None
                    if frame is None
                    else f"{frame.shape[1]}x{frame.shape[0]}"
                ),
                "error": self.last_error,
            }

    def close(self):
        self.running = False
        pipeline = self.pipeline
        if pipeline is not None:
            pipeline.send_event(self.Gst.Event.new_eos())
        self.thread.join(timeout=3.0)
        if self.pipeline is not None:
            self.pipeline.set_state(self.Gst.State.NULL)


class RtspVideoTrack(VideoStreamTrack):
    def __init__(self, rtsp_source, fps):
        super().__init__()
        self.source = rtsp_source
        self.fps = fps
        self.started_at = time.monotonic()
        self.frame_index = 0

    async def recv(self):
        self.frame_index += 1
        target = self.started_at + self.frame_index / self.fps
        delay = target - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

        frame = self.source.get_frame()
        while frame is None:
            await asyncio.sleep(0.02)
            frame = self.source.get_frame()

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self.frame_index * (90_000 // self.fps)
        video_frame.time_base = fractions.Fraction(1, 90_000)
        return video_frame


class JetsonH264Encoder(Encoder):
    """aiortc encoder backed exclusively by Jetson nvv4l2h264enc."""

    def __init__(self, bitrate):
        self.Gst = gst_import()
        check_gstreamer(self.Gst)
        self.bitrate = max(MIN_BITRATE, min(int(bitrate), MAX_BITRATE))
        self.pipeline = None
        self.source = None
        self.encoder = None
        self.sink = None
        self.width = None
        self.height = None
        self.frames_encoded = 0
        self.lock = threading.Lock()

    @property
    def target_bitrate(self):
        return self.bitrate

    @target_bitrate.setter
    def target_bitrate(self, value):
        # Jetson R36 cannot safely update this property while PLAYING. Keep the
        # initial setting instead of repeatedly rebuilding the encoder on REMB.
        self.bitrate = max(MIN_BITRATE, min(int(value), MAX_BITRATE))

    def _start(self, width, height):
        self.close()
        pipeline_text = (
            "appsrc name=src is-live=false block=true format=time "
            f"caps=video/x-raw,format=BGRx,width={width},height={height},"
            f"framerate={settings.fps}/1 ! "
            "queue max-size-buffers=1 leaky=downstream ! nvvidconv ! "
            "video/x-raw(memory:NVMM),format=NV12 ! "
            "nvv4l2h264enc name=encoder control-rate=1 "
            f"bitrate={self.bitrate} iframeinterval={settings.fps} "
            f"idrinterval={settings.fps} profile=1 preset-level=1 "
            "insert-sps-pps=true insert-vui=true maxperf-enable=true "
            "copy-timestamp=true ! "
            "video/x-h264,stream-format=byte-stream,alignment=au,"
            "profile=constrained-baseline ! "
            "appsink name=sink max-buffers=1 drop=false sync=false"
        )
        self.pipeline = self.Gst.parse_launch(pipeline_text)
        self.source = self.pipeline.get_by_name("src")
        self.encoder = self.pipeline.get_by_name("encoder")
        self.sink = self.pipeline.get_by_name("sink")
        result = self.pipeline.set_state(self.Gst.State.PLAYING)
        if result == self.Gst.StateChangeReturn.FAILURE:
            self.close()
            raise RuntimeError("Cannot start Jetson H.264 hardware encoder")
        self.width, self.height = width, height
        self.frames_encoded = 0

    def _check_bus(self):
        message = self.pipeline.get_bus().pop_filtered(
            self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS
        )
        if message is None:
            return
        if message.type == self.Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            raise RuntimeError(f"H.264 encoder error: {error}; debug={debug}")
        raise RuntimeError("H.264 encoder reached end of stream")

    def encode(self, frame, force_keyframe=False):
        if not isinstance(frame, av.VideoFrame):
            raise TypeError("JetsonH264Encoder expects av.VideoFrame")
        with self.lock:
            if self.pipeline is None or (frame.width, frame.height) != (
                self.width,
                self.height,
            ):
                self._start(frame.width, frame.height)
                force_keyframe = True
            if force_keyframe and self.frames_encoded:
                self.encoder.emit("force-IDR")

            data = frame.to_ndarray(format="bgra").tobytes()
            buffer = self.Gst.Buffer.new_allocate(None, len(data), None)
            buffer.fill(0, data)
            pts = int(
                fractions.Fraction(frame.pts) * frame.time_base * self.Gst.SECOND
            )
            buffer.pts = pts
            buffer.dts = pts
            buffer.duration = self.Gst.SECOND // settings.fps
            result = self.source.emit("push-buffer", buffer)
            if result != self.Gst.FlowReturn.OK:
                raise RuntimeError(f"H.264 encoder push failed: {result.value_nick}")

            sample = self.sink.emit("try-pull-sample", 0)
            if sample is None:
                self._check_bus()
                timestamp = h264.convert_timebase(
                    frame.pts, frame.time_base, h264.VIDEO_TIME_BASE
                )
                return [], timestamp

            encoded_buffer = sample.get_buffer()
            encoded = encoded_buffer.extract_dup(0, encoded_buffer.get_size())
            nal_units = list(h264.H264Encoder._split_bitstream(encoded))
            if not nal_units:
                raise RuntimeError("Jetson encoder returned no H.264 NAL units")
            self.frames_encoded += 1
            output_pts = encoded_buffer.pts
            timestamp = (
                h264.convert_timebase(
                    frame.pts, frame.time_base, h264.VIDEO_TIME_BASE
                )
                if output_pts == self.Gst.CLOCK_TIME_NONE
                else int(output_pts * 90_000 // self.Gst.SECOND)
            )
            return h264.H264Encoder._packetize(nal_units), timestamp

    def pack(self, packet):
        nal_units = h264.H264Encoder._split_bitstream(bytes(packet))
        timestamp = h264.convert_timebase(
            packet.pts, packet.time_base, h264.VIDEO_TIME_BASE
        )
        return h264.H264Encoder._packetize(nal_units), timestamp

    def close(self):
        if self.pipeline is not None:
            self.pipeline.set_state(self.Gst.State.NULL)
        self.pipeline = self.source = self.encoder = self.sink = None
        self.width = self.height = None
        self.frames_encoded = 0

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def encoder_factory(codec):
    if codec.mimeType.lower() == "video/h264":
        return JetsonH264Encoder(settings.bitrate)
    return software_get_encoder(codec)


def h264_codecs():
    codecs = [
        codec
        for codec in RTCRtpSender.getCapabilities("video").codecs
        if codec.mimeType.lower() == "video/h264"
        and codec.parameters.get("profile-level-id") == H264_PROFILE_LEVEL_ID
    ]
    if not codecs:
        raise RuntimeError(
            f"aiortc has no H.264 profile-level-id {H264_PROFILE_LEVEL_ID}"
        )
    return codecs


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def status(_request):
    return web.json_response(source.status())


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def connection_state_changed():
        print(f"WebRTC connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            pcs.discard(pc)

    transceiver = pc.addTransceiver("video", direction="sendonly")
    transceiver.setCodecPreferences(h264_codecs())
    await pc.setRemoteDescription(remote_offer)
    transceiver.sender.replaceTrack(RtspVideoTrack(source, settings.fps))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


async def on_startup(_app):
    global source
    source = RtspHardwareSource(
        settings.rtsp_url, settings.rtsp_latency, settings.rtsp_timeout
    )


async def on_shutdown(_app):
    await asyncio.gather(*(pc.close() for pc in pcs), return_exceptions=True)
    pcs.clear()
    if source is not None:
        source.close()


def build_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/status", status)
    app.router.add_post("/offer", offer)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def parse_args():
    parser = argparse.ArgumentParser(
        description="Jetson hardware H.264 RTSP-to-WebRTC relay"
    )
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument(
        "--rtsp-latency", type=int, default=100, help="RTSP jitter latency in ms"
    )
    parser.add_argument(
        "--rtsp-timeout",
        type=float,
        default=5.0,
        help="RTSP TCP timeout in seconds",
    )
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument(
        "--bitrate", type=int, default=DEFAULT_BITRATE, help="H.264 bits/s"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if args.fps <= 0:
        parser.error("--fps must be greater than zero")
    if args.rtsp_latency < 0 or args.rtsp_timeout <= 0:
        parser.error("RTSP latency must be >= 0 and timeout must be > 0")
    args.bitrate = max(MIN_BITRATE, min(args.bitrate, MAX_BITRATE))
    return args


if __name__ == "__main__":
    settings = parse_args()
    Gst = gst_import()
    check_gstreamer(Gst)
    rtcrtpsender.get_encoder = encoder_factory
    print(f"RTSP input: {settings.rtsp_url}")
    print("Decode: H.264 -> nvv4l2decoder -> nvvidconv -> BGRx")
    print(
        "Encode: BGRx -> nvvidconv -> NVMM/NV12 -> "
        f"nvv4l2h264enc ({settings.bitrate} bit/s)"
    )
    print(f"Open http://<device-ip>:{settings.port} in a browser")
    web.run_app(build_app(), host=settings.host, port=settings.port)
