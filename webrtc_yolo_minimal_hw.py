"""
Jetson VIC-accelerated variant of webrtc_yolo_minimal.py.

This version reuses the WebRTC output track (including its FPS overlay) from
webrtc_yolo_minimal.py.  GStreamer captures YUY2 (the GStreamer name for V4L2
YUYV) and nvvidconv performs the YUY2 -> BGRx conversion on the Jetson VIC.
BGRx is then mapped to a contiguous three-channel BGR NumPy array because
Ultralytics expects BGR images.

Examples:
    python webrtc_yolo_minimal_hw.py --camera-source v4l2
    python webrtc_yolo_minimal_hw.py --camera-source v4l2 \
        --v4l2-device /dev/video2
    python webrtc_yolo_minimal_hw.py --camera-source tiscamera
    python webrtc_yolo_minimal_hw.py --camera-source tiscamera \
        --tiscamera-serial 26410280
"""

import argparse
import sys

import numpy as np

import minimal_camera_control as controls
import webrtc_yolo_minimal as original

V4L2_DEVICE_OVERRIDE = None


class _HardwareGStreamerMixin:
    """Shared lifecycle and BGRx appsink handling."""

    pipeline_label = "GStreamer"

    def _start_pipeline(self, pipeline_text):
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise controls.CameraControlError(
                "This mode requires PyGObject and GStreamer 1.0"
            ) from exc

        self.Gst = Gst
        Gst.init(None)

        # Fail early with a useful message instead of a parse-launch error.
        if Gst.ElementFactory.find("nvvidconv") is None:
            raise controls.CameraControlError(
                "nvvidconv is not installed; install the Jetson NVIDIA "
                "GStreamer multimedia packages"
            )

        print(f"Opening {self.pipeline_label} hardware pipeline: {pipeline_text}")
        self.pipeline = Gst.parse_launch(pipeline_text)
        self.sink = self.pipeline.get_by_name("sink")
        if self.sink is None:
            self.pipeline.set_state(Gst.State.NULL)
            raise controls.CameraControlError("Cannot create GStreamer appsink")

        state = self.pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise controls.CameraControlError(
                f"Cannot start {self.pipeline_label} hardware pipeline"
            )
        state, current, _pending = self.pipeline.get_state(5 * Gst.SECOND)
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise controls.CameraControlError(
                f"{self.pipeline_label} failed to start "
                f"(state={current.value_nick})"
            )

        self.bus = self.pipeline.get_bus()
        self.failed = False

    def read(self):
        if self.failed:
            return False, None

        message = self.bus.pop_filtered(
            self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS
        )
        if message is not None:
            self.failed = True
            if message.type == self.Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                print(
                    f"{self.pipeline_label} pipeline error: "
                    f"{error}; debug={debug}"
                )
            else:
                print(f"{self.pipeline_label} pipeline reached end of stream")
            return False, None

        timeout = int(max(5.0, 3.0 / self.fps) * self.Gst.SECOND)
        sample = self.sink.emit("try-pull-sample", timeout)
        if sample is None:
            return False, None

        structure = sample.get_caps().get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        buffer = sample.get_buffer()
        mapped, map_info = buffer.map(self.Gst.MapFlags.READ)
        if not mapped:
            return False, None

        try:
            # GstVideo buffers may pad each row.  Deriving the row stride makes
            # the mapping safe for both tightly packed and aligned BGRx frames.
            row_stride = map_info.size // height
            if row_stride < width * 4:
                raise controls.CameraControlError(
                    f"Invalid BGRx buffer stride: {row_stride}"
                )
            bgrx = np.ndarray(
                (height, width, 4),
                dtype=np.uint8,
                buffer=map_info.data,
                strides=(row_stride, 4, 1),
            )
            # BGRx -> BGR is channel removal only, not color conversion.
            # copy() also releases the GStreamer buffer before returning.
            frame = bgrx[:, :, :3].copy()
        finally:
            buffer.unmap(map_info)
        return True, frame

    def close(self):
        self.pipeline.set_state(self.Gst.State.NULL)


class HardwareV4L2CameraSource(
    _HardwareGStreamerMixin, controls.V4L2CameraSource
):
    """v4l2src YUY2 capture with VIC color conversion."""

    pipeline_label = "V4L2/nvvidconv"

    def __init__(self, camera_index, _serial, width, height, fps, device=None):
        if not sys.platform.startswith("linux"):
            raise controls.CameraControlError("V4L2 mode requires Linux")
        self.camera_index = camera_index
        self.device = device or f"/dev/video{camera_index}"
        self.width = width
        self.height = height
        self.fps = fps
        pipeline_text = (
            f"v4l2src device={self.device} do-timestamp=true ! "
            f"video/x-raw,format=YUY2,width={width},height={height},"
            f"framerate={fps}/1 ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "nvvidconv compute-hw=2 ! "
            "video/x-raw,format=BGRx ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self._start_pipeline(pipeline_text)


class HardwareTiscameraCameraSource(
    _HardwareGStreamerMixin, controls.TiscameraCameraSource
):
    """tcambin YUY2 capture with VIC color conversion."""

    pipeline_label = "tiscamera/nvvidconv"

    def __init__(self, _camera_index, serial, width, height, fps):
        if not sys.platform.startswith("linux"):
            raise controls.CameraControlError("tiscamera mode requires Linux")
        try:
            import gi

            gi.require_version("Tcam", "0.1")
            from gi.repository import Tcam  # noqa: F401
        except (ImportError, ValueError) as exc:
            raise controls.CameraControlError(
                "tiscamera requires Tcam 0.1 introspection"
            ) from exc

        self.width = width
        self.height = height
        self.fps = fps
        escaped = serial.replace("\\", "\\\\").replace('"', '\\"')
        source = "tcambin name=camera_source"
        if escaped:
            source += f' serial="{escaped}"'
        pipeline_text = (
            f"{source} ! "
            f"video/x-raw,format=YUY2,width={width},height={height},"
            f"framerate={fps}/1 ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "nvvidconv compute-hw=2 ! "
            "video/x-raw,format=BGRx ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self._start_pipeline(pipeline_text)
        self.source = self.pipeline.get_by_name("camera_source")
        if self.source is None:
            self.close()
            raise controls.CameraControlError("Cannot create tcambin source")


class HardwareCameraManager(controls.CameraManager):
    """CameraManager that always uses the hardware conversion sources."""

    def __init__(
        self,
        source,
        camera_index,
        serial,
        width,
        height,
        fps,
        gstreamer_device=None,
    ):
        super().__init__(
            source,
            camera_index,
            serial,
            width,
            height,
            fps,
            gstreamer_device or V4L2_DEVICE_OVERRIDE,
        )

    def _open(self):
        if self.source_name in ("v4l2", "gstreamer"):
            return HardwareV4L2CameraSource(
                self.camera_index,
                self.serial,
                self.width,
                self.height,
                self.fps,
                self.gstreamer_device,
            )
        return HardwareTiscameraCameraSource(
            self.camera_index,
            self.serial,
            self.width,
            self.height,
            self.fps,
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "WebRTC YOLO demo using Jetson VIC for YUY2-to-BGRx conversion"
        )
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
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    V4L2_DEVICE_OVERRIDE = args.v4l2_device

    # Reuse the WebRTC, YOLO, UI and shutdown code from the original without
    # modifying it.  YoloCamera looks up CameraManager in that module at runtime.
    original.CameraManager = HardwareCameraManager
    original.args = args

    selected = args.v4l2_device or f"/dev/video{args.camera_index}"
    print(
        f"Hardware camera source: {args.camera_source}; device: {selected}; "
        f"requested format: {original.CAMERA_WIDTH}x"
        f"{original.CAMERA_HEIGHT} at {original.CAMERA_FPS} FPS"
    )
    print("Color path: YUY2/YUYV -> nvvidconv(VIC) -> BGRx -> BGR view/copy")
    print(f"Open http://<device-ip>:{original.HTTP_PORT} in a browser")
    original.web.run_app(
        original.app, host=original.HTTP_HOST, port=original.HTTP_PORT
    )
