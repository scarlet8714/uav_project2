"""Non-blocking five-frame capture shared by the minimal stream demos."""

from pathlib import Path
import queue
import sys
import threading
import time

import cv2


class FrameCapture:
    """Collect annotated BGR frames and write them outside the stream thread."""

    def __init__(self, frame_count=5, cooldown=10.0, jpeg_quality=95):
        self.frame_count = frame_count
        self.cooldown = cooldown
        self.jpeg_quality = jpeg_quality
        self.output_dir = Path.cwd() / Path(sys.argv[0]).stem
        self.lock = threading.Lock()
        self.pending = 0
        self.last_request = float("-inf")
        self.session = None
        self.jobs = queue.Queue(maxsize=frame_count)
        self.running = True
        self.worker = threading.Thread(target=self._write_frames, daemon=True)
        self.worker.start()

    @staticmethod
    def _safe(value):
        return "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in str(value)
        )

    def request(self, metadata):
        now = time.monotonic()
        with self.lock:
            remaining = self.cooldown - (now - self.last_request)
            if remaining > 0:
                return False, {
                    "error": "擷取冷卻中",
                    "retry_after": round(remaining, 1),
                }
            if self.pending:
                return False, {"error": "上一批圖片仍在擷取中"}

            self.last_request = now
            self.pending = self.frame_count
            self.session = {
                "timestamp": time.strftime("%Y%m%d_%H%M%S"),
                "exposure": self._safe(metadata.get("exposure", "unknown")),
                "resolution": self._safe(
                    metadata.get("resolution", "unknown")
                ),
                "fps": self._safe(metadata.get("fps", "unknown")),
                "index": 0,
            }

        return True, {
            "message": f"已開始擷取 {self.frame_count} 張圖片",
            "count": self.frame_count,
            "cooldown": self.cooldown,
            "directory": str(self.output_dir),
        }

    def submit(self, frame):
        """Queue one post-YOLO, pre-encoding frame without blocking."""
        with self.lock:
            if self.pending <= 0:
                return
            self.pending -= 1
            self.session["index"] += 1
            session = self.session.copy()

        try:
            self.jobs.put_nowait((frame.copy(), session))
        except queue.Full:
            # This should be rare with a queue sized for one complete batch.
            # Restore the counter so a later frame can replace the dropped one.
            with self.lock:
                self.pending += 1
                self.session["index"] -= 1

    def _write_frames(self):
        while self.running or not self.jobs.empty():
            try:
                frame, info = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                filename = (
                    f"{info['timestamp']}_{info['index']:02d}_"
                    f"exp-{info['exposure']}us_"
                    f"{info['resolution']}_{info['fps']}fps.jpg"
                )
                path = self.output_dir / filename
                success = cv2.imwrite(
                    str(path),
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
                )
                if success:
                    print(f"Captured image: {path}")
                else:
                    print(f"Failed to save captured image: {path}")
            except Exception as exc:
                print(f"Failed to save captured image: {exc}")
            finally:
                self.jobs.task_done()

    def close(self):
        self.running = False
        self.worker.join(timeout=3.0)
