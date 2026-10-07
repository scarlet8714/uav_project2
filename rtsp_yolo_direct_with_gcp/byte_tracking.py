"""Optional ByteTrack adapter; imported only when explicitly selected."""

from types import SimpleNamespace

from ultralytics.trackers.byte_tracker import BYTETracker


class ByteTargetTracker:
    def __init__(self, buffer=5):
        self.backend = BYTETracker(SimpleNamespace(
            track_high_thresh=0.3, track_low_thresh=0.1,
            new_track_thresh=0.3, track_buffer=buffer,
            match_thresh=0.8, fuse_score=True))
        self.confirmations = {}
        self.generation = None
        self.last_pts = None

    def update(self, result, generation, pts_seconds):
        # Do not reuse identities across reconnects or a long source-time gap.
        if (generation != self.generation or
                (self.last_pts is not None and
                 (pts_seconds <= self.last_pts or pts_seconds - self.last_pts > 1.0))):
            self.backend.reset()
            self.confirmations.clear()
        self.generation = generation
        self.last_pts = pts_seconds
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
        # Only matched detections are returned, never a lost track's prediction.
        return output
