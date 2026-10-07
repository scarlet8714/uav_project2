"""YOLO, temporal confirmation, and GPS projection."""

import math
import queue
import threading
import time

from ultralytics import YOLO

from .gps import GPSReader, estimate_target_gps


class TargetTracker:
    def __init__(self, confirm_frames=2, match_distance_px=60, max_missing=5):
        self.confirm_frames = confirm_frames
        self.match_distance_px = match_distance_px
        self.max_missing = max_missing
        self.candidates = []
        self.next_id = 0

    def update(self, detections):
        for candidate in self.candidates:
            candidate["missing"] += 1
        used = set()
        output = []
        for detection in detections:
            x, y = detection["center_x"], detection["center_y"]
            nearby = [(math.hypot(x-c["center_x"], y-c["center_y"]), c)
                      for c in self.candidates if c["id"] not in used]
            nearby = [item for item in nearby if item[0] <= self.match_distance_px]
            if nearby:
                _, candidate = min(nearby, key=lambda item: item[0])
                candidate.update(center_x=x, center_y=y, missing=0)
                candidate["count"] += 1
            else:
                candidate = {"id": self.next_id, "center_x": x, "center_y": y,
                             "count": 1, "missing": 0}
                self.candidates.append(candidate)
                self.next_id += 1
            used.add(candidate["id"])
            detection["track_id"] = candidate["id"]
            detection["confirm_count"] = candidate["count"]
            detection["confirmed"] = candidate["count"] >= self.confirm_frames
            output.append(detection)
        self.candidates = [c for c in self.candidates
                           if c["missing"] <= self.max_missing]
        return output


class InferenceWorker:
    def __init__(self, config, loop, on_result, on_event):
        self.config = config
        self.loop = loop
        self.on_result = on_result
        self.on_event = on_event
        self.model = YOLO(config.model_path, task="detect")
        self.gps = GPSReader(port=config.gps_port, baudrate=config.gps_baudrate)
        if not config.no_gps:
            self.gps.start()
        if config.tracker == "bytetrack":
            from .byte_tracking import ByteTargetTracker
            self.tracker = ByteTargetTracker(buffer=config.bytetrack_buffer)
        else:
            self.tracker = TargetTracker()
        self.jobs = queue.Queue(maxsize=1)
        self.submit_generation = None
        self.source_frame_count = 0
        self.running = True
        self.processed_frames = 0
        self.dropped_frames = 0
        self.skipped_frames = 0
        self.last_inference_ms = None
        self.last_result_at = None
        self.fps = None
        self.last_error = None
        self.last_gps_status = "unavailable"
        self.last_gps_age_ms = None
        self.thread = threading.Thread(target=self._run, name="yolo-gps",
                                       daemon=True)
        self.thread.start()
        self.on_event("tracker_selected", tracker=config.tracker,
                      bytetrack_buffer=config.bytetrack_buffer)

    def submit(self, frame):
        if not self.running:
            return
        if frame.generation != self.submit_generation:
            self.submit_generation = frame.generation
            self.source_frame_count = 0
        self.source_frame_count += 1
        # Infer on frames 1, 3, 5... of each source generation.
        # The browser reuses the latest matching result on intervening frames.
        if self.source_frame_count % 2 == 0:
            self.skipped_frames += 1
            return
        try:
            self.jobs.put_nowait(frame)
        except queue.Full:
            try:
                self.jobs.get_nowait()
                self.dropped_frames += 1
            except queue.Empty:
                pass
            self.jobs.put_nowait(frame)

    def _gps_for_frame(self, frame):
        if self.config.no_gps:
            return None, "unavailable", None
        gps = self.gps.get_at_or_before(frame.receive_mono_ns / 1e9)
        if gps is None:
            return self.gps.get_latest(), "no_history", None
        if not gps.connected:
            return gps, "unavailable", None
        if gps.last_position_update is None:
            return gps, "invalid_fix" if gps.connected else "unavailable", None
        age = (frame.receive_mono_ns / 1e9 - gps.last_position_update) * 1000
        if age < 0:
            return gps, "future", round(age, 1)
        if not gps.fix_valid:
            return gps, "invalid_fix", round(age, 1)
        if age > 2000:
            return gps, "stale", round(age, 1)
        if gps.course_deg is None:
            return gps, "no_course", round(age, 1)
        return gps, "valid", round(age, 1)

    def _process(self, frame):
        started = time.monotonic()
        image = frame.image
        height, width = image.shape[:2]
        confidence_threshold = 0.1 if self.config.tracker == "bytetrack" else 0.3
        result = self.model.predict(image, imgsz=(544, 960), rect=False, conf=confidence_threshold,
                                    iou=0.45, verbose=False)[0]
        if self.config.tracker == "bytetrack":
            boxes = self.tracker.update(result, frame.generation, frame.pts90k / 90000)
        else:
            raw = []
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                raw.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                            "center_x": (x1+x2)/2, "center_y": (y1+y2)/2,
                            "label": str(result.names[int(box.cls[0])]),
                            "confidence": float(box.conf[0])})
            boxes = self.tracker.update(raw)
        gps, gps_status, gps_age_ms = self._gps_for_frame(frame)
        for box in boxes:
            if gps_status != "valid" or not box["confirmed"]:
                continue
            target = estimate_target_gps(
                target_x=box["center_x"], target_y=box["center_y"],
                image_width=width, image_height=height,
                altitude_agl_m=self.config.altitude_agl_m,
                drone_lat=gps.latitude, drone_lon=gps.longitude,
                course_deg=gps.course_deg,
                hfov_deg=self.config.hfov_deg,
                vfov_deg=self.config.vfov_deg,
                camera_yaw_offset_deg=self.config.camera_yaw_offset_deg)
            box["target_lat"] = target["target_lat"]
            box["target_lon"] = target["target_lon"]
        self.processed_frames += 1
        completed_at = time.monotonic()
        self.last_inference_ms = round((completed_at-started)*1000, 1)
        if self.last_result_at is not None and completed_at > self.last_result_at:
            current_fps = 1 / (completed_at - self.last_result_at)
            self.fps = (current_fps if self.fps is None
                        else self.fps * 0.8 + current_fps * 0.2)
        self.last_result_at = completed_at
        self.last_error = None
        self.last_gps_status = gps_status
        self.last_gps_age_ms = gps_age_ms
        return {"type": "detection", "generation": frame.generation,
                "pts90k": frame.pts90k, "ptsSeconds": frame.pts90k/90000,
                "frameReceiveMonoNs": frame.receive_mono_ns,
                "width": width, "height": height, "boxes": boxes,
                "gpsStatus": gps_status, "gpsAgeMs": gps_age_ms,
                "gps": self._gps_details(gps),
                "yoloFps": None if self.fps is None else round(self.fps, 1),
                "inferenceMs": round((time.monotonic()-started)*1000, 1)}

    def _run(self):
        while self.running:
            try:
                frame = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if frame is None:
                break
            try:
                result = self._process(frame)
                self.loop.call_soon_threadsafe(self.on_result, result)
            except Exception as exc:
                self.last_error = repr(exc)
                self.on_event("yolo_error", error=self.last_error)

    def status(self):
        age = None if self.last_result_at is None else time.monotonic()-self.last_result_at
        return {"processed_frames": self.processed_frames,
                "tracker": self.config.tracker,
                "model_path": self.config.model_path,
                "thread_alive": self.thread.is_alive(),
                "queue_size": self.jobs.qsize(),
                "dropped_frames": self.dropped_frames,
                "skipped_frames": self.skipped_frames,
                "inference_ms": self.last_inference_ms,
                "fps": None if self.fps is None else round(self.fps, 1),
                "last_frame_age_s": None if age is None else round(age, 3),
                "last_error": self.last_error, "gps_status": self.last_gps_status,
                "gps_age_ms": self.last_gps_age_ms,
                "gps": self._gps_details(None if self.config.no_gps else self.gps.get_latest())}

    def _gps_details(self, gps):
        if gps is None:
            return {"enabled": False}
        return {"enabled": True, "port": self.config.gps_port,
                "connected": gps.connected, "fixValid": gps.fix_valid,
                "latitude": gps.latitude, "longitude": gps.longitude,
                "courseDeg": gps.course_deg, "rmcStatus": gps.rmc_status,
                "nmeaAgeMs": None if gps.last_nmea_update is None else
                    round((time.monotonic() - gps.last_nmea_update) * 1000, 1),
                "error": gps.error}

    def close(self):
        self.running = False
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        self.thread.join(timeout=3)
        self.gps.stop()
