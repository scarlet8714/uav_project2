"""Legacy YOLO + GPS target geolocation MJPEG implementation.

This preserves the original MJPEG final variant from before the three camera
paths and shared camera-control GUI were integrated.
"""

import argparse
import time

import cv2
from flask import Flask, Response, render_template_string

from yolo_final_old import (
    CAMERA_BACKEND,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    GSTREAMER_DEVICE,
    GSTREAMER_JPEG_DECODER,
    HTTP_HOST,
    HTTP_PORT,
    YoloGpsProcessor,
)


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>YOLO GPS MJPEG stream</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; text-align: center; }
    img { width: min(100%, 1280px); margin-top: 16px; background: #000; }
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


app = Flask(__name__)
processor = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="YOLO GPS video streaming over MJPEG"
    )
    parser.add_argument(
        "--camera-backend",
        choices=("opencv", "gstreamer"),
        default=CAMERA_BACKEND,
    )
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument("--gstreamer-device", default=GSTREAMER_DEVICE)
    parser.add_argument(
        "--jpeg-decoder",
        choices=("jpegdec", "nvjpegdec"),
        default=GSTREAMER_JPEG_DECODER,
    )
    return parser.parse_args()


def generate_mjpeg():
    while True:
        frame = processor.get_frame()
        if frame is None:
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
    return render_template_string(HTML)


@app.get("/video_feed")
def video_feed():
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


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
