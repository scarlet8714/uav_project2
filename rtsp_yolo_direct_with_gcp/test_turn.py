"""Run: python -m unittest rtsp_yolo_direct_with_gcp.test_turn -v."""

import asyncio
from collections import deque
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aioice.ice import TransportPolicy
from aiortc.rtp import RtpPacket

from .config import parse_args
from .source import EncodedTrack
from .turn import (TurnSettings, enforce_relay, load_turn_settings,
                   require_relay_candidates, selected_pair)
from . import server


DUMMY = TurnSettings("turn:example.test:3478?transport=udp", "test", "secret</script>")


class TurnConfigTests(unittest.TestCase):
    def test_file_environment_and_url_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            path = Path(directory) / "turn.env"
            path.write_text("# comment\nTURN_URL=turn:example.test:3478?transport=udp\n"
                            "TURN_USERNAME='file-user'\nTURN_PASSWORD=file-secret\n")
            self.assertEqual(load_turn_settings(path).username, "file-user")
            with patch.dict("os.environ", {"TURN_PASSWORD": "environment-secret"}):
                settings = load_turn_settings(path, "turn:example.test:3478?transport=tcp")
                self.assertEqual(settings.password, "environment-secret")
                self.assertEqual(settings.parsed["transport"], "tcp")
                self.assertNotIn("environment-secret", repr(settings))
                config = parse_args(["--turn-config", str(path)])
                self.assertEqual(config.port, 8081)
                self.assertNotIn("environment-secret", repr(config))

    def test_missing_credentials_do_not_enable_direct_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Missing"):
                load_turn_settings("/tmp/turn-config-that-does-not-exist")

    def test_rejects_stun_and_unsupported_transports_without_echoing_secret(self):
        with patch.dict("os.environ", {"TURN_USERNAME": "test", "TURN_PASSWORD": "secret"}, clear=True):
            for url in ("stun:example.test", "turn:example.test?transport=bad",
                        "turns:example.test?transport=udp", "turn:example.test:99999"):
                with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                    load_turn_settings("/tmp/turn-config-that-does-not-exist", url)
                self.assertNotIn("secret", str(caught.exception))


def fake_connection(candidate_type="relay"):
    return SimpleNamespace(_transport_policy=TransportPolicy.ALL, _local_candidates_start=False,
                           turn_server=("example.test", 3478),
                           local_candidates=[SimpleNamespace(type=candidate_type)], _nominated={})


class RelayPolicyTests(unittest.TestCase):
    def test_backend_policy_is_set_before_gathering(self):
        connection = fake_connection()
        transceiver = SimpleNamespace(sender=SimpleNamespace(transport=SimpleNamespace(
            transport=SimpleNamespace(iceGatherer=SimpleNamespace(_connection=connection)))))
        self.assertIs(enforce_relay(transceiver), connection)
        self.assertEqual(connection._transport_policy, TransportPolicy.RELAY)
        connection._local_candidates_start = True
        with self.assertRaisesRegex(RuntimeError, "gathering already started"):
            enforce_relay(transceiver)

    def test_empty_and_host_candidates_fail_closed(self):
        for candidates in ([], [SimpleNamespace(type="host")]):
            connection = fake_connection()
            connection.local_candidates = candidates
            with self.assertRaisesRegex(RuntimeError, "TURN allocation failed"):
                require_relay_candidates(connection)

    def test_pair_verifies_both_relay_endpoints(self):
        connection = fake_connection()
        self.assertIsNone(selected_pair(connection))
        local = SimpleNamespace(type="relay", host="203.0.113.1", port=50000, transport="udp")
        remote = SimpleNamespace(type="host", host="192.0.2.1", port=50001)
        connection._nominated[1] = SimpleNamespace(local_candidate=local, remote_candidate=remote)
        self.assertFalse(selected_pair(connection)["relay_verified"])
        remote.type = "relay"
        self.assertTrue(selected_pair(connection)["relay_verified"])


class TurnServerTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        entries = []
        source = SimpleNamespace(ready=True, generation=1, profile_id="4d4028", tracks=set(),
                                 config=SimpleNamespace(playout_delay_ms=150),
                                 on_event=lambda *args: None,
                                 status=lambda: {"connected": True})
        source.new_track = lambda: EncodedTrack(source)
        config = SimpleNamespace(turn=DUMMY, model_path="test2.engine", tracker="legacy",
                                 transport="udp", playout_delay_ms=150, rtsp_timeout=5)
        return {"config": config, "source": source, "peers": {}, "offer_lock": asyncio.Lock(),
                "recent_peer_closures": deque(maxlen=16),
                "log": SimpleNamespace(write=lambda kind, **fields: entries.append((kind, fields))),
                "inference": SimpleNamespace(status=lambda: {"last_frame_age_s": 0}),
                "entries": entries}

    async def test_html_has_relay_config_and_no_cache_but_health_omits_credentials(self):
        app = self.make_app()
        response = await server.index(SimpleNamespace(app=app))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn('"iceTransportPolicy": "relay"', response.text)
        self.assertIn("secret\\u003c/script>", response.text)
        self.assertNotIn("secret</script>", response.text)
        snapshot = json.dumps(server.health_snapshot(app))
        self.assertNotIn(DUMMY.password, snapshot)
        self.assertNotIn('"credential"', snapshot)

    async def setup_offer(self, candidate_type="relay"):
        app = self.make_app()
        handlers = {}
        connection = fake_connection(candidate_type)
        sent = []

        async def send(data):
            sent.append(data)

        transport = SimpleNamespace(_send_rtp=send, transport=SimpleNamespace(
            iceGatherer=SimpleNamespace(_connection=connection)))

        class Peer:
            connectionState = "new"
            iceConnectionState = "new"

            def __init__(self, configuration):
                self.configuration = configuration

            def on(self, name):
                def register(fn):
                    handlers[name] = fn
                    return fn
                return register

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

        request = SimpleNamespace(app=app, remote="test", json=params)
        with patch.object(server, "RTCPeerConnection", Peer), patch.object(server, "preferences", return_value=[]):
            response = await server.offer(request)
        return app, response, connection, transport, handlers

    async def test_offer_preserves_packet_timestamp_path_with_relay_configuration(self):
        app, response, connection, transport, handlers = await self.setup_offer()
        peer_id = json.loads(response.text)["peerId"]
        peer = app["peers"][peer_id]
        peer["track"].last_pts = 100
        packet = RtpPacket(payload_type=96, timestamp=1100, ssrc=1, payload=b"video")
        await transport._send_rtp(packet.serialize())
        self.assertEqual(peer["origin"], 1000)
        self.assertEqual(peer["sent_packets"], 1)
        self.assertEqual(connection._transport_policy, TransportPolicy.RELAY)
        self.assertEqual(peer["pc"].configuration.iceServers[0].credential, DUMMY.password)
        await server.close_peer(app, peer_id, "test_complete")

    async def test_allocation_failure_returns_502(self):
        with self.assertRaises(web.HTTPBadGateway):
            await self.setup_offer(candidate_type="host")

    async def test_connected_peer_without_verified_relay_pair_is_closed(self):
        app, response, connection, transport, handlers = await self.setup_offer()
        peer_id = json.loads(response.text)["peerId"]
        app["peers"][peer_id]["pc"].connectionState = "connected"
        await handlers["connectionstatechange"]()
        self.assertNotIn(peer_id, app["peers"])
        self.assertEqual(app["recent_peer_closures"][-1]["reason"], "relay_policy_violation")


if __name__ == "__main__":
    unittest.main()
