"""YOLO + GPS target geolocation streamed to browsers over MJPEG.

This is the MJPEG output variant of ``yolo_final.py``.  It reuses the same
camera, YOLO, temporal-confirmation, and GPS processing pipeline while
replacing the WebRTC transport with a simple HTTP multipart stream.

Camera examples:
    python yolo_final_mjpeg.py --camera-backend opencv
    python yolo_final_mjpeg.py --camera-backend gstreamer --jpeg-decoder jpegdec
    python yolo_final_mjpeg.py --camera-backend gstreamer --jpeg-decoder nvjpegdec

MJPEG dependencies are Flask and OpenCV.  GStreamer mode additionally
requires PyGObject and the selected GStreamer JPEG decoder plugin.
"""

import argparse

import cv2
from flask import Flask, Response, jsonify, request

from yolo_final import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    CAMERA_BACKEND,
    GSTREAMER_DEVICE,
    GSTREAMER_JPEG_DECODER,
    HTTP_HOST,
    HTTP_PORT,
    MODEL_PATH,
    TISCAMERA_SERIAL,
    YoloGpsProcessor,
)
from minimal_camera_control import CameraControlError
from minimal_control_ui import build_page


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>YOLO GPS MJPEG stream</title>
  <style>
    body {
      margin: 0;
      background: #111;
      color: #eee;
      font-family: sans-serif;
      text-align: center;
    }
    img {
      width: min(100%, 1280px);
      height: auto;
      margin-top: 16px;
      background: #000;
    }
    #status { margin: 12px; }
  </style>
</head>
<body>
  <h2>YOLO GPS MJPEG stream</h2>
  <div id="status">MJPEG: streaming</div>
  <img src="{{ url_for('video_feed') }}" alt="YOLO GPS MJPEG stream">
</body>
</html>
"""

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

HTML = build_page(
    "YOLO GPS MJPEG stream",
    '<img id="mjpeg-stream" src="/video_feed" alt="MJPEG stream">',
    MJPEG_RECONNECT_SCRIPT,
    source_options=(
        ("v4l2", "OpenCV / V4L2"),
        ("gstreamer", "GStreamer / v4l2src"),
        ("tiscamera", "GStreamer / tcambin"),
    ),
)


app = Flask(__name__)
processor = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="YOLO GPS video streaming over MJPEG"
    )
    parser.add_argument(
        "--camera-backend",
        choices=("opencv", "gstreamer", "tiscamera"),
        default=CAMERA_BACKEND,
    )
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--gstreamer-device", default=GSTREAMER_DEVICE)
    parser.add_argument(
        "--jpeg-decoder",
        choices=("jpegdec", "nvjpegdec"),
        default=GSTREAMER_JPEG_DECODER,
        help=(
            "legacy JPEG pipeline option; the current DFK AFU130-L53 "
            "v4l2src path uses raw YUY2"
        ),
    )
    parser.add_argument(
        "--tiscamera-serial",
        default=TISCAMERA_SERIAL,
        help="tiscamera serial; empty selects the first camera",
    )
    parser.add_argument(
        "--model-path",
        default=MODEL_PATH,
        help="YOLO .engine or .pt model path (default: %(default)s)",
    )
    return parser.parse_args()


def generate_mjpeg():
    """Encode the processor's latest annotated frame as multipart JPEG."""
    while True:
        frame = processor.get_frame()
        if frame is None:
            # The processor starts in a background thread; wait for its first
            # completed YOLO frame without blocking the capture thread.
            import time

            time.sleep(0.01)
            continue

        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + encoded.tobytes()
            + b"\r\n"
        )


@app.get("/")
def index():
    return HTML


@app.get("/video_feed")
def video_feed():
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/camera")
def camera_status():
    try:
        return jsonify(processor.camera_manager.status())
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.post("/api/camera/control")
def camera_control():
    params = request.get_json(silent=True) or {}
    try:
        result = processor.camera_manager.apply(
            params.get("name"), params.get("value")
        )
        return jsonify(result)
    except (CameraControlError, TypeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


if __name__ == "__main__":
    settings = parse_args()
    print(
        f"Camera backend={settings.camera_backend}, "
        f"format={CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}, "
        f"decoder={settings.jpeg_decoder}"
    )
    print(f"Open http://<device-ip>:{HTTP_PORT} in a browser")

    processor = YoloGpsProcessor(settings)
    try:
        app.run(
            host=HTTP_HOST,
            port=HTTP_PORT,
            threaded=True,
            use_reloader=False,
        )
    finally:
        processor.close()
