"""YOLO/GPS WebRTC relay using RTSP plus Jetson hardware codecs.

This entry point retains the detection, temporal confirmation, GPS target
projection, FPS overlay, frame capture, and WebRTC behavior from
``yolo_final.py``.  The video path is:

    RTSP H.264 -> nvv4l2decoder -> nvvidconv -> BGR -> YOLO / GPS overlay
    -> nvvidconv -> NVMM/NV12 -> nvv4l2h264enc -> H.264 WebRTC

Run:
    python yolo_final_rtsp.py
    python yolo_final_rtsp.py \
        --rtsp-url rtsp://192.168.144.135/live \
        --h264-bitrate 3000000
"""

import argparse
import time

import aiortc.rtcrtpsender as rtcrtpsender

from minimal_camera_control import CONTROL_NAMES, CameraControlError
from minimal_control_ui import build_page
import rtsp_minimal as rtsp_hw
import webrtc_yolo_minimal_jetson_h264 as h264_hw
import yolo_final as original
import yolo_final_jetson_h264 as final_h264


class RtspCameraManager:
    """Adapt the hardware RTSP decoder to yolo_final's camera interface."""

    def __init__(self, settings):
        self.source_name = "rtsp"
        self.fps = settings.fps
        self.decoder = rtsp_hw.RtspHardwareSource(
            settings.rtsp_url,
            settings.rtsp_latency,
            settings.rtsp_timeout,
        )
        self.delivered_sequence = 0
        self.running = True

    def read(self):
        deadline = time.monotonic() + original.CAMERA_READ_TIMEOUT_SEC
        while self.running and time.monotonic() < deadline:
            decoder_status = self.decoder.status()
            sequence = decoder_status["frames"]
            if sequence > self.delivered_sequence:
                frame = self.decoder.get_frame()
                if frame is not None:
                    self.delivered_sequence = sequence
                    return True, frame
            time.sleep(0.005)
        return False, None

    def status(self):
        decoder_status = self.decoder.status()
        unsupported = "RTSP input does not expose local camera controls"
        return {
            "source": self.source_name,
            "resolution": (
                decoder_status["resolution"]
                or f"{original.CAMERA_WIDTH}x{original.CAMERA_HEIGHT}"
            ),
            "fps": self.fps,
            "controls": {
                name: {"supported": False, "error": unsupported}
                for name in CONTROL_NAMES
            },
            "actions": {"focus_one_push": {"supported": False}},
            "rtsp": decoder_status,
        }

    def apply(self, name, value):
        if name == "source" and value == "rtsp":
            return self.status()
        raise CameraControlError(
            "RTSP source settings are configured with command-line options"
        )

    def close(self):
        self.running = False
        self.decoder.close()


def create_rtsp_camera(settings):
    manager = RtspCameraManager(settings)
    return manager, original.LatestFrameCamera(manager)


def parse_args():
    parser = argparse.ArgumentParser(
        description="YOLO GPS RTSP-to-WebRTC with Jetson H.264 hardware codecs"
    )
    parser.add_argument(
        "--rtsp-url",
        default=rtsp_hw.DEFAULT_RTSP_URL,
        help="H.264 RTSP input URL (default: %(default)s)",
    )
    parser.add_argument(
        "--rtsp-latency",
        type=int,
        default=100,
        help="RTSP jitter-buffer latency in ms (default: %(default)s)",
    )
    parser.add_argument(
        "--rtsp-timeout",
        type=float,
        default=5.0,
        help="RTSP TCP timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=original.CAMERA_FPS,
        help="WebRTC output FPS (default: %(default)s)",
    )
    parser.add_argument(
        "--model-path",
        default=original.MODEL_PATH,
        help="YOLO .engine or .pt model path (default: %(default)s)",
    )
    parser.add_argument(
        "--h264-bitrate",
        type=int,
        default=h264_hw.DEFAULT_H264_BITRATE,
        help="fixed H.264 bitrate in bits/s (default: %(default)s)",
    )
    parser.add_argument(
        "--host", default=original.HTTP_HOST, help="HTTP bind address"
    )
    parser.add_argument(
        "--port", type=int, default=original.HTTP_PORT, help="HTTP port"
    )
    args = parser.parse_args()
    if args.rtsp_latency < 0:
        parser.error("--rtsp-latency must be zero or greater")
    if args.rtsp_timeout <= 0:
        parser.error("--rtsp-timeout must be greater than zero")
    if args.fps <= 0 or 90_000 % args.fps:
        parser.error("--fps must be a positive divisor of 90000")
    args.h264_bitrate = h264_hw.JetsonH264Encoder._clamp_bitrate(
        args.h264_bitrate
    )
    return args


def configure(settings):
    # YoloGpsProcessor resolves this function from yolo_final's module globals.
    original.create_camera = create_rtsp_camera
    original.settings = settings

    # The final track currently uses this module constant for pacing/timestamps.
    original.CAMERA_FPS = settings.fps
    h264_hw.original.CAMERA_FPS = settings.fps

    original.HTML = build_page(
        "YOLO GPS RTSP WebRTC stream",
        '<video id="video" autoplay playsinline muted></video>',
        original.FINAL_WEBRTC_SCRIPT,
        source_options=(("rtsp", "RTSP / H.264"),),
    )

    # aiortc imports get_encoder into rtcrtpsender's namespace.  Replace it
    # before peers are created, and offer only H.264 constrained-baseline.
    h264_hw.settings = settings
    rtcrtpsender.get_encoder = h264_hw.jetson_encoder_factory


if __name__ == "__main__":
    settings = parse_args()
    configure(settings)

    Gst = rtsp_hw.gst_import()
    rtsp_hw.check_gstreamer(Gst)
    h264_hw.check_jetson_encoder(Gst)

    print(f"RTSP input: {settings.rtsp_url}")
    print("Decode: H.264 -> nvv4l2decoder -> nvvidconv -> BGRx/BGR")
    print(
        f"YOLO/GPS: {settings.model_path}; WebRTC output: {settings.fps} FPS"
    )
    print(
        "Encode: BGR -> BGRx -> nvvidconv/NVMM -> "
        f"nvv4l2h264enc ({settings.h264_bitrate} bit/s)"
    )
    print(f"Open http://<device-ip>:{settings.port} in a browser")
    original.web.run_app(
        final_h264.build_app(), host=settings.host, port=settings.port
    )
