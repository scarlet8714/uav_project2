"""Optional ByteTrack adapter; imported only when explicitly selected."""

from types import SimpleNamespace
import math

from ultralytics.trackers.byte_tracker import BYTETracker
from .tracking import TargetTracker


class ByteTargetTracker:
    def __init__(self, buffer=5, hold_seconds=0.5):
        self.backend = BYTETracker(SimpleNamespace(
            track_high_thresh=0.3, track_low_thresh=0.1,
            new_track_thresh=0.3, track_buffer=buffer,
            match_thresh=0.8, fuse_score=True))
        self.confirmations = {}
        self.generation = None
        self.last_pts = None
        self.buffer = buffer
        self.hold_seconds = hold_seconds
        self.minimum_step = None
        self.last_matched_pts = {}
        self.retention = TargetTracker(hold_seconds=hold_seconds)

    @property
    def candidates(self):
        return self.retention.candidates

    @property
    def epoch(self):
        return self.retention.epoch

    def remember(self, boxes):
        self.retention.remember(boxes)

    def update(self, result, generation, pts_seconds, image_size=None):
        # Do not reuse identities across reconnects or a long source-time gap.
        if (generation != self.generation or
                (self.last_pts is not None and
                 (pts_seconds <= self.last_pts or pts_seconds - self.last_pts > 1.0))):
            self.backend.reset()
            self.confirmations.clear()
            self.minimum_step = None
            self.last_matched_pts.clear()
        elif self.last_pts is not None:
            step_seconds = pts_seconds-self.last_pts
            self.minimum_step = (step_seconds if self.minimum_step is None else
                                 min(self.minimum_step, step_seconds))
        # Keep backend IDs long enough; the outer tracker enforces source-time expiry.
        if self.minimum_step is not None:
            self.backend.max_frames_lost = max(
                self.buffer, math.ceil(self.hold_seconds/max(self.minimum_step, 0.001))+1)
        self.generation = generation
        self.last_pts = pts_seconds
        expired = {key for key, last in self.last_matched_pts.items()
                   if pts_seconds-last > self.hold_seconds}
        # The backend counts updates; discard identities whose source-time lease expired.
        if expired:
            for track in self.backend.tracked_stracks + self.backend.lost_stracks:
                if track.track_id in expired:
                    track.mark_removed()
            self.backend.tracked_stracks = [track for track in self.backend.tracked_stracks
                                           if track.track_id not in expired]
            self.backend.lost_stracks = [track for track in self.backend.lost_stracks
                                        if track.track_id not in expired]
            for key in expired:
                self.last_matched_pts.pop(key, None)
                self.confirmations.pop(key, None)
        detections = result.boxes.cpu().numpy()
        tracks = self.backend.update(detections)
        output = []
        step = self.backend.frame_id
        for track in tracks:
            # ByteTrack supplies the original detection index as the last column.
            detection = detections[int(track[-1])]
            x1, y1, x2, y2 = detection.xyxy[0].tolist()
            confidence = float(detection.conf[0])
            track_id = int(track[4])
            self.last_matched_pts[track_id] = pts_seconds
            count, _ = self.confirmations.get(track_id, (0, step))
            # Weak matches can sustain an ID, but cannot confirm a new target.
            count += int(confidence >= 0.3)
            self.confirmations[track_id] = (count, step)
            output.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "center_x": (x1 + x2) / 2, "center_y": (y1 + y2) / 2,
                "label": str(result.names[int(detection.cls[0])]),
                "confidence": confidence, "track_id": track_id,
                "confirm_count": count, "confirmed": count >= 2})
        self.confirmations = {
            key: value for key, value in self.confirmations.items()
            if step - value[1] <= self.backend.max_frames_lost + 1}
        return self.retention.update(output, generation, pts_seconds, image_size, trust_ids=True)
