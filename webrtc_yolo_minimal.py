"""
Minimal OpenCV/tiscamera + YOLO + WebRTC experiment.

Install dependencies:
    python3 -m pip install aiohttp aiortc av ultralytics opencv-python

Run:
    python webrtc_yolo_minimal.py --camera-source opencv --camera-index 0
    python webrtc_yolo_minimal.py --camera-source tiscamera
    python webrtc_yolo_minimal.py --camera-source tiscamera \
        --tiscamera-serial 12345678

The tiscamera source requires Linux, tiscamera/tcamdutils 0.14.0,
GStreamer 1.0, and the Python GObject introspection bindings.
"""

import argparse
import asyncio
import fractions
import sys
import threading
import time

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from ultralytics import YOLO

from minimal_camera_control import CameraControlError, CameraManager
from minimal_control_ui import build_page
from minimal_frame_capture import FrameCapture

# Only change this value to use another YOLO model.
MODEL_PATH = "yolo11s.engine"

CAMERA_INDEX = 0
CAMERA_SOURCE = "opencv"
TISCAMERA_SERIAL = ""
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 30
YOLO_CONF = 0.4

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
frame_capture = FrameCapture()


class FpsOverlay:
    """Measure smoothed output FPS and draw it on a BGR frame."""

    def __init__(self, smoothing=0.1):
        self.smoothing = smoothing
        self.last_time = None
        self.fps = None

    def draw(self, frame):
        now = time.monotonic()
        if self.last_time is not None:
            elapsed = now - self.last_time
            if elapsed > 0:
                current_fps = 1.0 / elapsed
                self.fps = (
                    current_fps
                    if self.fps is None
                    else self.fps * (1.0 - self.smoothing)
                    + current_fps * self.smoothing
                )
        self.last_time = now

        label = "FPS: --" if self.fps is None else f"FPS: {self.fps:.1f}"
        origin = (20, 45)
        cv2.putText(
            frame, label, origin, cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (0, 0, 0), 4, cv2.LINE_AA,
        )
        cv2.putText(
            frame, label, origin, cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (0, 255, 0), 2, cv2.LINE_AA,
        )


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>WebRTC YOLO test</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; text-align: center; }
    video { width: min(100%, 1280px); margin-top: 16px; background: #000; }
    #status { margin: 12px; }
  </style>
</head>
<body>
  <h2>WebRTC YOLO test</h2>
  <div id="status">Connecting...</div>
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
        const checkState = () => {
          if (peer.iceGatheringState === "complete") {
            peer.removeEventListener("icegatheringstatechange", checkState);
            resolve();
          }
        };
        peer.addEventListener("icegatheringstatechange", checkState);
      });

      const response = await fetch("/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp: peer.localDescription.sdp,
          type: peer.localDescription.type
        })
      });

      if (!response.ok) throw new Error(await response.text());
      const answer = await response.json();
      await peer.setRemoteDescription(answer);
    }

    start().catch(error => {
      console.error(error);
      statusElement.textContent = "Error: " + error.message;
    });
  </script>
</body>
</html>
"""

WEBRTC_SCRIPT = """
const statusElement = document.getElementById("connection-status");
statusElement.textContent = "WebRTC: connecting";
const peer = new RTCPeerConnection();
peer.addTransceiver("video", { direction: "recvonly" });
peer.ontrack = event => {
  document.getElementById("video").srcObject = event.streams[0];
};
peer.onconnectionstatechange = () => {
  statusElement.textContent = "WebRTC: " + peer.connectionState;
};
async function startWebRTC() {
  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  await new Promise(resolve => {
    if (peer.iceGatheringState === "complete") return resolve();
    const checkState = () => {
      if (peer.iceGatheringState === "complete") {
        peer.removeEventListener("icegatheringstatechange", checkState);
        resolve();
      }
    };
    peer.addEventListener("icegatheringstatechange", checkState);
  });
  const response = await fetch("/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: peer.localDescription.sdp,
      type: peer.localDescription.type
    })
  });
  if (!response.ok) throw new Error(await response.text());
  await peer.setRemoteDescription(await response.json());
}
startWebRTC().catch(error => {
  statusElement.textContent = "WebRTC error: " + error.message;
});
"""

HTML = build_page(
    "UAV YOLO WebRTC Stream",
    '<video id="video" autoplay playsinline muted></video>',
    WEBRTC_SCRIPT,
)


class OpenCVCameraSource:
    """Camera source using cv2.VideoCapture, matching the diagnostic tool."""

    BACKEND_CANDIDATES = (
        (
            ("DirectShow", cv2.CAP_DSHOW),
            ("Media Foundation", cv2.CAP_MSMF),
            ("OpenCV default", None),
        )
        if sys.platform.startswith("win")
        else (("OpenCV default", None),)
    )

    def __init__(self, camera_index):
        self.capture = None
        for label, backend in self.BACKEND_CANDIDATES:
            print(f"Trying OpenCV camera {camera_index} with {label}...")
            candidate = (
                cv2.VideoCapture(camera_index)
                if backend is None
                else cv2.VideoCapture(camera_index, backend)
            )
            if not candidate.isOpened():
                candidate.release()
                continue

            # Set FOURCC before dimensions/FPS, as in opencv_camera_controls.py.
            candidate.set(
                cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")
            )
            candidate.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            candidate.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
            candidate.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.capture = candidate
            actual_width = int(candidate.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(candidate.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = candidate.get(cv2.CAP_PROP_FPS)
            print(
                f"OpenCV camera opened with {label}: "
                f"{actual_width}x{actual_height} at {actual_fps:g} FPS"
            )
            break

        if self.capture is None:
            raise RuntimeError(f"Cannot open OpenCV camera index {camera_index}")

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


class YoloCamera:
    """Continuously captures frames and keeps only the newest YOLO result."""

    def __init__(self, camera_source, camera_index, tiscamera_serial):
        print(f"Loading YOLO model: {MODEL_PATH}")
        self.model = YOLO(MODEL_PATH)
        self.source = CameraManager(
            camera_source,
            camera_index,
            tiscamera_serial,
            CAMERA_WIDTH,
            CAMERA_HEIGHT,
            CAMERA_FPS,
        )

        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            ok, frame = self.source.read()
            if not ok:
                print("Camera read failed; retrying...")
                time.sleep(0.1)
                continue

            results = self.model.predict(
                source=frame,
                conf=YOLO_CONF,
                verbose=False,
            )
            annotated_frame = results[0].plot()
            if annotated_frame.shape[:2] != (CAMERA_HEIGHT, CAMERA_WIDTH):
                annotated_frame = cv2.resize(
                    annotated_frame,
                    (CAMERA_WIDTH, CAMERA_HEIGHT),
                    interpolation=cv2.INTER_LINEAR,
                )
            frame_capture.submit(annotated_frame)

            with self.lock:
                self.frame = annotated_frame

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def close(self):
        self.running = False
        self.thread.join(timeout=2.0)
        self.source.close()


class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, camera):
        super().__init__()
        self.camera = camera
        self.started_at = time.monotonic()
        self.frame_index = 0
        self.fps_overlay = FpsOverlay()

    async def recv(self):
        # WebRTC video uses a 90 kHz clock.
        self.frame_index += 1
        pts = self.frame_index * (90000 // CAMERA_FPS)
        target_time = self.started_at + self.frame_index / CAMERA_FPS
        delay = target_time - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

        frame = self.camera.get_frame()
        while frame is None:
            await asyncio.sleep(0.01)
            frame = self.camera.get_frame()

        self.fps_overlay.draw(frame)
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = fractions.Fraction(1, 90000)
        return video_frame


pcs = set()
camera = None
args = None


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(
        sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"WebRTC connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            pcs.discard(pc)

    await pc.setRemoteDescription(remote_offer)
    pc.addTrack(CameraVideoTrack(camera))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


async def camera_status(_request):
    try:
        return web.json_response(await asyncio.to_thread(camera.source.status))
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def camera_control(request):
    params = await request.json()
    try:
        result = await asyncio.to_thread(
            camera.source.apply, params.get("name"), params.get("value")
        )
        return web.json_response(result)
    except (CameraControlError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def capture_frames(_request):
    try:
        status = await asyncio.to_thread(camera.source.status)
        exposure = status.get("controls", {}).get("exposure", {})
        accepted, result = frame_capture.request({
            "exposure": exposure.get("value", "unknown"),
            "resolution": status.get("resolution", "unknown"),
            "fps": status.get("fps", "unknown"),
        })
        return web.json_response(result, status=202 if accepted else 429)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def on_startup(_app):
    global camera
    camera = YoloCamera(
        args.camera_source,
        args.camera_index,
        args.tiscamera_serial,
    )


async def on_shutdown(_app):
    await asyncio.gather(*(pc.close() for pc in pcs), return_exceptions=True)
    pcs.clear()
    if camera is not None:
        camera.close()
    frame_capture.close()


app = web.Application()
app.router.add_get("/", index)
app.router.add_post("/offer", offer)
app.router.add_get("/api/camera", camera_status)
app.router.add_post("/api/camera/control", camera_control)
app.router.add_post("/api/capture", capture_frames)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stream 1920x1080 30 FPS camera video with YOLO over WebRTC"
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
    print(f"Open http://<device-ip>:{HTTP_PORT} in a browser")
    web.run_app(app, host=HTTP_HOST, port=HTTP_PORT)
