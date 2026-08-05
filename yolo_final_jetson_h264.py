"""YOLO final pipeline with Jetson VIC capture and Jetson H.264 WebRTC.

This variant keeps all behavior from ``yolo_final.py`` and the VIC camera
conversion from ``yolo_final_hw.py``.  It additionally replaces aiortc's
software video encoder with the tested ``nvv4l2h264enc`` adapter from
``webrtc_yolo_minimal_jetson_h264.py``.

The H.264 encoded appsink uses ``drop=false`` so completed reference frames
are never discarded before RTP packetization.  Raw frames may still be
dropped before the encoder to bound latency.

Examples:
    python yolo_final_jetson_h264.py --camera-backend gstreamer
    python yolo_final_jetson_h264.py --camera-backend gstreamer \
        --gstreamer-device /dev/video0 --h264-bitrate 3000000
    python yolo_final_jetson_h264.py --camera-backend tiscamera \
        --tiscamera-serial 26410280
"""

import argparse

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
import aiortc.rtcrtpsender as rtcrtpsender

import webrtc_yolo_minimal_jetson_h264 as h264_hw
import yolo_final as original
import yolo_final_hw as capture_hw


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(
        sdp=params["sdp"], type=params["type"]
    )
    pc = RTCPeerConnection()
    original.pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"[WebRTC] Connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            original.pcs.discard(pc)

    # aiortc fixes the common codec list while applying the remote offer, so
    # constrain the transceiver before setRemoteDescription.  Doing this later
    # leaves the client's VP8-first order in effect.
    video = pc.addTransceiver("video", direction="sendonly")
    video.setCodecPreferences(h264_hw.constrained_baseline_codecs())
    await pc.setRemoteDescription(remote_offer)
    video.sender.replaceTrack(original.CameraVideoTrack(original.processor))

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    })


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
        description=(
            "YOLO GPS WebRTC using Jetson VIC and Jetson H.264 hardware encoding"
        )
    )
    parser.add_argument(
        "--camera-backend",
        choices=("opencv", "gstreamer", "tiscamera"),
        default=original.CAMERA_BACKEND,
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=original.CAMERA_INDEX,
    )
    parser.add_argument(
        "--gstreamer-device",
        default=original.GSTREAMER_DEVICE,
    )
    parser.add_argument(
        "--jpeg-decoder",
        choices=("jpegdec", "nvjpegdec"),
        default=original.GSTREAMER_JPEG_DECODER,
        help=(
            "legacy compatibility option; VIC paths capture raw YUY2 and "
            "do not use a JPEG decoder"
        ),
    )
    parser.add_argument(
        "--tiscamera-serial",
        default=original.TISCAMERA_SERIAL,
        help="tiscamera serial; empty selects the first camera",
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
    return parser.parse_args()


def configure(parsed_args):
    parsed_args.h264_bitrate = h264_hw.JetsonH264Encoder._clamp_bitrate(
        parsed_args.h264_bitrate
    )
    original.CameraManager = capture_hw.FinalHardwareCameraManager
    original.settings = parsed_args

    # The shared encoder factory reads its bitrate from module settings.
    h264_hw.settings = parsed_args
    rtcrtpsender.get_encoder = h264_hw.jetson_encoder_factory


if __name__ == "__main__":
    settings = parse_args()
    configure(settings)
    Gst = h264_hw._gst_import()
    h264_hw.check_jetson_encoder(Gst)

    print(
        f"Camera backend={settings.camera_backend}, "
        f"format={original.CAMERA_WIDTH}x{original.CAMERA_HEIGHT}"
        f"@{original.CAMERA_FPS}, decoder={settings.jpeg_decoder}"
    )
    if settings.camera_backend == "opencv":
        print("Color path: OpenCV software capture/conversion")
    else:
        print("Color path: YUY2 -> nvvidconv(VIC) -> BGRx -> BGR copy")
    print(
        "WebRTC encode path: BGR -> BGRx -> nvvidconv/NVMM -> "
        f"nvv4l2h264enc ({settings.h264_bitrate} bit/s, drop=false)"
    )
    print(f"Open http://<device-ip>:{original.HTTP_PORT} in a browser")
    original.web.run_app(
        build_app(),
        host=original.HTTP_HOST,
        port=original.HTTP_PORT,
    )
