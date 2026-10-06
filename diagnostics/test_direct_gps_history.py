"""GPS history regressions; no camera, serial device, or YOLO model required.

Run: python -m unittest diagnostics.test_direct_gps_history
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pynmea2

from rtsp_yolo_direct.gps import GPSReader, GPS_HISTORY_SIZE
from rtsp_yolo_direct.inference import InferenceWorker


class GPSHistoryTests(unittest.TestCase):
    def setUp(self):
        self.reader = GPSReader()
        self.worker = object.__new__(InferenceWorker)
        self.worker.config = SimpleNamespace(no_gps=False)
        self.worker.gps = self.reader

    def rmc(self, at, status="A", speed="0.0", course="90.0"):
        message = pynmea2.parse(
            f"$GPRMC,120000.00,{status},2333.0000,N,12028.0000,E,"
            f"{speed},{course},061026,,,A")
        with patch("rtsp_yolo_direct.gps.time.monotonic", return_value=at):
            self.reader._handle_nmea(message)

    def frame_status(self, at):
        return self.worker._gps_for_frame(
            SimpleNamespace(receive_mono_ns=int(at * 1e9)))

    def test_select_previous_position_even_after_newer_updates(self):
        self.rmc(10, course="45")
        self.rmc(10.2, course="90")
        gps, status, age = self.frame_status(10.1)
        self.assertEqual((status, age, gps.course_deg), ("valid", 100.0, 45.0))
        self.assertEqual(self.frame_status(10.2)[0].course_deg, 90.0)
        # Historical freshness uses frame time, even when processing much later.
        with patch("rtsp_yolo_direct.gps.time.monotonic", return_value=100):
            self.assertEqual(self.frame_status(10.1)[1], "valid")

    def test_missing_history_never_uses_future_sample(self):
        self.rmc(10)
        self.assertEqual(self.frame_status(9.9)[1:], ("no_history", None))

    def test_invalid_fix_and_disconnect_block_old_valid_sample(self):
        self.rmc(10)
        self.rmc(10.2, status="V")
        self.assertEqual(self.frame_status(10.1)[1], "valid")
        self.assertEqual(self.frame_status(10.3)[1], "invalid_fix")
        with patch("rtsp_yolo_direct.gps.time.monotonic", return_value=10.4):
            self.reader._update_state(connected=False, fix_valid=False)
        self.assertEqual(self.frame_status(10.5)[1], "unavailable")

    def test_stale_position_and_missing_course(self):
        self.rmc(10, course="")
        self.assertEqual(self.frame_status(10.1)[1], "no_course")
        self.assertEqual(self.frame_status(12.1)[1], "stale")
        self.worker.config.no_gps = True
        self.assertEqual(self.frame_status(10.1), (None, "unavailable", None))

    def test_stationary_and_missing_speed_accept_course(self):
        self.rmc(10, speed="0", course="30")
        self.assertEqual(self.frame_status(10.1)[0].course_deg, 30)
        self.rmc(10.2, speed="", course="60")
        self.assertEqual(self.frame_status(10.3)[0].course_deg, 60)
        self.rmc(10.4, course="")
        state = self.frame_status(10.5)[0]
        self.assertEqual(state.course_deg, 60)
        self.assertEqual(state.last_course_update, 10.2)

    def test_vtg_course_does_not_leak_into_earlier_frame(self):
        self.rmc(10, course="")
        message = pynmea2.parse("$GPVTG,75.0,T,,M,0.0,N,0.0,K,A")
        with patch("rtsp_yolo_direct.gps.time.monotonic", return_value=10.2):
            self.reader._handle_nmea(message)
        self.assertEqual(self.frame_status(10.1)[1], "no_course")
        state, status, age = self.frame_status(10.3)
        self.assertEqual((state.course_deg, status, age), (75, "valid", 300.0))

    def test_history_is_bounded_and_returns_copies(self):
        for at in range(GPS_HISTORY_SIZE + 2):
            self.rmc(at)
        self.assertEqual(len(self.reader._history), GPS_HISTORY_SIZE)
        self.assertIsNone(self.reader.get_at_or_before(0))
        snapshot = self.reader.get_at_or_before(GPS_HISTORY_SIZE)
        snapshot.course_deg = 123
        self.assertEqual(self.reader.get_at_or_before(GPS_HISTORY_SIZE).course_deg, 90)

    def test_speed_gate_can_be_restored(self):
        self.reader.min_speed_for_cog_mps = 1.0
        self.rmc(10, speed="0", course="30")
        self.assertEqual(self.frame_status(10.1)[1], "no_course")
        self.rmc(10.2, speed="3", course="60")
        self.assertEqual(self.frame_status(10.3)[1], "valid")


if __name__ == "__main__":
    unittest.main()
