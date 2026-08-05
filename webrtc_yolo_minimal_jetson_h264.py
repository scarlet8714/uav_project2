"""Jetson VIC capture plus Jetson H.264 WebRTC encoding.

This is the hardware-encoder counterpart of ``webrtc_yolo_minimal_hw.py``.
It keeps that program's camera / YOLO path, but replaces aiortc's libx264
encoder with a GStreamer ``nvv4l2h264enc`` pipeline.  The browser is offered
H.264 constrained-baseline only, so the stream cannot silently fall back to
VP8 or software H.264.

The adapter targets the encoder interface shipped by aiortc 1.15.0 (pinned in
requirements.txt).  Each WebRTC peer owns one Jetson encoder instance.

Examples:
    python webrtc_yolo_minimal_jetson_h264.py --camera-source v4l2
    python webrtc_yolo_minimal_jetson_h264.py --camera-source v4l2 \
        --v4l2-device /dev/video2 --h264-bitrate 3000000
    python webrtc_yolo_minimal_jetson_h264.py --camera-source tiscamera \
        --tiscamera-serial 26410280
"""

import argparse
import asyncio
import fractions
import threading
import time

from aiohttp import web
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from aiortc.codecs import get_encoder as software_get_encoder
from aiortc.codecs import h264
from aiortc.codecs.base import Encoder
import aiortc.rtcrtpsender as rtcrtpsender
import av

import webrtc_yolo_minimal as original
import webrtc_yolo_minimal_hw as capture_hw


H264_PROFILE_LEVEL_ID = "42e01f"
DEFAULT_H264_BITRATE = 3_000_000
MIN_H264_BITRATE = 500_000
MAX_H264_BITRATE = 20_000_000
settings = None


def _gst_import():
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "Jetson H.264 mode requires PyGObject and GStreamer 1.0"
        ) from exc
    Gst.init(None)
    return Gst


def check_jetson_encoder(Gst):
    """Fail instead of silently falling back to a CPU encoder."""
    missing = [
        name
        for name in ("appsrc", "nvvidconv", "nvv4l2h264enc", "appsink")
        if Gst.ElementFactory.find(name) is None
    ]
    if missing:
        raise RuntimeError(
            "Missing required Jetson GStreamer elements: " + ", ".join(missing)
        )


class JetsonH264Encoder(Encoder):
    """aiortc encoder adapter backed by Jetson ``nvv4l2h264enc``."""

    def __init__(self, bitrate=DEFAULT_H264_BITRATE):
        self.Gst = _gst_import()
        check_jetson_encoder(self.Gst)
        self.pipeline = None
        self.source = None
        self.sink = None
        self.encoder = None
        self.width = None
        self.height = None
        self._target_bitrate = self._clamp_bitrate(bitrate)
        self._active_bitrate = None
        self._frames_encoded = 0
        self._lock = threading.Lock()

    @staticmethod
    def _clamp_bitrate(value):
        return max(MIN_H264_BITRATE, min(int(value), MAX_H264_BITRATE))

    @property
    def target_bitrate(self):
        return self._target_bitrate

    @target_bitrate.setter
    def target_bitrate(self, value):
        self._target_bitrate = self._clamp_bitrate(value)

    def _pipeline_text(self, width, height):
        # PyAV supplies packed BGRx in host memory; nvvidconv performs the
        # BGRx -> NV12 conversion and uploads it to NVMM.  Avoiding a separate
        # GStreamer videoconvert is materially faster at 1080p on Jetson.
        return (
            # CameraVideoTrack already performs real-time pacing.  Keeping
            # appsrc non-live prevents a second 30 FPS clock wait inside the
            # encoder, which would add to capture / overlay preparation time.
            "appsrc name=src is-live=false block=true format=time "
            f"caps=video/x-raw,format=BGRx,width={width},height={height},"
            f"framerate={original.CAMERA_FPS}/1 ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
            "nvv4l2h264enc name=encoder control-rate=1 "
            f"bitrate={self._target_bitrate} iframeinterval={original.CAMERA_FPS} "
            f"idrinterval={original.CAMERA_FPS} profile=1 preset-level=1 "
            "insert-sps-pps=true insert-vui=true maxperf-enable=true "
            "copy-timestamp=true ! "
            "video/x-h264,stream-format=byte-stream,alignment=au,"
            "profile=constrained-baseline ! "
            "appsink name=sink max-buffers=1 drop=false sync=false"
        )

    def _start(self, width, height):
        self.close()
        pipeline_text = self._pipeline_text(width, height)
        self.pipeline = self.Gst.parse_launch(pipeline_text)
        self.source = self.pipeline.get_by_name("src")
        self.encoder = self.pipeline.get_by_name("encoder")
        self.sink = self.pipeline.get_by_name("sink")
        if any(element is None for element in (self.source, self.encoder, self.sink)):
            self.close()
            raise RuntimeError("Cannot create Jetson H.264 appsrc/encoder/appsink")

        result = self.pipeline.set_state(self.Gst.State.PLAYING)
        if result == self.Gst.StateChangeReturn.FAILURE:
            self.close()
            raise RuntimeError(
                "Cannot start nvv4l2h264enc; check Jetson device access"
            )
        self.width = width
        self.height = height
        self._active_bitrate = self._target_bitrate
        self._frames_encoded = 0

    def _needs_restart(self, frame):
        if self.pipeline is None:
            return True
        if (frame.width, frame.height) != (self.width, self.height):
            return True
        # Jetson R36 marks nvv4l2h264enc's bitrate property writable only in
        # NULL/READY.  Rebuilding the encoder for every REMB estimate causes a
        # visible stall and a fresh IDR, so keep the configured bitrate stable
        # for the lifetime of a resolution.  A later resolution restart picks
        # up the most recent estimate.
        return False

    def _check_bus(self):
        message = self.pipeline.get_bus().pop_filtered(
            self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS
        )
        if message is None:
            return
        if message.type == self.Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            raise RuntimeError(
                f"Jetson H.264 pipeline error: {error}; debug={debug}"
            )
        raise RuntimeError("Jetson H.264 pipeline reached end of stream")

    def encode(self, frame, force_keyframe=False):
        if not isinstance(frame, av.VideoFrame):
            raise TypeError("JetsonH264Encoder expects av.VideoFrame")

        with self._lock:
            if self._needs_restart(frame):
                self._start(frame.width, frame.height)
                force_keyframe = True

            if force_keyframe and self._frames_encoded:
                # nvv4l2h264enc exposes this action specifically for WebRTC PLI.
                # Do not emit it before the first input buffer: the encoder has
                # not created its NVENC channel yet on Jetson Linux R36 and the
                # action can crash the process.  A fresh encoder starts on IDR.
                self.encoder.emit("force-IDR")

            ndarray = frame.to_ndarray(format="bgra")
            data = ndarray.tobytes()
            buffer = self.Gst.Buffer.new_allocate(None, len(data), None)
            buffer.fill(0, data)
            pts = int(
                fractions.Fraction(frame.pts) * frame.time_base * self.Gst.SECOND
            )
            buffer.pts = pts
            buffer.dts = pts
            buffer.duration = self.Gst.SECOND // original.CAMERA_FPS

            result = self.source.emit("push-buffer", buffer)
            if result != self.Gst.FlowReturn.OK:
                raise RuntimeError(f"nvv4l2h264enc push failed: {result.value_nick}")

            # NVENC and nvvidconv are streaming components.  Do not serialize
            # them by waiting for the just-submitted frame.  aiortc explicitly
            # accepts an empty payload list for codec delay and will ask for
            # the next frame; by then the previous access unit is normally
            # ready.  This keeps one frame in flight through the hardware.
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
                raise RuntimeError("nvv4l2h264enc returned no Annex-B NAL units")
            self._frames_encoded += 1
            output_pts = encoded_buffer.pts
            if output_pts == self.Gst.CLOCK_TIME_NONE:
                timestamp = h264.convert_timebase(
                    frame.pts, frame.time_base, h264.VIDEO_TIME_BASE
                )
            else:
                timestamp = int(output_pts * 90000 // self.Gst.SECOND)
            return h264.H264Encoder._packetize(nal_units), timestamp

    def pack(self, packet):
        """Satisfy aiortc's Encoder protocol; this track supplies raw frames."""
        if not isinstance(packet, av.Packet):
            raise TypeError("JetsonH264Encoder.pack expects av.Packet")
        nal_units = h264.H264Encoder._split_bitstream(bytes(packet))
        timestamp = h264.convert_timebase(
            packet.pts, packet.time_base, h264.VIDEO_TIME_BASE
        )
        return h264.H264Encoder._packetize(nal_units), timestamp

    def close(self):
        pipeline = getattr(self, "pipeline", None)
        if pipeline is not None:
            pipeline.set_state(self.Gst.State.NULL)
        self.pipeline = None
        self.source = None
        self.sink = None
        self.encoder = None
        self.width = None
        self.height = None
        self._active_bitrate = None
        self._frames_encoded = 0

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def jetson_encoder_factory(codec):
    if codec.mimeType.lower() == "video/h264":
        return JetsonH264Encoder(settings.h264_bitrate)
    return software_get_encoder(codec)


def constrained_baseline_codecs():
    codecs = []
    for codec in RTCRtpSender.getCapabilities("video").codecs:
        if (
            codec.mimeType.lower() == "video/h264"
            and codec.parameters.get("profile-level-id")
            == H264_PROFILE_LEVEL_ID
        ):
            codecs.append(codec)
    if not codecs:
        raise RuntimeError(
            f"aiortc does not expose H.264 profile-level-id {H264_PROFILE_LEVEL_ID}"
        )
    return codecs


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(
        sdp=params["sdp"], type=params["type"]
    )

    pc = RTCPeerConnection()
    original.pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"WebRTC connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            original.pcs.discard(pc)

    # aiortc computes the common codec list while applying the remote offer.
    # Create and constrain the transceiver first; setting preferences after
    # setRemoteDescription leaves the offer's VP8-first ordering in effect.
    video = pc.addTransceiver("video", direction="sendonly")
    video.setCodecPreferences(constrained_baseline_codecs())
    await pc.setRemoteDescription(remote_offer)
    video.sender.replaceTrack(original.CameraVideoTrack(original.camera))

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


def build_app():
    app = web.Application()
    app.router.add_get("/", original.index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/api/camera", original.camera_status)
    app.router.add_post("/api/camera/control", original.camera_control)
    app.router.add_post("/api/capture", original.capture_frames)
    app.on_startup.append(original.on_startup)
    app.on_shutdown.append(original.on_shutdown)
    return app


def parse_args():
    parser = argparse.ArgumentParser(
        description="WebRTC YOLO using Jetson VIC and Jetson H.264 hardware encoding"
    )
    parser.add_argument(
        "--camera-source",
        choices=("v4l2", "tiscamera"),
        default="v4l2",
        help="camera source (default: %(default)s)",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=original.CAMERA_INDEX,
        help="V4L2 camera index (default: %(default)s)",
    )
    parser.add_argument(
        "--v4l2-device",
        default=None,
        help="V4L2 device path; overrides --camera-index",
    )
    parser.add_argument(
        "--tiscamera-serial",
        default=original.TISCAMERA_SERIAL,
        help="tiscamera serial number; empty selects the first camera",
    )
    parser.add_argument(
        "--h264-bitrate",
        type=int,
        default=DEFAULT_H264_BITRATE,
        help="initial H.264 bitrate in bits/s (default: %(default)s)",
    )
    return parser.parse_args()


def configure(parsed_args):
    global settings
    settings = parsed_args
    settings.h264_bitrate = JetsonH264Encoder._clamp_bitrate(
        settings.h264_bitrate
    )
    capture_hw.V4L2_DEVICE_OVERRIDE = settings.v4l2_device
    original.CameraManager = capture_hw.HardwareCameraManager
    original.args = settings

    # RTCRtpSender imports get_encoder into its module namespace.  Replace that
    # one reference before any sender is created; non-H.264 codecs retain the
    # stock factory, although SDP below permits H.264 only for video.
    rtcrtpsender.get_encoder = jetson_encoder_factory


if __name__ == "__main__":
    parsed = parse_args()
    configure(parsed)
    Gst = _gst_import()
    check_jetson_encoder(Gst)
    selected = parsed.v4l2_device or f"/dev/video{parsed.camera_index}"
    print(
        f"Hardware camera source: {parsed.camera_source}; device: {selected}; "
        f"requested format: {original.CAMERA_WIDTH}x{original.CAMERA_HEIGHT} "
        f"at {original.CAMERA_FPS} FPS"
    )
    print("Capture color path: YUY2 -> nvvidconv(VIC) -> BGRx -> BGR")
    print(
        "WebRTC encode path: BGR -> BGRx -> nvvidconv/NVMM -> "
        f"nvv4l2h264enc ({parsed.h264_bitrate} bit/s)"
    )
    print(f"Open http://<device-ip>:{original.HTTP_PORT} in a browser")
    web.run_app(
        build_app(), host=original.HTTP_HOST, port=original.HTTP_PORT
    )
