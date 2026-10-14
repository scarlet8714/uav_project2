"""Run: python -m unittest rtsp_yolo_direct_with_gcp_stun_cls.test_turn -v."""

import asyncio
from collections import deque
from dataclasses import replace
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
from .turn import (DEFAULT_STUN_URL, TurnSettings, configure_ice, enforce_relay,
                   load_turn_settings, require_ice_candidates, require_relay_candidates, selected_pair)
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
                self.assertEqual(config.port, 8082)
                self.assertEqual(config.turn.stun_url, DEFAULT_STUN_URL)
                self.assertEqual(config.turn.ice_transport_policy, "all")
                self.assertNotIn("environment-secret", repr(config))

    def test_stun_precedence_and_relay_cli_option(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            path = Path(directory) / "turn.env"
            path.write_text("TURN_URL=turn:example.test:3478?transport=udp\n"
                            "TURN_USERNAME=test\nTURN_PASSWORD=secret\nSTUN_URL=stun:file.test:3478\n")
            self.assertEqual(load_turn_settings(path).stun_url, "stun:file.test:3478")
            with patch.dict("os.environ", {"STUN_URL": "stun:env.test:3478"}):
                self.assertEqual(load_turn_settings(path).stun_url, "stun:env.test:3478")
                config = parse_args(["--turn-config", str(path), "--stun-url", "stun:cli.test:3478",
                                     "--ice-transport-policy", "relay", "--port", "8081"])
                self.assertEqual(config.turn.stun_url, "stun:cli.test:3478")
                self.assertEqual(config.turn.ice_transport_policy, "relay")
                self.assertEqual(config.port, 8081)

    def test_all_mode_registers_both_servers_but_relay_mode_omits_stun(self):
        from aiortc.rtcicetransport import connection_kwargs
        config = DUMMY.browser_configuration()
        self.assertEqual(config["iceTransportPolicy"], "all")
        self.assertEqual(config["iceServers"][0], {"urls": DEFAULT_STUN_URL})
        kwargs = connection_kwargs(DUMMY.rtc_configuration().iceServers)
        self.assertEqual(kwargs["stun_server"], ("104.155.197.179", 3478))
        self.assertEqual(kwargs["turn_server"], ("example.test", 3478))
        relay = replace(DUMMY, ice_transport_policy="relay")
        self.assertEqual(relay.browser_configuration()["iceTransportPolicy"], "relay")
        self.assertEqual(len(relay.browser_configuration()["iceServers"]), 1)
        self.assertNotIn("stun_server", connection_kwargs(relay.rtc_configuration().iceServers))

    def test_invalid_stun_url_is_rejected_without_echoing_secret(self):
        for url in ("", "turn:example.test:3478", "stun:example.test:99999", "https://example.test"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "Invalid STUN_URL"):
                replace(DUMMY, stun_url=url)

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
    def test_all_policy_allows_direct_even_when_turn_is_unavailable(self):
        connection = fake_connection("host")
        connection.turn_server = None
        transceiver = SimpleNamespace(sender=SimpleNamespace(transport=SimpleNamespace(
            transport=SimpleNamespace(iceGatherer=SimpleNamespace(_connection=connection)))))
        self.assertIs(configure_ice(transceiver, DUMMY), connection)
        self.assertEqual(connection._transport_policy, TransportPolicy.ALL)
        for kind in ("host", "srflx", "prflx", "relay"):
            connection.local_candidates = [SimpleNamespace(type=kind)]
            require_ice_candidates(connection, "all")
        connection.local_candidates = []
        with self.assertRaisesRegex(RuntimeError, "ICE gathering failed"):
            require_ice_candidates(connection, "all")

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

    def test_direct_and_mixed_relay_pairs_are_classified_correctly(self):
        connection = fake_connection()
        for local_type, remote_type, path in (("host", "srflx", "direct"),
                                              ("srflx", "prflx", "direct"),
                                              ("host", "relay", "turn"),
                                              ("relay", "srflx", "turn"),
                                              ("relay", "relay", "turn")):
            connection._nominated[1] = SimpleNamespace(
                local_candidate=SimpleNamespace(type=local_type, host="192.0.2.1", port=50000, transport="udp"),
                remote_candidate=SimpleNamespace(type=remote_type, host="203.0.113.1", port=50001))
            pair = selected_pair(connection)
            self.assertEqual(pair["path"], path)
            self.assertEqual(pair["uses_turn"], path == "turn")


class TurnServerTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, settings=DUMMY):
        entries = []
        source = SimpleNamespace(ready=True, generation=1, profile_id="4d4028", tracks=set(),
                                 config=SimpleNamespace(playout_delay_ms=150),
                                 on_event=lambda *args: None,
                                 status=lambda: {"connected": True})
        source.new_track = lambda: EncodedTrack(source)
        config = SimpleNamespace(turn=settings, model_path="test2.engine", tracker="legacy",
                                 transport="udp", playout_delay_ms=150, rtsp_timeout=5)
        return {"config": config, "source": source, "peers": {}, "offer_lock": asyncio.Lock(),
                "recent_peer_closures": deque(maxlen=16),
                "log": SimpleNamespace(write=lambda kind, **fields: entries.append((kind, fields))),
                "inference": SimpleNamespace(status=lambda: {"last_frame_age_s": 0}),
                "entries": entries}

    async def test_html_has_stun_and_turn_no_cache_but_health_omits_credentials(self):
        app = self.make_app()
        response = await server.index(SimpleNamespace(app=app))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn('"iceTransportPolicy": "all"', response.text)
        self.assertIn(DEFAULT_STUN_URL, response.text)
        self.assertIn("secret\\u003c/script>", response.text)
        self.assertNotIn("secret</script>", response.text)
        snapshot = json.dumps(server.health_snapshot(app))
        self.assertNotIn(DUMMY.password, snapshot)
        self.assertNotIn('"credential"', snapshot)
        self.assertEqual(server.health_snapshot(app)["settings"]["ice_transport_policy"], "all")

    async def test_relay_html_and_health_remain_relay_only(self):
        app = self.make_app(replace(DUMMY, ice_transport_policy="relay"))
        response = await server.index(SimpleNamespace(app=app))
        self.assertIn('"iceTransportPolicy": "relay"', response.text)
        self.assertNotIn(DEFAULT_STUN_URL, response.text)
        self.assertEqual(server.health_snapshot(app)["settings"]["ice_transport_policy"], "relay")

    async def setup_offer(self, candidate_type="host", settings=DUMMY):
        app = self.make_app(settings)
        handlers = {}
        connection = fake_connection(candidate_type)
        if candidate_type is None:
            connection.local_candidates = []
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

    async def test_direct_offer_preserves_packet_timestamp_path_and_turn_configuration(self):
        app, response, connection, transport, handlers = await self.setup_offer()
        peer_id = json.loads(response.text)["peerId"]
        peer = app["peers"][peer_id]
        peer["track"].last_pts = 100
        packet = RtpPacket(payload_type=96, timestamp=1100, ssrc=1, payload=b"video")
        await transport._send_rtp(packet.serialize())
        self.assertEqual(peer["origin"], 1000)
        self.assertEqual(peer["sent_packets"], 1)
        self.assertEqual(connection._transport_policy, TransportPolicy.ALL)
        self.assertEqual(peer["pc"].configuration.iceServers[-1].credential, DUMMY.password)
        self.assertEqual(peer["pc"].configuration.iceServers[0].urls, DEFAULT_STUN_URL)
        await server.close_peer(app, peer_id, "test_complete")

    async def test_empty_candidates_return_502_but_host_only_allocation_succeeds(self):
        with self.assertRaises(web.HTTPBadGateway):
            await self.setup_offer(candidate_type=None)
        app, response, *_ = await self.setup_offer(candidate_type="srflx")
        await server.close_peer(app, json.loads(response.text)["peerId"], "test_complete")

    async def test_connected_peer_without_selected_pair_is_closed(self):
        app, response, connection, transport, handlers = await self.setup_offer()
        peer_id = json.loads(response.text)["peerId"]
        app["peers"][peer_id]["pc"].connectionState = "connected"
        await handlers["connectionstatechange"]()
        self.assertNotIn(peer_id, app["peers"])
        self.assertEqual(app["recent_peer_closures"][-1]["reason"], "ice_pair_missing")

    async def test_direct_and_turn_connected_peers_are_kept_in_all_mode(self):
        for local_type, remote_type, event in (("srflx", "host", "ice_direct_connected"),
                                               ("host", "relay", "turn_relay_connected"),
                                               ("relay", "relay", "turn_relay_connected")):
            app, response, connection, _, handlers = await self.setup_offer()
            peer_id = json.loads(response.text)["peerId"]
            connection._nominated[1] = SimpleNamespace(
                local_candidate=SimpleNamespace(type=local_type, host="192.0.2.1", port=50000, transport="udp"),
                remote_candidate=SimpleNamespace(type=remote_type, host="203.0.113.1", port=50001))
            app["peers"][peer_id]["pc"].connectionState = "connected"
            await handlers["connectionstatechange"]()
            self.assertIn(peer_id, app["peers"])
            self.assertTrue(any(kind == event for kind, _ in app["entries"]))
            self.assertIsNotNone(app["peers"][peer_id]["connected_at"])
            await server.close_peer(app, peer_id, "test_complete")

    async def test_forced_relay_preserves_policy_and_rejects_direct_pairs(self):
        settings = replace(DUMMY, ice_transport_policy="relay")
        with self.assertRaises(web.HTTPBadGateway):
            await self.setup_offer(candidate_type="host", settings=settings)
        app, response, connection, _, handlers = await self.setup_offer(candidate_type="relay", settings=settings)
        self.assertEqual(connection._transport_policy, TransportPolicy.RELAY)
        peer_id = json.loads(response.text)["peerId"]
        connection._nominated[1] = SimpleNamespace(
            local_candidate=SimpleNamespace(type="relay", host="192.0.2.1", port=50000, transport="udp"),
            remote_candidate=SimpleNamespace(type="host", host="203.0.113.1", port=50001))
        app["peers"][peer_id]["pc"].connectionState = "connected"
        await handlers["connectionstatechange"]()
        self.assertNotIn(peer_id, app["peers"])
        self.assertEqual(app["recent_peer_closures"][-1]["reason"], "relay_policy_violation")


if __name__ == "__main__":
    unittest.main()
