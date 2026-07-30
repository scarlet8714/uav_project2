"""YOLO + GPS target geolocation streamed to browsers over WebRTC.

Camera examples:
    python yolo_final.py --camera-backend opencv
    python yolo_final.py --camera-backend gstreamer --jpeg-decoder jpegdec
    python yolo_final.py --camera-backend gstreamer --jpeg-decoder nvjpegdec

WebRTC dependencies are aiohttp, aiortc and av.  GStreamer mode additionally
requires PyGObject and the selected GStreamer JPEG decoder plugin.
"""

import argparse
import asyncio
import fractions
import math
import threading
import time

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from ultralytics import YOLO

from gps_geolocation import GPSReader, estimate_target_gps_from_reader
from minimal_camera_control import CameraControlError, CameraManager
from minimal_control_ui import build_page
from minimal_frame_capture import FrameCapture


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# "opencv" or "gstreamer". CLI options can override these settings.
CAMERA_BACKEND = "gstreamer"
CAMERA_INDEX = 0
GSTREAMER_DEVICE = "/dev/video0"
TISCAMERA_SERIAL = ""

CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 30
CAMERA_READ_TIMEOUT_SEC = 2.0

# "jpegdec" for software decoding or "nvjpegdec" for NVIDIA decoding.
GSTREAMER_JPEG_DECODER = "jpegdec"
GSTREAMER_DROP_OLD_FRAMES = True

MODEL_PATH = "11s_car_544_960.engine"
YOLO_IMGSZ = (544, 960)
YOLO_CONF = 0.4
YOLO_IOU = 0.45

GPS_PORT = "/dev/ttyUSB0"
GPS_BAUDRATE = 9600
ALTITUDE_AGL_M = 75.0
HFOV_DEG = 52.0
VFOV_DEG = 31.0
CAMERA_YAW_OFFSET_DEG = 180.0
PRINT_TARGET_GPS = True

# Rotate before YOLO so bbox coordinates and GPS projection use the same image.
ROTATE_180 = False

ENABLE_TEMPORAL_CONFIRMATION = True
CONFIRM_FRAMES = 3
MATCH_DISTANCE_PX = 60.0
MAX_MISSING_FRAMES = 5

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WEBRTC_CLOCK_RATE = 90_000


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>YOLO GPS WebRTC stream</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; text-align: center; }
    video { width: min(100%, 1280px); margin-top: 16px; background: #000; }
    #status { margin: 12px; }
  </style>
</head>
<body>
  <h2>YOLO GPS WebRTC stream</h2>
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
      await peer.setRemoteDescription(await response.json());
    }

    start().catch(error => {
      console.error(error);
      statusElement.textContent = "Error: " + error.message;
    });
  </script>
</body>
</html>
"""

FINAL_WEBRTC_SCRIPT = """
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
window.addEventListener("pagehide", () => peer.close());
startWebRTC().catch(error => {
  statusElement.textContent = "WebRTC error: " + error.message;
});
"""

HTML = build_page(
    "YOLO GPS WebRTC stream",
    '<video id="video" autoplay playsinline muted></video>',
    FINAL_WEBRTC_SCRIPT,
    source_options=(
        ("v4l2", "OpenCV / V4L2"),
        ("gstreamer", "GStreamer / v4l2src"),
        ("tiscamera", "GStreamer / tcambin"),
    ),
)


# ---------------------------------------------------------------------------
# Camera sources
# ---------------------------------------------------------------------------

class OpenCVCamera:
    """cv2.VideoCapture source with a small input buffer."""

    def __init__(self, camera_index):
        self.capture = cv2.VideoCapture(camera_index)
        self.capture.set(
            cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")
        )
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.capture.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open OpenCV camera index {camera_index}")

        print(
            "[Camera] OpenCV: "
            f"{int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))} at "
            f"{self.capture.get(cv2.CAP_PROP_FPS):g} FPS"
        )

    def read(self):
        return self.capture.read()

    def close(self):
        self.capture.release()


class GStreamerCamera:
    """GStreamer GI source; does not require OpenCV GStreamer support."""

    def __init__(self, device, jpeg_decoder):
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError) as exc:
            raise RuntimeError(
                "GStreamer mode requires PyGObject and GStreamer 1.0"
            ) from exc

        self.Gst = Gst
        Gst.init(None)
        drop = "true" if GSTREAMER_DROP_OLD_FRAMES else "false"
        self.pipeline_text = (
            f"v4l2src device={device} ! "
            f"image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},"
            f"framerate={CAMERA_FPS}/1 ! "
            f"{jpeg_decoder} ! videoconvert ! video/x-raw,format=BGR ! "
            f"appsink name=appsink emit-signals=false sync=false async=false "
            f"drop={drop} max-buffers=1"
        )
        print(f"[Camera] GStreamer pipeline:\n{self.pipeline_text}")

        try:
            self.pipeline = Gst.parse_launch(self.pipeline_text)
        except Exception as exc:
            raise RuntimeError(f"Cannot create GStreamer pipeline: {exc}") from exc

        self.appsink = self.pipeline.get_by_name("appsink")
        if self.appsink is None:
            raise RuntimeError("GStreamer pipeline has no appsink")

        state = self.pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("GStreamer pipeline cannot enter PLAYING state")

        self.bus = self.pipeline.get_bus()
        self.closed = False

    def _bus_error(self):
        message = self.bus.pop_filtered(
            self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS
        )
        if message is None:
            return None
        if message.type == self.Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            return f"GStreamer ERROR: {error}; debug={debug}"
        return "GStreamer EOS"

    def read(self):
        if self.closed:
            return False, None

        error = self._bus_error()
        if error:
            print(f"[Camera] {error}")
            return False, None

        sample = self.appsink.emit(
            "try-pull-sample",
            int(CAMERA_READ_TIMEOUT_SEC * self.Gst.SECOND),
        )
        if sample is None:
            print(f"[Camera] {self._bus_error() or 'GStreamer frame timeout'}")
            return False, None

        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")
        buffer = sample.get_buffer()
        ok, map_info = buffer.map(self.Gst.MapFlags.READ)
        if not ok:
            print("[Camera] Cannot map Gst.Buffer")
            return False, None
        try:
            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape(
                (height, width, 3)
            ).copy()
        except Exception as exc:
            print(f"[Camera] Cannot convert frame: {exc}")
            return False, None
        finally:
            buffer.unmap(map_info)
        return True, frame

    def close(self):
        if not self.closed:
            self.closed = True
            self.pipeline.set_state(self.Gst.State.NULL)


class LatestFrameCamera:
    """Continuously drains the camera and exposes only each newest frame."""

    def __init__(self, source):
        self.source = source
        self.condition = threading.Condition()
        self.frame = None
        self.frame_id = 0
        self.delivered_id = 0
        self.running = True
        self.thread = threading.Thread(
            target=self._capture, name="CameraCaptureThread", daemon=True
        )
        self.thread.start()

    def _capture(self):
        while self.running:
            ok, frame = self.source.read()
            if not ok:
                if not self.running:
                    break
                time.sleep(0.02)
                continue
            with self.condition:
                self.frame = frame
                self.frame_id += 1
                self.condition.notify_all()

    def read(self):
        deadline = time.monotonic() + CAMERA_READ_TIMEOUT_SEC
        with self.condition:
            while self.running and self.frame_id <= self.delivered_id:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, None
                self.condition.wait(remaining)
            if self.frame is None:
                return False, None
            self.delivered_id = self.frame_id
            return True, self.frame.copy()

    def close(self):
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self.source.close()
        self.thread.join(timeout=2.0)


def create_camera(settings):
    manager = CameraManager(
        settings.camera_backend,
        settings.camera_index,
        settings.tiscamera_serial,
        CAMERA_WIDTH,
        CAMERA_HEIGHT,
        CAMERA_FPS,
        gstreamer_device=settings.gstreamer_device,
    )
    return manager, LatestFrameCamera(manager)


# ---------------------------------------------------------------------------
# YOLO, temporal confirmation and GPS annotation
# ---------------------------------------------------------------------------

class TargetTracker:
    def __init__(self):
        self.candidates = []
        self.next_id = 0

    def update(self, detections):
        if not ENABLE_TEMPORAL_CONFIRMATION:
            return [
                (detection, {"id": -1, "count": CONFIRM_FRAMES,
                             "confirmed": True})
                for detection in detections
            ]

        for candidate in self.candidates:
            candidate["missing"] += 1

        used_ids = set()
        matches = []
        for detection in detections:
            cx, cy = detection["center_x"], detection["center_y"]
            available = [
                candidate for candidate in self.candidates
                if candidate["id"] not in used_ids
            ]
            nearby = [
                (math.hypot(cx - candidate["center_x"],
                            cy - candidate["center_y"]), candidate)
                for candidate in available
            ]
            nearby = [item for item in nearby if item[0] <= MATCH_DISTANCE_PX]

            if nearby:
                _, candidate = min(nearby, key=lambda item: item[0])
                candidate.update(center_x=cx, center_y=cy, missing=0)
                candidate["count"] += 1
                candidate["confirmed"] = candidate["count"] >= CONFIRM_FRAMES
            else:
                candidate = {
                    "id": self.next_id,
                    "center_x": cx,
                    "center_y": cy,
                    "count": 1,
                    "missing": 0,
                    "confirmed": CONFIRM_FRAMES <= 1,
                }
                self.next_id += 1
                self.candidates.append(candidate)

            used_ids.add(candidate["id"])
            matches.append((detection, candidate))

        self.candidates = [
            candidate for candidate in self.candidates
            if candidate["missing"] <= MAX_MISSING_FRAMES
        ]
        return matches


class FpsOverlay:
    """Measure smoothed processed-frame FPS and draw it on a BGR frame."""

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


class YoloGpsProcessor:
    """Runs one inference pipeline and stores only its latest result."""

    def __init__(self, settings):
        print(f"[YOLO] Loading model: {settings.model_path}")
        self.model = YOLO(settings.model_path, task="detect")
        self.camera_manager, self.camera = create_camera(settings)
        self.gps = GPSReader(port=GPS_PORT, baudrate=GPS_BAUDRATE)
        self.tracker = TargetTracker()
        self.frame_capture = FrameCapture()
        self.fps_overlay = FpsOverlay()
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.gps.start()
        self.thread = threading.Thread(
            target=self._run, name="YoloGpsThread", daemon=True
        )
        self.thread.start()

    @staticmethod
    def _label(image, text, x, y, color):
        height, width = image.shape[:2]
        x = max(0, min(int(x), width - 1))
        y = max(15, min(int(y), height - 10))
        cv2.putText(
            image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
            0.45, color, 1, cv2.LINE_AA
        )

    def _process(self, frame):
        if ROTATE_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        image_height, image_width = frame.shape[:2]

        result = self.model.predict(
            source=frame,
            imgsz=YOLO_IMGSZ,
            conf=YOLO_CONF,
            iou=YOLO_IOU,
            verbose=False,
        )[0]
        annotated = result.plot()

        detections = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "center_x": (x1 + x2) / 2.0,
                "center_y": (y1 + y2) / 2.0,
            })

        for index, (detection, candidate) in enumerate(
            self.tracker.update(detections)
        ):
            target_x = detection["center_x"]
            target_y = detection["center_y"]
            text_x = detection["x1"]
            text_y = detection["y2"] + 20
            cv2.circle(
                annotated, (int(target_x), int(target_y)), 5, (0, 0, 255), -1
            )

            if not candidate["confirmed"]:
                self._label(
                    annotated,
                    f"confirm {candidate['count']}/{CONFIRM_FRAMES}",
                    text_x, text_y, (0, 255, 255),
                )
                continue

            target_gps = estimate_target_gps_from_reader(
                gps_reader=self.gps,
                target_x=target_x,
                target_y=target_y,
                image_width=image_width,
                image_height=image_height,
                altitude_agl_m=ALTITUDE_AGL_M,
                hfov_deg=HFOV_DEG,
                vfov_deg=VFOV_DEG,
                camera_yaw_offset_deg=CAMERA_YAW_OFFSET_DEG,
            )
            if target_gps is None:
                self._label(
                    annotated, "GPS unavailable", text_x, text_y, (0, 0, 255)
                )
                continue

            target_lat = target_gps["target_lat"]
            target_lon = target_gps["target_lon"]
            self._label(
                annotated,
                f"{target_lat:.7f}, {target_lon:.7f}",
                text_x, text_y, (0, 255, 0),
            )
            if PRINT_TARGET_GPS:
                print(
                    f"[Target {index}] candidate_id={candidate['id']} "
                    f"count={candidate['count']} "
                    f"pixel=({target_x:.1f}, {target_y:.1f}) "
                    f"GPS=({target_lat:.7f}, {target_lon:.7f})"
                )
        return annotated

    def _run(self):
        while self.running:
            ok, frame = self.camera.read()
            if not ok:
                if self.running:
                    print("[Camera] Waiting for a new frame...")
                continue
            try:
                annotated = self._process(frame)
            except Exception as exc:
                print(f"[YOLO] Frame processing failed: {exc}")
                continue
            self.fps_overlay.draw(annotated)
            self.frame_capture.submit(annotated)
            with self.lock:
                self.frame = annotated

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def request_capture(self):
        status = self.camera_manager.status()
        exposure = status.get("controls", {}).get("exposure", {})
        return self.frame_capture.request({
            "exposure": exposure.get("value", "unknown"),
            "resolution": status.get("resolution", "unknown"),
            "fps": status.get("fps", "unknown"),
        })

    def close(self):
        self.running = False
        self.camera.close()
        self.thread.join()
        self.gps.stop()
        self.frame_capture.close()


# ---------------------------------------------------------------------------
# WebRTC server
# ---------------------------------------------------------------------------

class CameraVideoTrack(VideoStreamTrack):
    def __init__(self, processor):
        super().__init__()
        self.processor = processor
        self.started_at = time.monotonic()
        self.frame_index = 0

    async def recv(self):
        self.frame_index += 1
        pts_step = WEBRTC_CLOCK_RATE // CAMERA_FPS
        target_time = self.started_at + self.frame_index / CAMERA_FPS
        delay = target_time - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

        frame = self.processor.get_frame()
        while frame is None:
            await asyncio.sleep(0.01)
            frame = self.processor.get_frame()

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self.frame_index * pts_step
        video_frame.time_base = fractions.Fraction(1, WEBRTC_CLOCK_RATE)
        return video_frame


pcs = set()
processor = None
settings = None


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def offer(request):
    params = await request.json()
    remote_offer = RTCSessionDescription(
        sdp=params["sdp"], type=params["type"]
    )
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"[WebRTC] Connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            pcs.discard(pc)

    await pc.setRemoteDescription(remote_offer)
    pc.addTrack(CameraVideoTrack(processor))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    })


async def camera_status(_request):
    try:
        result = await asyncio.to_thread(processor.camera_manager.status)
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def camera_control(request):
    params = await request.json()
    try:
        result = await asyncio.to_thread(
            processor.camera_manager.apply,
            params.get("name"),
            params.get("value"),
        )
        return web.json_response(result)
    except (CameraControlError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def capture_frames(_request):
    try:
        accepted, result = await asyncio.to_thread(processor.request_capture)
        return web.json_response(result, status=202 if accepted else 429)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def on_startup(_app):
    global processor
    processor = YoloGpsProcessor(settings)


async def on_shutdown(_app):
    await asyncio.gather(*(pc.close() for pc in pcs), return_exceptions=True)
    pcs.clear()
    if processor is not None:
        processor.close()


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
        description="YOLO GPS video streaming over WebRTC"
    )
    parser.add_argument(
        "--camera-backend",
        choices=("opencv", "gstreamer", "tiscamera"),
        default=CAMERA_BACKEND,
    )
    parser.add_argument("--camera-index", type=int, default=CAMERA_INDEX)
    parser.add_argument(
        "--gstreamer-device", default=GSTREAMER_DEVICE,
    )
    parser.add_argument(
        "--jpeg-decoder", choices=("jpegdec", "nvjpegdec"),
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


if __name__ == "__main__":
    settings = parse_args()
    print(
        f"Camera backend={settings.camera_backend}, "
        f"format={CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}, "
        f"decoder={settings.jpeg_decoder}"
    )
    print(f"Open http://<device-ip>:{HTTP_PORT} in a browser")
    web.run_app(app, host=HTTP_HOST, port=HTTP_PORT)
