"""Exercise the installed ByteTrack backend without a camera or GPU inference."""

from types import SimpleNamespace
import unittest

import numpy as np
from ultralytics.engine.results import Boxes

from .byte_tracking import ByteTargetTracker


def result(present=True, label=0, confidence=0.9):
    data = np.array([[20, 20, 60, 60, confidence, label]] if present else [],
                    dtype=np.float32).reshape(-1, 6)
    return SimpleNamespace(boxes=Boxes(data, (200, 200)),
                           names={0: "military_car", 1: "car"})


class ByteTrackingTests(unittest.TestCase):
    def test_confirmed_target_is_hidden_and_recovers_original_id(self):
        tracker = ByteTargetTracker()
        first = tracker.update(result(), 1, 0)[0]
        confirmed = tracker.update(result(), 1, 0.1)[0]
        self.assertTrue(confirmed["confirmed"])
        self.assertEqual(tracker.update(result(False), 1, 0.2), [])
        self.assertIn(first["track_id"], tracker.candidates)
        recovered = tracker.update(result(), 1, 0.3)[0]
        self.assertEqual(recovered["track_id"], first["track_id"])

    def test_many_missing_updates_do_not_expire_before_time_limit(self):
        tracker = ByteTargetTracker(buffer=1)
        tracker.update(result(), 1, 0)
        tracker.update(result(), 1, 0.02)
        for i in range(2, 20):
            self.assertEqual(tracker.update(result(False), 1, i*0.02), [])
            self.assertEqual(len(tracker.candidates), 1)
        recovered = tracker.update(result(), 1, 0.4)[0]
        self.assertEqual(recovered["confirm_count"], 3)

    def test_source_time_expiry_and_reconnect_drop_old_state(self):
        tracker = ByteTargetTracker()
        tracker.update(result(), 1, 0)
        tracker.update(result(), 1, 0.1)
        self.assertEqual(tracker.update(result(False), 1, 0.61), [])
        self.assertEqual(tracker.last_matched_pts, {})
        epoch = tracker.epoch
        self.assertEqual(tracker.update(result(False), 2, 0), [])
        self.assertGreater(tracker.epoch, epoch)

    def test_weak_match_preserves_id_without_confirming_new_target(self):
        tracker = ByteTargetTracker()
        first = tracker.update(result(), 1, 0)[0]
        weak = tracker.update(result(confidence=0.2), 1, 0.1)[0]
        self.assertEqual(weak["track_id"], first["track_id"])
        self.assertEqual(weak["confirm_count"], 1)
        self.assertFalse(weak["confirmed"])


if __name__ == "__main__":
    unittest.main()
