"""
Minimal OpenCV/tiscamera + YOLO + MJPEG experiment.

Run with a regular OpenCV camera:
    python mjpeg_yolo_minimal.py --camera-source opencv --camera-index 0

Run on Linux with tiscamera 0.14.0:
    python mjpeg_yolo_minimal.py --camera-source tiscamera
    python mjpeg_yolo_minimal.py --camera-source tiscamera \
        --tiscamera-serial 12345678

The tiscamera source requires tiscamera/tcamdutils 0.14.0, GStreamer 1.0,
and the Python GObject introspection bindings.
"""

import argparse
import sys
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request
from ultralytics import YOLO

from minimal_camera_control import CameraControlError, CameraManager
from minimal_control_ui import build_page

MODEL_PATH = "yolo11n.engine"
CAMERA_SOURCE = "opencv"
CAMERA_INDEX = 0
TISCAMERA_SERIAL = ""
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 30

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 5000

MJPEG_RECONNECT_SCRIPT = """
const streamImage = document.getElementById("mjpeg-stream");
const streamStatus = document.getElementById("connection-status");
let reconnectTimer = null;

function reconnectMjpeg() {
  streamStatus.textContent = "MJPEG：重新連線中…";
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    streamImage.src = "/video_feed?retry=" + Date.now();
  }, 1000);
}

streamImage.addEventListener("load", () => {
  streamStatus.textContent = "MJPEG：串流中";
});
streamImage.addEventListener("error", reconnectMjpeg);
streamStatus.textContent = "MJPEG：等待影像…";
"""


class OpenCVCameraSource:
    """1920x1080 30 FPS camera source using cv2.VideoCapture(0)."""

    def __init__(self, camera_index):
        self.capture = cv2.VideoCapture(camera_index)
        if not self.capture.isOpened():
            raise RuntimeError(
                f"Cannot open OpenCV camera index {camera_index}")

        self.capture.set(
            cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")
        )
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.capture.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        actual_width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.capture.get(cv2.CAP_PROP_FPS)
        print(
            f"OpenCV camera opened: {actual_width}x{actual_height} "
            f"at {actual_fps:g} FPS"
        )

    def read(self):
        return self.capture.read()

    def close(self):
        self.capture.release()


def build_tiscamera_pipeline(serial):
    escaped_serial = serial.replace("\\", "\\\\").replace('"', '\\"')
    source = "tcambin"
    if escaped_serial:
        source += f' serial="{escaped_serial}"'
    return (
        f"{source} ! "
        f"video/x-raw,format=BGRx,width={CAMERA_WIDTH},"
        f"height={CAMERA_HEIGHT},framerate={CAMERA_FPS}/1 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink max-buffers=1 drop=true sync=false"
    )


class TiscameraCameraSource:
    """Linux tiscamera 0.14.0 source using tcambin and GStreamer."""

    def __init__(self, serial):
        if not sys.platform.startswith("linux"):
            raise RuntimeError("tiscamera camera source requires Linux")

        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "tiscamera source requires PyGObject and GStreamer 1.0"
            ) from exc

        self.Gst = Gst
        Gst.init(None)
        pipeline_description = build_tiscamera_pipeline(serial)
        print(f"Opening tiscamera pipeline: {pipeline_description}")
        self.pipeline = Gst.parse_launch(pipeline_description)
        self.sink = self.pipeline.get_by_name("sink")
        if self.sink is None:
            raise RuntimeError("Cannot create the tiscamera GStreamer appsink")

        state_result = self.pipeline.set_state(Gst.State.PLAYING)
        if state_result == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(
                "Cannot start tiscamera. Verify tiscamera 0.14.0, tcambin, "
                "and the camera are available."
            )

    def read(self):
        sample = self.sink.emit("try-pull-sample", self.Gst.SECOND)
        if sample is None:
            return False, None

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        buffer = sample.get_buffer()
        mapped, map_info = buffer.map(self.Gst.MapFlags.READ)
        if not mapped:
            return False, None
        try:
            frame = np.ndarray(
                (height, width, 3),
                dtype=np.uint8,
                buffer=map_info.data,
            ).copy()
        finally:
            buffer.unmap(map_info)
        return True, frame

    def close(self):
        self.pipeline.set_state(self.Gst.State.NULL)


app = Flask(__name__)
model = YOLO(MODEL_PATH)
camera = None


def create_camera(camera_source, camera_index, tiscamera_serial):
    return CameraManager(
        camera_source,
        camera_index,
        tiscamera_serial,
        CAMERA_WIDTH,
        CAMERA_HEIGHT,
        CAMERA_FPS,
    )


def gen_frames():
    while True:
        success, frame = camera.read()
        if not success:
            # Format/source changes can temporarily interrupt capture.  Keep
            # this multipart response alive so the browser resumes without a
            # manual page refresh when frames become available again.
            time.sleep(0.1)
            continue

        results = model(frame, verbose=False)
        annotated_frame = results[0].plot()

        success, buffer = cv2.imencode(".jpg", annotated_frame)
        if not success:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )


@app.route("/")
def index():
    return build_page(
        "UAV YOLO MJPEG Stream",
        '<img id="mjpeg-stream" src="/video_feed" alt="MJPEG stream">',
        MJPEG_RECONNECT_SCRIPT,
    )


@app.route("/video_feed")
def video_feed():
    return Response(
        gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/camera")
def camera_status():
    try:
        return jsonify(camera.status())
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.post("/api/camera/control")
def camera_control():
    params = request.get_json(silent=True) or {}
    try:
        return jsonify(camera.apply(params.get("name"), params.get("value")))
    except (CameraControlError, TypeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stream 1920x1080 30 FPS camera video with YOLO over MJPEG"
    )
    parser.add_argument(
        "--camera-source",
        choices=("opencv", "tiscamera"),
        default=CAMERA_SOURCE,
        help="camera API to use (default: %(default)s)",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=CAMERA_INDEX,
        help="OpenCV device index (default: %(default)s)",
    )
    parser.add_argument(
        "--tiscamera-serial",
        default=TISCAMERA_SERIAL,
        help="tiscamera serial number; empty selects the first camera",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(
        f"Camera source: {args.camera_source}, index: {args.camera_index}, "
        f"requested format: {CAMERA_WIDTH}x{CAMERA_HEIGHT} at {CAMERA_FPS} FPS"
    )
    camera = create_camera(
        args.camera_source,
        args.camera_index,
        args.tiscamera_serial,
    )
    try:
        app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True)
    finally:
        camera.close()
