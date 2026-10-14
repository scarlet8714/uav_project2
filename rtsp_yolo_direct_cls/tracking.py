"""Time-based extension of the legacy tracker, independent of class labels."""

import math
import time


class TargetTracker:
    def __init__(self, confirm_frames=2, match_distance_px=60, hold_seconds=0.5):
        self.confirm_frames = confirm_frames
        self.match_distance_px = match_distance_px
        self.hold_seconds = hold_seconds
        self.candidates = {}
        self.next_id = 0
        self.generation = None
        self.last_pts = None
        self.epoch = 0

    def reset(self):
        self.candidates.clear()
        self.last_pts = None
        self.epoch += 1

    @staticmethod
    def _state(box):
        return [(box["x1"] + box["x2"]) / 2,
                (box["y1"] + box["y2"]) / 2,
                max(1.0, box["x2"] - box["x1"]),
                max(1.0, box["y2"] - box["y1"])]

    def _predict(self, candidate, pts, image_size=None):
        dt = max(0.0, pts - candidate["last_pts"])
        x, y, width, height = [s + v * dt for s, v in
                              zip(candidate["state"], candidate["velocity"])]
        # Limit size extrapolation while retaining positional motion.
        width = max(candidate["state"][2] * 0.5,
                    min(width, candidate["state"][2] * 2))
        height = max(candidate["state"][3] * 0.5,
                     min(height, candidate["state"][3] * 2))
        box = dict(candidate["box"])
        box.update(x1=x-width/2, y1=y-height/2, x2=x+width/2, y2=y+height/2)
        if image_size is not None:
            image_width, image_height = image_size
            for key in ("x1", "x2"):
                box[key] = min(image_width, max(0.0, box[key]))
            for key in ("y1", "y2"):
                box[key] = min(image_height, max(0.0, box[key]))
        box.update(center_x=(box["x1"]+box["x2"])/2,
                   center_y=(box["y1"]+box["y2"])/2)
        return box

    @staticmethod
    def _iou(a, b):
        intersection = (max(0.0, min(a["x2"], b["x2"])-max(a["x1"], b["x1"])) *
                        max(0.0, min(a["y2"], b["y2"])-max(a["y1"], b["y1"])))
        area_a = max(0.0, a["x2"]-a["x1"]) * max(0.0, a["y2"]-a["y1"])
        area_b = max(0.0, b["x2"]-b["x1"]) * max(0.0, b["y2"]-b["y1"])
        return intersection / max(1.0, area_a+area_b-intersection)

    def update(self, detections, generation=0, pts_seconds=None, image_size=None,
               trust_ids=False):
        pts = time.monotonic() if pts_seconds is None else pts_seconds
        if not math.isfinite(pts):
            raise ValueError("Tracking PTS must be finite")
        if (generation != self.generation or
                (self.last_pts is not None and
                 (pts <= self.last_pts or pts-self.last_pts > 1.0))):
            self.reset()
        self.generation, self.last_pts = generation, pts
        self.candidates = {key: c for key, c in self.candidates.items()
                           if pts-c["last_pts"] <= self.hold_seconds}
        predictions = {key: self._predict(c, pts, image_size)
                       for key, c in self.candidates.items()}
        pairs = []
        for index, box in enumerate(detections):
            state = self._state(box)
            for key, prediction in predictions.items():
                if trust_ids:
                    if key == box["track_id"]:
                        pairs.append((0.0, index, key))
                    continue
                predicted = self._state(prediction)
                distance = math.hypot(state[0]-predicted[0], state[1]-predicted[1])
                ratio = max(state[2]/predicted[2], predicted[2]/state[2],
                            state[3]/predicted[3], predicted[3]/state[3])
                gate = max(self.match_distance_px,
                           0.35 * max(math.hypot(*state[2:]), math.hypot(*predicted[2:])))
                overlap = self._iou(box, prediction)
                if ratio <= 3 and (distance <= gate or overlap >= 0.1):
                    pairs.append((distance/gate + 0.75*(1-overlap) +
                                  0.15*math.log(ratio), index, key))
        matches, used = {}, set()
        for _, index, key in sorted(pairs):
            if index not in matches and key not in used:
                matches[index] = key
                used.add(key)
        output = []
        for index, detection in enumerate(detections):
            box = dict(detection)
            state = self._state(box)
            key = matches.get(index)
            if key is None:
                key = int(box["track_id"]) if trust_ids else self.next_id
                self.next_id = max(self.next_id, key+1)
                candidate = {"state": state, "velocity": [0.0]*4,
                             "count": 0, "last_pts": pts, "box": box}
                self.candidates[key] = candidate
            else:
                candidate = self.candidates[key]
                dt = pts-candidate["last_pts"]
                velocity = [(s-old)/dt for s, old in zip(state, candidate["state"])]
                weight = 1.0 if candidate["count"] == 1 else 0.5
                candidate["velocity"] = [weight*v+(1-weight)*old for v, old in
                                         zip(velocity, candidate["velocity"])]
            candidate["count"] += 1
            count = box.get("confirm_count", candidate["count"]) if trust_ids else candidate["count"]
            box.update(track_id=key, confirm_count=count,
                       confirmed=box.get("confirmed", count >= self.confirm_frames)
                       if trust_ids else count >= self.confirm_frames,
                       observed=True, lastObservedPts=pts,
                       expiresPts=pts+self.hold_seconds, missingSeconds=0.0,
                       center_x=state[0], center_y=state[1])
            candidate.update(state=state, last_pts=pts, box=dict(box))
            used.add(key)
            output.append(box)
        # Missing targets remain candidates for ID recovery, but produce no display box.
        return output

    def remember(self, boxes):
        """Keep the latest observed target information in the retained track."""
        for box in boxes:
            if box.get("observed") and box["track_id"] in self.candidates:
                self.candidates[box["track_id"]]["box"] = dict(box)
