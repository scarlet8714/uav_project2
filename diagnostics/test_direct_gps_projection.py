"""Offline geometry and inference checks for both direct streaming variants.

Run: python3 -m unittest diagnostics.test_direct_gps_projection -v
"""

from contextlib import ExitStack
import importlib
import io
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


VARIANTS = ("rtsp_yolo_direct", "rtsp_yolo_direct_with_gcp_stun")


class ProjectionTests(unittest.TestCase):
    def modules(self):
        for name in VARIANTS:
            yield name, importlib.import_module(name + ".gps")

    def pixel(self, module, x=960, y=540, **settings):
        return module.pixel_to_ground_offset(x, y, 1920, 1080, 110, **settings)

    def test_center_is_92_metres_forward_and_edges_have_expected_distances(self):
        # Analytic ground distances: H / tan(50°), H / tan(50° ± 14.85°).
        for name, module in self.modules():
            with self.subTest(variant=name):
                right, forward = self.pixel(module)
                self.assertAlmostEqual(right, 0)
                self.assertAlmostEqual(forward, 92.3009594295008)
                self.assertAlmostEqual(self.pixel(module, y=0)[1], 156.2241954748603)
                self.assertAlmostEqual(self.pixel(module, y=1080)[1], 51.644870097257034)
                self.assertAlmostEqual(self.pixel(module, x=1920)[0], 66.04622956246462)

    def test_left_right_symmetry_and_oblique_horizontal_scale(self):
        for name, module in self.modules():
            with self.subTest(variant=name):
                left = self.pixel(module, x=0)
                right = self.pixel(module, x=1920)
                self.assertAlmostEqual(left[0], -right[0])
                self.assertAlmostEqual(left[1], right[1])
                # The same horizontal pixel offset covers more ground at the top.
                self.assertGreater(self.pixel(module, x=1920, y=0)[0],
                                   self.pixel(module, x=1920, y=1080)[0])

    def test_nadir_pinhole_geometry_has_exact_half_width_offsets(self):
        for name, module in self.modules():
            with self.subTest(variant=name):
                # At 100 m with 90° FOV, a half-normalized offset is exactly 50 m.
                right, forward = module.pixel_to_ground_offset(
                    150, 25, 200, 100, 100, hfov_deg=90, vfov_deg=90,
                    camera_pitch_deg=-90)
                self.assertAlmostEqual(right, 50)
                self.assertAlmostEqual(forward, 50)
                right, forward = module.pixel_to_ground_offset(
                    50, 75, 200, 100, 100, hfov_deg=90, vfov_deg=90,
                    camera_pitch_deg=-90)
                self.assertAlmostEqual(right, -50)
                self.assertAlmostEqual(forward, -50)
                self.assertAlmostEqual(self.pixel(module, camera_pitch_deg=-90)[1], 0)

    def test_center_rotates_with_course_and_zero_camera_yaw_offset(self):
        for name, module in self.modules():
            for course, expected_north, expected_east in (
                (0, 92.3009594295008, 0), (90, 0, 92.3009594295008),
                (180, -92.3009594295008, 0), (270, 0, -92.3009594295008),
            ):
                with self.subTest(variant=name, course=course):
                    result = module.estimate_target_gps(
                        target_x=960, target_y=540, image_width=1920, image_height=1080,
                        altitude_agl_m=110, drone_lat=25, drone_lon=121, course_deg=course)
                    self.assertAlmostEqual(result["north_m"], expected_north)
                    self.assertAlmostEqual(result["east_m"], expected_east)
                    if course == 0:
                        self.assertGreater(result["target_lat"], 25)
                        self.assertAlmostEqual(result["target_lon"], 121)
                    elif course == 90:
                        self.assertGreater(result["target_lon"], 121)
                        self.assertAlmostEqual(result["target_lat"], 25)

    def test_nonzero_yaw_override_and_reader_pitch_override_are_propagated(self):
        for name, module in self.modules():
            with self.subTest(variant=name):
                result = module.estimate_target_gps(
                    target_x=960, target_y=540, image_width=1920, image_height=1080,
                    altitude_agl_m=110, drone_lat=25, drone_lon=121, course_deg=0,
                    camera_yaw_offset_deg=90)
                self.assertAlmostEqual(result["north_m"], 0)
                self.assertAlmostEqual(result["east_m"], 92.3009594295008)
                state = SimpleNamespace(fix_valid=True, latitude=25, longitude=121,
                                        course_deg=0, error=None)
                reader = SimpleNamespace(get_latest=lambda: state)
                result = module.estimate_target_gps_from_reader(
                    reader, target_x=960, target_y=540, image_width=1920,
                    image_height=1080, altitude_agl_m=110, camera_pitch_deg=-90)
                self.assertAlmostEqual(result["target_lat"], 25)
                self.assertAlmostEqual(result["target_lon"], 121)

    def test_sky_and_horizon_rays_have_no_ground_coordinate(self):
        for name, module in self.modules():
            for pitch in (-10, -14.85):
                with self.subTest(variant=name, pitch=pitch):
                    with self.assertRaisesRegex(ValueError, "intersect"):
                        self.pixel(module, y=0, camera_pitch_deg=pitch)

    def test_invalid_projection_inputs_are_rejected(self):
        for name, module in self.modules():
            for settings in ({"camera_pitch_deg": 0}, {"camera_pitch_deg": 10},
                             {"camera_pitch_deg": -91}, {"camera_pitch_deg": math.nan},
                             {"hfov_deg": math.inf}, {"vfov_deg": 180}):
                with self.subTest(variant=name, settings=settings):
                    with self.assertRaises(ValueError):
                        self.pixel(module, **settings)

    def parse(self, name, flags):
        config = importlib.import_module(name + ".config")
        with ExitStack() as stack:
            stack.enter_context(patch("sys.argv", ["projection-test", *flags]))
            if name.endswith("_stun"):
                stack.enter_context(patch.object(config, "load_turn_settings", return_value=object()))
            return config.parse_args()

    def test_cli_defaults_and_pitch_override(self):
        for name in VARIANTS:
            with self.subTest(variant=name):
                config = self.parse(name, [])
                self.assertEqual((config.altitude_agl_m, config.camera_pitch_deg,
                                  config.camera_yaw_offset_deg, config.hfov_deg, config.vfov_deg),
                                 (110, -50, 0, 49.4, 29.7))
                self.assertEqual(self.parse(name, ["--camera-pitch-deg", "-90"]).camera_pitch_deg, -90)

    def test_cli_rejects_horizontal_positive_and_nonfinite_pitch(self):
        for name in VARIANTS:
            for pitch in ("0", "10", "-91", "nan", "inf"):
                with self.subTest(variant=name, pitch=pitch), patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as failure:
                        self.parse(name, ["--camera-pitch-deg", pitch])
                    self.assertEqual(failure.exception.code, 2)

    def test_inference_keeps_sky_detection_and_projects_other_detection(self):
        for name in VARIANTS:
            with self.subTest(variant=name):
                inference = importlib.import_module(name + ".inference")
                worker = object.__new__(inference.InferenceWorker)
                worker.config = SimpleNamespace(tracker="legacy", altitude_agl_m=110,
                                                hfov_deg=49.4, vfov_deg=29.7,
                                                camera_yaw_offset_deg=0, camera_pitch_deg=-10)
                boxes = [SimpleNamespace(xyxy=[np.array(coords)], cls=[0], conf=[0.9])
                         for coords in ((90, 0, 110, 0), (90, 40, 110, 60))]
                prediction = SimpleNamespace(boxes=boxes, names={0: "car"})
                worker.model = SimpleNamespace(predict=lambda *args, **kwargs: [prediction])
                worker.tracker = inference.TargetTracker(confirm_frames=1)
                gps = SimpleNamespace(latitude=25, longitude=121, course_deg=0)
                worker._gps_for_frame = lambda frame: (gps, "valid", 0)
                worker._gps_details = lambda gps: {"enabled": True}
                worker.processed_frames = 0
                worker.last_result_at = worker.fps = None
                frame = SimpleNamespace(image=np.zeros((100, 200, 3), dtype=np.uint8),
                                        generation=1, pts90k=90000, receive_mono_ns=1000000000)
                result = worker._process(frame)
                self.assertEqual(len(result["boxes"]), 2)
                self.assertNotIn("target_lat", result["boxes"][0])
                self.assertGreater(result["boxes"][1]["target_lat"], 25)
                self.assertEqual(worker.processed_frames, 1)


if __name__ == "__main__":
    unittest.main()
