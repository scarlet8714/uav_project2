"""Run: python -m unittest diagnostics.test_direct_backend_status -v."""

import asyncio
from collections import deque
from contextlib import redirect_stdout
import io
import json
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiortc.rtp import RtpPacket, RtcpRrPacket

from rtsp_yolo_direct.diagnostics import format_status
from rtsp_yolo_direct.inference import InferenceWorker
from rtsp_yolo_direct.source import EncodedTrack, RtspSource
from rtsp_yolo_direct import server


class Log:
    def __init__(self):
        self.events = []

    def write(self, kind, **fields):
        self.events.append((kind, fields))


def make_app():
    rtsp = dict(connected=True, packets=300, last_packet_age_s=.02,
                reconnects=0, decoded_frames=290, last_decoded_age_s=.03)
    yolo = dict(fps=13.2, inference_ms=70.1, last_frame_age_s=.04,
                queue_size=1, dropped_frames=8, gps_status="invalid_fix")
    source = SimpleNamespace(status=lambda: rtsp, tracks=set(), ready=True,
                             generation=1, profile_id="4d4028", on_event=lambda *args: None,
                             config=SimpleNamespace(playout_delay_ms=150))
    source.new_track = lambda: EncodedTrack(source)
    return {"source": source, "inference": SimpleNamespace(status=lambda: yolo),
            "config": SimpleNamespace(model_path="test2.engine", tracker="legacy",
                                      transport="udp", playout_delay_ms=150, rtsp_timeout=5),
            "peers": {}, "recent_peer_closures": deque(maxlen=16), "log": Log(),
            "offer_lock": asyncio.Lock()}


class BackendStatusTests(unittest.TestCase):
    def test_console_includes_progress_and_handles_startup_without_frames(self):
        app = make_app()
        snapshot = server.health_snapshot(app)
        text = format_status(snapshot)
        for expected in ("RTSP=up", "decode=290", "YOLO=13.2fps/70.1ms",
                         "dropped=8", "GPS=invalid_fix", "WebRTC=0 no-viewer"):
            self.assertIn(expected, text)
        snapshot["yolo"].update(fps=None, inference_ms=None, last_frame_age_s=None)
        snapshot["rtsp"].update(connected=False, last_packet_age_s=None)
        self.assertIn("YOLO=--fps/--", format_status(snapshot))

    def test_events_print_immediately_but_health_samples_do_not_flood_terminal(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            log = server.EventLog(directory)
            log.write("peer_closing", peer_id="test", reason="superseded_by_new_offer",
                      sent_packets=123)
            log.write("health_sample", rtsp={}, yolo={})
            log.close()
            console = output.getvalue()
            self.assertIn("reason=superseded_by_new_offer", console)
            self.assertNotIn("health_sample", console)
            entries = [json.loads(line) for line in (log.directory / "events.jsonl").read_text().splitlines()]
            self.assertEqual(len(entries), 2)

    def test_inference_counts_skipped_and_replaced_waiting_frames(self):
        worker = object.__new__(InferenceWorker)
        worker.running = True
        worker.submit_generation = None
        worker.source_frame_count = worker.skipped_frames = worker.dropped_frames = 0
        worker.jobs = queue.Queue(maxsize=1)
        frames = [SimpleNamespace(generation=1, number=n) for n in (1, 2, 3)]
        for frame in frames:
            worker.submit(frame)
        self.assertIs(worker.jobs.get_nowait(), frames[2])
        self.assertEqual((worker.skipped_frames, worker.dropped_frames), (1, 1))

    def test_decoder_exception_is_recorded_and_still_propagates(self):
        source = object.__new__(RtspSource)
        log = Log()
        source.on_event = log.write
        source._decode_frames = lambda *args: (_ for _ in ()).throw(RuntimeError("decoder failed"))
        with self.assertRaisesRegex(RuntimeError, "decoder failed"):
            source._decoder_loop(None, 1, None)
        self.assertIn("decoder failed", source.decoder_error)
        self.assertEqual(log.events[0][0], "decoder_error")


class PeerStatusTests(unittest.IsolatedAsyncioTestCase):
    async def create_offer(self):
        self.app = make_app()
        self.sent = []
        self.fail_send = False

        async def send(data):
            if self.fail_send:
                raise RuntimeError("send failed")
            self.sent.append(data)

        self.transport = SimpleNamespace(_send_rtp=send)
        transport = self.transport

        class Peer:
            connectionState = "connected"
            iceConnectionState = "completed"

            def on(self, event):
                return lambda fn: fn

            def addTransceiver(self, *args, **kwargs):
                return SimpleNamespace(setCodecPreferences=lambda codecs: None,
                                       sender=SimpleNamespace(transport=transport, replaceTrack=lambda track: None))

            async def setRemoteDescription(self, description):
                pass

            async def createAnswer(self):
                return SimpleNamespace(sdp="answer", type="answer")

            async def setLocalDescription(self, description):
                self.localDescription = description

            async def close(self):
                self.connectionState = self.iceConnectionState = "closed"

        async def params():
            return {"sdp": "offer", "type": "offer"}

        request = SimpleNamespace(app=self.app, remote="test-client", json=params)
        with patch.object(server, "RTCPeerConnection", Peer), patch.object(server, "preferences", return_value=[]):
            response = await server.offer(request)
        self.peer_id = json.loads(response.text)["peerId"]
        self.peer = self.app["peers"][self.peer_id]
        self.peer["track"].last_pts = 0

    async def test_rtcp_does_not_look_like_video_progress(self):
        await self.create_offer()
        with patch.object(server.time, "monotonic", return_value=10):
            await self.transport._send_rtp(bytes(RtcpRrPacket(ssrc=1)))
        self.assertIsNone(self.peer["origin"])
        self.assertIsNone(self.peer["last_rtp_at"])
        self.assertEqual((self.peer["sent_packets"], self.peer["sent_rtcp_packets"]), (0, 1))
        packet = RtpPacket(payload_type=96, timestamp=1000, ssrc=1, payload=b"video")
        with patch.object(server.time, "monotonic", return_value=11):
            await self.transport._send_rtp(packet.serialize())
        self.assertEqual(self.peer["origin"], 1000)
        snapshot = server.health_snapshot(self.app, now=12)
        self.assertEqual(snapshot["peers"][0]["last_rtp_age_s"], 1)
        self.assertIn("waiting-keyframe", format_status(snapshot))

    async def test_close_keeps_final_snapshot_and_reason(self):
        await self.create_offer()
        await server.close_peer(self.app, self.peer_id, "superseded_by_new_offer")
        snapshot = server.health_snapshot(self.app)
        self.assertEqual(snapshot["peers"], [])
        closure = snapshot["recent_peer_closures"][-1]
        self.assertEqual(closure["id"], self.peer_id)
        self.assertEqual(closure["reason"], "superseded_by_new_offer")
        self.assertEqual(closure["track"]["queue_capacity"], 120)

    async def test_send_failure_records_error_without_hiding_exception(self):
        await self.create_offer()
        self.fail_send = True
        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await self.transport._send_rtp(RtpPacket(payload_type=96, payload=b"video").serialize())
        self.assertIn("send failed", self.peer["last_send_error"])
        self.assertEqual(self.app["log"].events[-1][0], "rtp_send_error")

    async def test_watchdog_prints_every_five_seconds_and_logs_peer_snapshots(self):
        app = make_app()
        clock = [0]

        async def tick(delay):
            clock[0] += delay
            if clock[0] > 7:
                raise asyncio.CancelledError

        with patch.object(server.asyncio, "sleep", tick), \
                patch.object(server.time, "monotonic", lambda: clock[0]), \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(asyncio.CancelledError):
                await server.watchdog(app)
        self.assertEqual(output.getvalue().count("STATUS"), 2)
        samples = [fields for kind, fields in app["log"].events if kind == "health_sample"]
        self.assertEqual(len(samples), 7)
        self.assertTrue(all("peers" in fields for fields in samples))


if __name__ == "__main__":
    unittest.main()
