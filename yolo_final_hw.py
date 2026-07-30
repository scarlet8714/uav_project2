"""Jetson VIC-accelerated WebRTC variant of yolo_final.py.

All WebRTC, YOLO, GPS geolocation, temporal confirmation, camera controls,
runtime source/format switching, and shutdown behavior come from
``yolo_final.py``.  Only the GStreamer and tcambin camera conversion path is
replaced:

    camera YUY2 -> nvvidconv compute-hw=2 (VIC) -> BGRx -> BGR NumPy

The OpenCV backend remains available and uses the original software path.

Examples:
    python yolo_final_hw.py --camera-backend gstreamer
    python yolo_final_hw.py --camera-backend gstreamer \
        --gstreamer-device /dev/video0
    python yolo_final_hw.py --camera-backend tiscamera \
        --tiscamera-serial 26410280
"""

import argparse

import minimal_camera_control as controls
import webrtc_yolo_minimal_hw as vic
import yolo_final as original


class FinalHardwareCameraManager(controls.CameraManager):
    """Use VIC conversion for GStreamer/tcambin and retain OpenCV support."""

    def _open(self):
        if self.source_name == "v4l2":
            return controls.V4L2CameraSource(
                self.camera_index,
                self.serial,
                self.width,
                self.height,
                self.fps,
            )
        if self.source_name == "gstreamer":
            return vic.HardwareV4L2CameraSource(
                self.camera_index,
                self.serial,
                self.width,
                self.height,
                self.fps,
                self.gstreamer_device,
            )
        return vic.HardwareTiscameraCameraSource(
            self.camera_index,
            self.serial,
            self.width,
            self.height,
            self.fps,
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "YOLO GPS WebRTC stream using Jetson VIC for camera "
            "YUY2-to-BGRx conversion"
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
    return parser.parse_args()


if __name__ == "__main__":
    settings = parse_args()

    # yolo_final.create_camera resolves CameraManager from its module globals,
    # so replacing it here preserves the complete application above the camera
    # conversion layer.
    original.CameraManager = FinalHardwareCameraManager
    original.settings = settings

    print(
        f"Camera backend={settings.camera_backend}, "
        f"format={original.CAMERA_WIDTH}x{original.CAMERA_HEIGHT}"
        f"@{original.CAMERA_FPS}, decoder={settings.jpeg_decoder}"
    )
    if settings.camera_backend == "opencv":
        print("Color path: OpenCV software capture/conversion")
    else:
        print("Color path: YUY2 -> nvvidconv(VIC) -> BGRx -> BGR copy")
    print(f"Open http://<device-ip>:{original.HTTP_PORT} in a browser")
    original.web.run_app(
        original.app,
        host=original.HTTP_HOST,
        port=original.HTTP_PORT,
    )
