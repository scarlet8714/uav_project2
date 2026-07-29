"""Shared runtime camera switching and controls for the minimal demos."""

import subprocess
import sys
import threading

import cv2
import numpy as np


RESOLUTIONS = (
    (4128, 3096),
    (1920, 1080),
    (1600, 1200),
    (1280, 960),
    (1280, 720),
    (800, 480),
    (640, 480),
)
FPS_OPTIONS = (30, 25, 20, 15, 10, 5, 1)
CONTROL_NAMES = (
    "exposure",
    "brightness",
    "contrast",
    "saturation",
    "gain",
    "sharpness",
)

V4L2_NAMES = {
    "exposure": "exposure_time_us",
    "brightness": "brightness",
    "contrast": "atr_contrast",
    "saturation": "saturation",
    "gain": "gain",
    "sharpness": "sharpness",
}
TISCAMERA_NAMES = {
    "exposure": "Exposure Time (us)",
    "brightness": "Brightness",
    "contrast": "ATR Contrast",
    "saturation": "Saturation",
    "gain": "Gain",
    "sharpness": "Sharpness",
}


class CameraControlError(RuntimeError):
    pass


class V4L2CameraSource:
    def __init__(self, camera_index, _serial, width, height, fps):
        if not sys.platform.startswith("linux"):
            raise CameraControlError("V4L2 mode requires Linux")
        self.camera_index = camera_index
        self.device = f"/dev/video{camera_index}"
        self.width = width
        self.height = height
        self.fps = fps
        self.capture = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise CameraControlError(f"Cannot open V4L2 device {self.device}")
        self.capture.set(
            cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")
        )
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        print(
            f"V4L2 camera opened: {self.width}x{self.height} "
            f"at {self.fps:g} FPS"
        )

    def read(self):
        return self.capture.read()

    def _v4l2_ctl(self, *arguments):
        command = ["v4l2-ctl", "-d", self.device, *arguments]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise CameraControlError(detail or "v4l2-ctl failed")
        return result.stdout.strip()

    def set_control(self, name, value):
        control = V4L2_NAMES[name]
        if name == "exposure":
            self._v4l2_ctl("--set-ctrl", "auto_shutter=0")
        elif name == "gain":
            self._v4l2_ctl("--set-ctrl", "gain_auto=0")
        self._v4l2_ctl("--set-ctrl", f"{control}={int(value)}")
        return self.get_control(name)

    def get_control(self, name):
        control = V4L2_NAMES[name]
        output = self._v4l2_ctl("--get-ctrl", control)
        try:
            return int(output.rsplit(":", 1)[1].strip())
        except (IndexError, ValueError) as exc:
            raise CameraControlError(
                f"Cannot parse v4l2 value: {output}"
            ) from exc

    def supports_focus_one_push(self):
        try:
            return "auto_focus_one_push" in self._v4l2_ctl(
                "--list-ctrls"
            )
        except CameraControlError:
            return False

    def focus_one_push(self):
        if not self.supports_focus_one_push():
            raise CameraControlError(
                "V4L2 one-push focus is not supported"
            )
        self._v4l2_ctl("--set-ctrl", "auto_focus_one_push=1")
        return {"name": "focus_one_push", "triggered": True}

    def close(self):
        self.capture.release()


class GStreamerV4L2CameraSource(V4L2CameraSource):
    """GStreamer v4l2src capture with V4L2 controls."""

    def __init__(
        self, camera_index, _serial, width, height, fps, device=None
    ):
        if not sys.platform.startswith("linux"):
            raise CameraControlError("GStreamer V4L2 mode requires Linux")
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise CameraControlError(
                "GStreamer V4L2 mode requires PyGObject and GStreamer 1.0"
            ) from exc

        self.Gst = Gst
        self.camera_index = camera_index
        self.device = device or f"/dev/video{camera_index}"
        self.width = width
        self.height = height
        self.fps = fps
        Gst.init(None)
        pipeline_text = (
            f"v4l2src device={self.device} ! "
            f"video/x-raw,format=YUY2,width={width},height={height},"
            f"framerate={fps}/1 ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink name=sink "
            "max-buffers=1 drop=true sync=false"
        )
        print(f"Opening GStreamer V4L2 pipeline: {pipeline_text}")
        self.pipeline = Gst.parse_launch(pipeline_text)
        self.sink = self.pipeline.get_by_name("sink")
        if self.sink is None:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError("Cannot create GStreamer V4L2 appsink")
        state = self.pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError(
                "Cannot start GStreamer V4L2 pipeline"
            )
        state, current, _pending = self.pipeline.get_state(
            5 * Gst.SECOND
        )
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError(
                f"GStreamer V4L2 failed to start (state={current.value_nick})"
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
                print(f"GStreamer V4L2 error: {error}; debug={debug}")
            return False, None
        timeout_seconds = max(5.0, 3.0 / self.fps)
        sample = self.sink.emit(
            "try-pull-sample", int(timeout_seconds * self.Gst.SECOND)
        )
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
            frame = np.ndarray(
                (height, width, 3), dtype=np.uint8, buffer=map_info.data
            ).copy()
        finally:
            buffer.unmap(map_info)
        return True, frame

    def close(self):
        self.pipeline.set_state(self.Gst.State.NULL)


class TiscameraCameraSource:
    def __init__(self, _camera_index, serial, width, height, fps):
        if not sys.platform.startswith("linux"):
            raise CameraControlError("tiscamera mode requires Linux")
        try:
            import gi

            gi.require_version("Gst", "1.0")
            gi.require_version("Tcam", "0.1")
            from gi.repository import Gst, Tcam  # noqa: F401
        except (ImportError, ValueError) as exc:
            raise CameraControlError(
                "tiscamera requires PyGObject and GStreamer 1.0"
            ) from exc

        self.Gst = Gst
        self.width = width
        self.height = height
        self.fps = fps
        Gst.init(None)
        escaped = serial.replace("\\", "\\\\").replace('"', '\\"')
        source = "tcambin name=camera_source"
        if escaped:
            source += f' serial="{escaped}"'
        pipeline_text = (
            f"{source} ! video/x-raw,format=BGRx,width={width},"
            f"height={height},framerate={fps}/1 ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink name=sink "
            "max-buffers=1 drop=true sync=false"
        )
        print(f"Opening tiscamera pipeline: {pipeline_text}")
        self.pipeline = Gst.parse_launch(pipeline_text)
        self.source = self.pipeline.get_by_name("camera_source")
        self.sink = self.pipeline.get_by_name("sink")
        if self.source is None or self.sink is None:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError("Cannot create tiscamera elements")
        state = self.pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError("Cannot start tiscamera pipeline")
        state, current, _pending = self.pipeline.get_state(
            5 * Gst.SECOND
        )
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise CameraControlError(
                f"tiscamera failed to start (state={current.value_nick})"
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
                print(f"tiscamera error: {error}; debug={debug}")
            return False, None
        timeout_seconds = max(5.0, 3.0 / self.fps)
        sample = self.sink.emit(
            "try-pull-sample", int(timeout_seconds * self.Gst.SECOND)
        )
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
            frame = np.ndarray(
                (height, width, 3), dtype=np.uint8, buffer=map_info.data
            ).copy()
        finally:
            buffer.unmap(map_info)
        return True, frame

    def set_control(self, name, value):
        prop = TISCAMERA_NAMES[name]
        available = self.source.get_tcam_property_names()
        if prop not in available:
            raise CameraControlError(
                f"tiscamera property {prop!r} is not supported"
            )
        if name == "exposure" and "Exposure Auto" in available:
            self.source.set_tcam_property("Exposure Auto", False)
        elif name == "gain" and "Gain Auto" in available:
            self.source.set_tcam_property("Gain Auto", False)
        if not self.source.set_tcam_property(prop, int(value)):
            raise CameraControlError(f"tiscamera rejected {prop}")
        return self.get_control(name)

    def get_control(self, name):
        prop = TISCAMERA_NAMES[name]
        available = self.source.get_tcam_property_names()
        if prop not in available:
            raise CameraControlError(
                f"tiscamera property {prop!r} is not supported"
            )
        result = self.source.get_tcam_property(prop)
        if not result[0]:
            raise CameraControlError(f"Cannot read tiscamera property {prop}")
        return result[1]

    def supports_focus_one_push(self):
        return "Auto Focus One Push" in self.source.get_tcam_property_names()

    def focus_one_push(self):
        if not self.supports_focus_one_push():
            raise CameraControlError(
                "tiscamera one-push focus is not supported"
            )
        if not self.source.set_tcam_property("Auto Focus One Push", True):
            raise CameraControlError(
                "tiscamera rejected the one-push focus trigger"
            )
        return {"name": "focus_one_push", "triggered": True}

    def close(self):
        self.pipeline.set_state(self.Gst.State.NULL)


class CameraManager:
    """Serializes capture, source switching, format changes and controls."""

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
        self.lock = threading.RLock()
        self.source_name = self._normalize_source(source)
        self.camera_index = camera_index
        self.serial = serial
        self.gstreamer_device = gstreamer_device
        self.width = width
        self.height = height
        self.fps = fps
        self.camera = self._open()

    @staticmethod
    def _normalize_source(source):
        aliases = {
            "opencv": "v4l2",
            "v4l2": "v4l2",
            "gstreamer": "gstreamer",
            "gstreamer_v4l2src": "gstreamer",
            "tiscamera": "tiscamera",
            "tcambin": "tiscamera",
        }
        try:
            return aliases[source]
        except KeyError as exc:
            raise CameraControlError(
                f"Unknown camera source: {source}"
            ) from exc

    def _open(self):
        if self.source_name == "v4l2":
            cls = V4L2CameraSource
        elif self.source_name == "gstreamer":
            return GStreamerV4L2CameraSource(
                self.camera_index,
                self.serial,
                self.width,
                self.height,
                self.fps,
                self.gstreamer_device,
            )
        else:
            cls = TiscameraCameraSource
        return cls(
            self.camera_index,
            self.serial,
            self.width,
            self.height,
            self.fps,
        )

    def read(self):
        with self.lock:
            return self.camera.read()

    def status(self):
        with self.lock:
            controls = {}
            for name in CONTROL_NAMES:
                try:
                    controls[name] = {
                        "supported": True,
                        "value": self.camera.get_control(name),
                    }
                except Exception as exc:
                    controls[name] = {
                        "supported": False,
                        "error": str(exc),
                    }
            return {
                "source": self.source_name,
                "resolution": f"{self.width}x{self.height}",
                "fps": self.fps,
                "controls": controls,
                "actions": {
                    "focus_one_push": {
                        "supported": self.camera.supports_focus_one_push()
                    }
                },
            }

    def apply(self, name, value):
        with self.lock:
            if name == "source":
                requested = self._normalize_source(str(value))
                if requested == self.source_name:
                    return self.status()
                return self._reopen(source=requested)
            if name == "resolution":
                try:
                    width, height = map(int, str(value).lower().split("x"))
                except (TypeError, ValueError) as exc:
                    raise CameraControlError("Resolution must be WIDTHxHEIGHT") from exc
                if (width, height) not in RESOLUTIONS:
                    raise CameraControlError("Unsupported resolution")
                fps = 1 if (width, height) == (4128, 3096) else self.fps
                if fps == 1 and (width, height) != (4128, 3096):
                    fps = 30
                return self._reopen(width=width, height=height, fps=fps)
            if name == "fps":
                fps = int(value)
                if fps not in FPS_OPTIONS:
                    raise CameraControlError("Unsupported FPS")
                if (self.width, self.height) == (4128, 3096) and fps != 1:
                    raise CameraControlError(
                        "4128x3096 resolution requires 1 FPS"
                    )
                return self._reopen(fps=fps)
            if name == "focus_one_push":
                return self.camera.focus_one_push()
            if name not in CONTROL_NAMES:
                raise CameraControlError(f"Unknown control: {name}")
            actual = self.camera.set_control(name, int(value))
            return {"name": name, "requested": int(value), "actual": actual}

    def _reopen(self, source=None, width=None, height=None, fps=None):
        old = (
            self.source_name, self.width, self.height, self.fps, self.camera
        )
        new_source = source or self.source_name
        new_width = width or self.width
        new_height = height or self.height
        new_fps = fps or self.fps
        old[4].close()
        self.source_name = new_source
        self.width = new_width
        self.height = new_height
        self.fps = new_fps
        try:
            self.camera = self._open()
        except Exception:
            self.source_name, self.width, self.height, self.fps = old[:4]
            self.camera = self._open()
            raise
        return self.status()

    def close(self):
        with self.lock:
            self.camera.close()
