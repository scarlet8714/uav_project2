"""Behavioral tests with source timestamps and classifier scores; no GPU needed."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from .classification import (ClassificationManager, load_settings, preprocess,
                             probabilities)
from .config import parse_args
from .tracking import TargetTracker


SETTINGS_PATH = Path(__file__).with_name("classifier_config.json")
SETTINGS = load_settings(SETTINGS_PATH)


def detection(x=30, label="military_car", width=40):
    return dict(x1=x-width/2, y1=10, x2=x+width/2, y2=30,
                center_x=x, center_y=20, label=label, confidence=0.9)


class TrackingTests(unittest.TestCase):
    def test_missing_target_is_hidden_then_recovers_original_id_using_motion(self):
        tracker = TargetTracker()
        first = tracker.update([detection()], 1, 0)[0]
        second = tracker.update([detection(60)], 1, 0.1)[0]
        second["label"] = "cm34"
        second.update(target_lat=25, target_lon=121)
        tracker.remember([second])
        self.assertEqual(tracker.update([], 1, 0.3), [])
        retained = tracker.candidates[first["track_id"]]
        self.assertEqual(retained["count"], 2)
        self.assertEqual(retained["box"]["label"], "cm34")
        recovered = tracker.update([detection(150)], 1, 0.4)[0]
        self.assertEqual(recovered["track_id"], first["track_id"])
        self.assertTrue(recovered["observed"])

    def test_retention_is_seconds_regardless_of_number_of_updates(self):
        for steps in ((0.2, 0.4, 0.59), tuple(np.arange(0.11, 0.59, 0.01))):
            tracker = TargetTracker()
            tracker.update([detection()], 1, 0)
            tracker.update([detection()], 1, 0.1)
            for pts in steps:
                self.assertEqual(tracker.update([], 1, float(pts)), [])
                self.assertEqual(len(tracker.candidates), 1)
            self.assertEqual(tracker.update([], 1, 0.61), [])
            self.assertEqual(tracker.candidates, {})

    def test_single_detection_is_not_held(self):
        tracker = TargetTracker()
        tracker.update([detection()], 1, 0)
        self.assertEqual(tracker.update([], 1, 0.1), [])

    def test_class_changes_keep_id_and_missing_tracks_remain_hidden(self):
        tracker = TargetTracker()
        first = tracker.update([detection()], 1, 0)[0]
        second = tracker.update([detection(label="car")], 1, 0.1)[0]
        self.assertEqual(first["track_id"], second["track_id"])
        self.assertEqual(tracker.update([], 1, 0.2), [])
        self.assertEqual(tracker.candidates[first["track_id"]]["box"]["label"], "car")

    def test_reconnect_time_reversal_and_long_gap_clear_old_targets(self):
        for generation, pts in ((2, 0.2), (1, 0.1), (1, 1.2)):
            tracker = TargetTracker()
            tracker.update([detection()], 1, 0)
            tracker.update([detection()], 1, 0.1)
            epoch = tracker.epoch
            self.assertEqual(tracker.update([], generation, pts), [])
            self.assertGreater(tracker.epoch, epoch)

    def test_two_detections_cannot_take_the_same_track(self):
        tracker = TargetTracker()
        tracker.update([detection(30), detection(80)], 1, 0)
        result = tracker.update([detection(40), detection(70)], 1, 0.1)
        self.assertEqual(len({box["track_id"] for box in result}), 2)
        self.assertTrue(all(box["confirm_count"] == 2 for box in result))

    def test_size_change_after_a_gap_recovers_original_id(self):
        tracker = TargetTracker()
        first = tracker.update([detection(30, width=20)], 1, 0, (100, 50))[0]
        tracker.update([detection(50, width=40)], 1, 0.1, (100, 50))
        self.assertEqual(tracker.update([], 1, 0.2, (100, 50)), [])
        recovered = tracker.update([detection(70, width=60)], 1, 0.3, (100, 50))[0]
        self.assertEqual(recovered["track_id"], first["track_id"])

    def test_unmatched_old_track_does_not_add_a_second_box_at_same_position(self):
        tracker = TargetTracker()
        tracker.update([detection(), detection()], 1, 0)
        tracker.update([detection(), detection()], 1, 0.1)
        output = tracker.update([detection()], 1, 0.2)
        self.assertEqual(len(tracker.candidates), 2)
        self.assertEqual(len(output), 1)
        self.assertTrue(output[0]["observed"])

    def test_expired_target_cannot_steal_a_new_detection(self):
        tracker = TargetTracker()
        first = tracker.update([detection()], 1, 0)[0]
        result = tracker.update([detection()], 1, 0.8)[0]
        self.assertNotEqual(first["track_id"], result["track_id"])


class FakeRunner:
    def __init__(self, scores=(0.8, 0.1, 0.1)):
        self.scores = scores
        self.calls = []

    def predict(self, crop):
        self.calls.append(crop.copy())
        return self.scores


def ready_manager(history_size=5):
    manager = ClassificationManager("unused.engine", SETTINGS_PATH, history_size=history_size)
    manager.settings = SETTINGS
    manager.runner = FakeRunner()
    manager.state = "ready"
    return manager


def tracked_box(label="military_car", observed=True, key=0):
    return dict(detection(label=label), track_id=key, observed=observed)


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)

    def classify(self, manager, scores, key=0, active_ids=None):
        manager.runner.scores = scores
        box = tracked_box(key=key)
        manager.update([box], self.image, {key} if active_ids is None else active_ids)
        return box

    def test_only_real_military_boxes_are_classified(self):
        manager = ready_manager()
        boxes = [tracked_box(), tracked_box("car", key=1),
                 tracked_box("amphibious_armored_vehicle", key=2),
                 tracked_box("cm34", observed=False, key=3)]
        manager.update(boxes, self.image, {0, 1, 2, 3})
        self.assertEqual(len(manager.runner.calls), 1)
        self.assertEqual(boxes[0]["label"], "cm34")
        self.assertEqual(boxes[0]["detector_label"], "military_car")
        self.assertEqual(boxes[1]["label"], "car")
        self.assertEqual(boxes[3]["label"], "cm34")

    def test_low_scores_still_produce_a_class_without_unknown_label(self):
        manager = ready_manager()
        manager.runner.scores = (0.33, 0.34, 0.33)
        box = tracked_box()
        manager.update([box], self.image, {0})
        self.assertEqual(box["label"], "light_tactical")

    def test_new_evidence_changes_class_and_history_is_bounded(self):
        manager = ready_manager(history_size=5)
        for _ in range(5):
            box = tracked_box()
            manager.update([box], self.image, {0})
        manager.runner.scores = (0.1, 0.1, 0.8)
        for _ in range(3):
            box = tracked_box()
            manager.update([box], self.image, {0})
        self.assertEqual(box["label"], "medium_tactical")
        self.assertEqual(box["classification_count"], 5)
        self.assertEqual(len(manager.histories[0]), 5)

    def test_single_high_confidence_outlier_does_not_override_four_cm34_votes(self):
        manager = ready_manager()
        for _ in range(4):
            self.classify(manager, (0.36, 0.35, 0.29))
        box = self.classify(manager, (0.005, 0.99, 0.005))
        self.assertEqual(box["label"], "cm34")
        self.assertEqual(box["classifier_raw_index"], 1)
        self.assertEqual(box["classifier_votes"], [4, 1, 0])
        self.assertEqual(box["classifier_confidence"], 0.8)
        np.testing.assert_allclose(box["classifier_probs"], [0.8, 0.2, 0])
        np.testing.assert_allclose(box["classifier_raw_probs"], [0.005, 0.99, 0.005])

    def test_startup_tie_keeps_displayed_class_then_majority_updates_it(self):
        manager = ready_manager()
        first = self.classify(manager, (0.1, 0.8, 0.1))
        self.assertEqual(first["label"], "light_tactical")
        self.assertEqual(first["classification_count"], 1)
        tied = self.classify(manager, (0.8, 0.1, 0.1))
        self.assertEqual(tied["label"], "light_tactical")
        self.assertEqual(tied["classifier_votes"], [1, 1, 0])
        majority = self.classify(manager, (0.8, 0.1, 0.1))
        self.assertEqual(majority["label"], "cm34")
        self.assertEqual(majority["classifier_votes"], [2, 1, 0])

    def test_tie_does_not_keep_previous_class_if_it_has_fewer_votes(self):
        manager = ready_manager()
        for index in (0, 0, 1, 1, 2):
            scores = [0.1]*3
            scores[index] = 0.8
            box = self.classify(manager, scores)
        self.assertEqual(box["label"], "cm34")
        changed = self.classify(manager, (0.1, 0.1, 0.8))
        self.assertEqual(changed["classifier_votes"], [1, 2, 2])
        self.assertEqual(changed["label"], "medium_tactical")

    def test_votes_and_tie_preference_are_independent_per_track(self):
        manager = ready_manager()
        for _ in range(4):
            self.classify(manager, (0.8, 0.1, 0.1), key=0, active_ids={0, 1})
            other = self.classify(manager, (0.1, 0.8, 0.1), key=1, active_ids={0, 1})
        box = self.classify(manager, (0.1, 0.8, 0.1), key=0, active_ids={0, 1})
        self.assertEqual(box["label"], "cm34")
        self.assertEqual(other["label"], "light_tactical")
        self.assertEqual(manager.selected_indices, {0: 0, 1: 1})

    def test_one_result_history_updates_immediately(self):
        manager = ready_manager(history_size=1)
        self.classify(manager, (0.8, 0.1, 0.1))
        box = self.classify(manager, (0.1, 0.8, 0.1))
        self.assertEqual(box["label"], "light_tactical")
        self.assertEqual(box["classification_count"], 1)

    def test_switching_to_car_clears_fine_classification_history(self):
        manager = ready_manager()
        manager.update([tracked_box()], self.image, {0})
        manager.update([tracked_box("car")], self.image, {0})
        self.assertNotIn(0, manager.histories)
        self.assertNotIn(0, manager.selected_indices)
        manager.runner.scores = (0.1, 0.8, 0.1)
        box = tracked_box()
        manager.update([box], self.image, {0})
        self.assertEqual(box["label"], "light_tactical")
        self.assertEqual(box["classification_count"], 1)

    def test_missing_engine_does_not_interrupt_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ClassificationManager(Path(directory)/"pending.engine", SETTINGS_PATH)
            box = tracked_box()
            manager.update([box], self.image, {0})
            self.assertEqual(box["label"], "military_car")
            self.assertEqual(manager.status()["state"], "waiting_engine")

    def test_engine_appearing_later_is_loaded_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)/"pending.engine"
            runner = FakeRunner()
            manager = ClassificationManager(engine, SETTINGS_PATH,
                                            runner_factory=lambda path, settings: runner)
            self.assertFalse(manager.ensure_ready())
            engine.write_bytes(b"test fixture")
            os.utime(engine, (0, 0))
            manager.next_retry = 0
            self.assertTrue(manager.ensure_ready())
            box = tracked_box()
            manager.update([box], self.image, {0})
            self.assertEqual(box["label"], "cm34")

    def test_partial_engine_is_not_loaded_while_being_written(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)/"building.engine"
            engine.write_bytes(b"partial")
            manager = ClassificationManager(engine, SETTINGS_PATH,
                                            runner_factory=lambda *args: self.fail("loaded partial engine"))
            self.assertFalse(manager.ensure_ready())
            self.assertEqual(manager.state, "engine_building")

    def test_runner_failure_keeps_detection_and_other_boxes(self):
        manager = ready_manager()
        manager.runner.predict = lambda crop: (_ for _ in ()).throw(RuntimeError("bad engine"))
        boxes = [tracked_box(), tracked_box("car", key=1)]
        manager.update(boxes, self.image, {0, 1})
        self.assertEqual([box["label"] for box in boxes], ["military_car", "car"])
        self.assertEqual(manager.state, "error")

    def test_expired_and_reset_tracks_discard_classification(self):
        manager = ready_manager()
        manager.update([tracked_box()], self.image, {0})
        manager.update([], self.image, set())
        self.assertEqual(manager.histories, {})
        self.assertEqual(manager.selected_indices, {})
        manager.update([tracked_box()], self.image, {0})
        manager.reset()
        self.assertEqual(manager.histories, {})
        self.assertEqual(manager.selected_indices, {})

    def test_preprocessing_rgb_scaling_and_normalization(self):
        image = np.full((10, 20, 3), [10, 20, 30], dtype=np.uint8)
        output = preprocess(image, SETTINGS)
        self.assertEqual(output.shape, (1, 3, 224, 224))
        self.assertEqual(output.dtype, np.float32)
        expected = (np.array([30, 20, 10])/255-np.array(SETTINGS["mean"])) / SETTINGS["std"]
        np.testing.assert_allclose(output[0, :, 0, 0], expected, rtol=1e-6)

    def test_logits_softmax_is_stable_and_invalid_outputs_are_rejected(self):
        np.testing.assert_allclose(probabilities([1000, 1000, 1000]), [1/3]*3)
        for output in ([1, 2], [np.nan, 0, 1], [np.inf, 0, 1]):
            with self.assertRaises(ValueError):
                probabilities(output)


class ConfigTests(unittest.TestCase):
    def test_defaults_select_requested_models_and_mapping(self):
        with patch("rtsp_yolo_direct_cls.config.load_turn_settings", return_value=None):
            config = parse_args([])
        self.assertEqual(Path(config.model_path).name, "test3.engine")
        self.assertEqual(Path(config.classifier_model_path).name, "classifier_fp16.engine")
        self.assertEqual(config.track_hold_seconds, 0.5)
        self.assertEqual(SETTINGS["labels"], ["cm34", "light_tactical", "medium_tactical"])


class InferenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        from .inference import InferenceWorker
        self.worker = object.__new__(InferenceWorker)
        self.worker.config = SimpleNamespace(
            tracker="legacy", altitude_agl_m=110, camera_pitch_deg=-50,
            camera_yaw_offset_deg=0, hfov_deg=49.4, vfov_deg=29.7, track_hold_seconds=0.5)
        self.worker.tracker = TargetTracker()
        self.worker.tracker_epoch = self.worker.tracker.epoch
        self.worker.classifier = ready_manager()
        self.runner = self.worker.classifier.runner
        self.worker.processed_frames = 0
        self.worker.last_result_at = self.worker.fps = None
        self.worker._gps_for_frame = lambda frame: (
            SimpleNamespace(latitude=25, longitude=121, course_deg=0), "valid", 0)
        self.worker._gps_details = lambda gps: {"enabled": True}

    def process(self, pts, label="military_car", generation=1):
        boxes = [] if label is None else [SimpleNamespace(
            xyxy=[np.array([20, 20, 60, 60])], conf=[0.9], cls=[0])]
        prediction = SimpleNamespace(boxes=boxes, names={0: label})
        self.worker.model = SimpleNamespace(predict=lambda *args, **kwargs: [prediction])
        frame = SimpleNamespace(image=np.zeros((100, 100, 3), dtype=np.uint8),
                                generation=generation, pts90k=round(pts*90000),
                                receive_mono_ns=round(pts*1e9))
        return self.worker._process(frame)

    def test_missing_target_emits_no_box_and_keeps_classification_for_recovery(self):
        self.process(0)
        measured = self.process(0.1)["boxes"][0]
        self.assertIn("target_lat", measured)
        self.assertEqual(self.process(0.2, None)["boxes"], [])
        self.assertEqual(len(self.runner.calls), 2)
        self.assertTrue(self.worker.classifier.histories)
        recovered = self.process(0.3)["boxes"][0]
        self.assertEqual(recovered["track_id"], measured["track_id"])
        self.assertEqual(recovered["classification_count"], 3)
        self.assertEqual(recovered["label"], "cm34")
        self.assertEqual(self.process(0.81, None)["boxes"], [])

    def test_car_switch_and_return_to_military_use_fresh_history(self):
        original = self.process(0)["boxes"][0]
        car = self.process(0.1, "car")["boxes"][0]
        self.assertEqual(original["track_id"], car["track_id"])
        self.assertEqual(car["label"], "car")
        self.assertEqual(len(self.runner.calls), 1)
        self.runner.scores = (0.1, 0.1, 0.8)
        returned = self.process(0.2)["boxes"][0]
        self.assertEqual(returned["label"], "medium_tactical")
        self.assertEqual(returned["classification_count"], 1)

    def test_source_reset_removes_both_tracking_and_classification_history(self):
        self.process(0)
        self.process(0.1)
        self.assertTrue(self.worker.classifier.histories)
        self.assertEqual(self.process(0.2, None, generation=2)["boxes"], [])
        self.assertEqual(self.worker.classifier.histories, {})


if __name__ == "__main__":
    unittest.main()
