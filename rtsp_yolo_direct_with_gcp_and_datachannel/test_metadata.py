"""DataChannel transport, origin delivery, backpressure and lifecycle regressions."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from aiohttp.test_utils import make_mocked_request

from . import server
from .metadata import LABEL, PROTOCOL, MAX_BUFFERED_BYTES, MAX_MESSAGE_BYTES, MetadataSender


class FakeDataChannel:
    def __init__(self, state="open", **overrides):
        self.label, self.protocol = LABEL, PROTOCOL
        self.ordered = True
        self.maxRetransmits = self.maxPacketLifeTime = None
        self.readyState = state
        self.bufferedAmount = 0
        self.bufferedAmountLowThreshold = 0
        self.messages, self.handlers = [], {}
        self.fail_send = False
        self.count_buffered = False
        for key, value in overrides.items():
            setattr(self, key, value)

    def on(self, event):
        def register(callback):
            self.handlers[event] = callback
            return callback
        return register

    def emit(self, event):
        if event in self.handlers:
            self.handlers[event]()

    def send(self, message):
        if self.fail_send:
            raise RuntimeError("send failed")
        self.messages.append(json.loads(message))
        if self.count_buffered:
            self.bufferedAmount += len(message.encode("utf-8"))

    def close(self):
        self.readyState = "closed"
        self.emit("close")

    def open(self):
        self.readyState = "open"
        self.emit("open")

    def drain(self):
        self.bufferedAmount = 0
        self.emit("bufferedamountlow")


def detection(pts=1):
    return {"type": "detection", "generation": 1, "ptsSeconds": pts,
            "width": 960, "height": 544, "boxes": [{"label": "car", "target_lat": 23.0}]}


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.peer = {"origin": 123456, "generation": 1, "closing": False,
                     "pc": SimpleNamespace(connectionState="connected"),
                     "track": SimpleNamespace(readyState="live")}
        self.app = {"peers": {"viewer": self.peer},
                    "log": SimpleNamespace(write=lambda kind, **data: self.events.append((kind, data)))}
        self.sender = MetadataSender(self.app, "viewer", self.peer)
        self.peer["metadata"] = self.sender

    def test_already_open_remote_channel_gets_origin_then_yolo_and_gps(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        self.assertEqual(channel.messages, [{"type": "origin", "rtpOrigin": 123456}])
        server.publish(self.app, detection())
        self.assertEqual(channel.messages[-1], detection())
        self.assertTrue(self.sender.snapshot()["connected"])
        self.assertEqual(self.events[0][0], "metadata_connected")

    def test_channel_opening_later_gets_latest_result_only(self):
        channel = FakeDataChannel("connecting")
        self.sender.attach(channel)
        self.sender.publish(detection(1))
        self.sender.publish(detection(2))
        self.assertEqual(channel.messages, [])
        channel.open()
        self.assertEqual(channel.messages[0]["type"], "origin")
        self.assertEqual(channel.messages[1]["ptsSeconds"], 2)
        self.assertEqual(self.sender.dropped_detections, 1)

    def test_origin_becoming_available_after_data_channel_open_is_sent(self):
        self.peer["origin"] = None
        channel = FakeDataChannel()
        self.sender.attach(channel)
        self.assertEqual(channel.messages, [])
        self.peer["origin"] = 1000
        self.sender.origin_available()
        self.assertEqual(channel.messages, [{"type": "origin", "rtpOrigin": 1000}])

    def test_replacement_resends_origin_and_old_callbacks_leave_new_channel_intact(self):
        first, second = FakeDataChannel(), FakeDataChannel()
        self.sender.attach(first)
        self.sender.attach(second)
        self.assertEqual(first.readyState, "closed")
        self.assertIs(self.sender.channel, second)
        first.emit("close")
        first.emit("bufferedamountlow")
        self.sender.publish(detection())
        self.assertEqual(second.messages[0]["type"], "origin")
        self.assertEqual(len(first.messages), 1)
        self.assertEqual(second.messages[-1], detection())
        self.assertEqual(self.peer["pc"].connectionState, "connected")
        self.assertEqual(self.peer["track"].readyState, "live")

    def test_closed_channel_preserves_video_and_can_be_replaced(self):
        first = FakeDataChannel()
        self.sender.attach(first)
        first.close()
        self.assertFalse(self.sender.snapshot()["connected"])
        self.assertEqual(self.peer["pc"].connectionState, "connected")
        second = FakeDataChannel()
        self.sender.attach(second)
        self.assertEqual(second.messages[0]["rtpOrigin"], 123456)

    def test_backpressure_retains_one_latest_result_and_flushes_after_drain(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        channel.bufferedAmount = MAX_BUFFERED_BYTES
        for i in range(100):
            self.sender.publish(detection(i))
        self.assertEqual(len(channel.messages), 1)
        self.assertEqual(self.sender.snapshot()["pending_results"], 1)
        self.assertEqual(self.sender.dropped_detections, 99)
        channel.drain()
        self.assertEqual(channel.messages[-1]["ptsSeconds"], 99)
        self.assertEqual(self.sender.snapshot()["pending_results"], 0)

    def test_origin_has_priority_when_new_channel_buffer_is_full(self):
        channel = FakeDataChannel(bufferedAmount=MAX_BUFFERED_BYTES)
        self.sender.attach(channel)
        self.sender.publish(detection())
        self.assertEqual(channel.messages, [])
        channel.drain()
        self.assertEqual([item["type"] for item in channel.messages], ["origin", "detection"])

    def test_buffer_limit_includes_message_utf8_bytes(self):
        channel = FakeDataChannel(count_buffered=True)
        self.sender.attach(channel)
        large = detection()
        large["padding"] = "目" * 10000
        for _ in range(10):
            self.sender.publish(large)
        self.assertLessEqual(channel.bufferedAmount, MAX_BUFFERED_BYTES)
        self.assertEqual(self.sender.snapshot()["pending_results"], 1)
        channel.drain()
        self.assertEqual(self.sender.snapshot()["pending_results"], 0)

    def test_oversized_detection_is_dropped_without_failing_video(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        value = detection()
        value["padding"] = "x" * MAX_MESSAGE_BYTES
        self.sender.publish(value)
        self.assertEqual(len(channel.messages), 1)
        self.assertEqual(self.sender.snapshot()["pending_results"], 0)
        self.assertEqual(self.peer["pc"].connectionState, "connected")
        self.assertEqual(self.events[-1][0], "metadata_message_too_large")

    def test_send_failure_closes_only_metadata_channel(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        channel.fail_send = True
        self.sender.publish(detection())
        self.assertEqual(channel.readyState, "closed")
        self.assertEqual(self.peer["pc"].connectionState, "connected")
        self.assertIn("send failed", self.sender.last_error)

    def test_wrong_protocol_or_reliability_cannot_replace_valid_channel(self):
        active = FakeDataChannel()
        self.sender.attach(active)
        for options in ({"label": "other"}, {"protocol": "other"}, {"ordered": False},
                        {"maxRetransmits": 0}, {"maxPacketLifeTime": 1000}):
            with self.subTest(options=options):
                invalid = FakeDataChannel(**options)
                self.sender.attach(invalid)
                self.assertEqual(invalid.readyState, "closed")
                self.assertIs(self.sender.channel, active)

    def test_other_source_generation_is_ignored(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        self.sender.publish({**detection(), "generation": 2})
        self.assertEqual(len(channel.messages), 1)

    def test_stop_cancels_delivery_and_ignores_late_events(self):
        channel = FakeDataChannel()
        self.sender.attach(channel)
        self.sender.stop()
        channel.emit("open")
        channel.emit("bufferedamountlow")
        self.sender.publish(detection())
        self.assertEqual(channel.readyState, "closed")
        self.assertEqual(len(channel.messages), 1)
        self.assertIsNone(self.sender.channel)

    def test_closing_or_removed_peer_rejects_new_channel(self):
        for removed in (False, True):
            if removed:
                self.app["peers"].clear()
            else:
                self.peer["closing"] = True
            channel = FakeDataChannel()
            self.sender.attach(channel)
            self.assertEqual(channel.readyState, "closed")


class RoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_route_is_removed_but_signaling_and_health_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            app = server.create_app(SimpleNamespace(log_dir=directory))
            try:
                for method, path in (("GET", "/"), ("POST", "/offer"), ("GET", "/api/health")):
                    match = await app.router.resolve(make_mocked_request(method, path, app=app))
                    self.assertIsNone(match.http_exception)
                match = await app.router.resolve(make_mocked_request("GET", "/events/viewer", app=app))
                self.assertEqual(match.http_exception.status, 404)
            finally:
                app["log"].close()


if __name__ == "__main__":
    unittest.main()
