"""Probe TURN auth, two relay allocations, ICE, and bidirectional payloads.

Run from the project root: python -m rtsp_yolo_direct_with_gcp.check_turn
Does not open the camera, GPS, TensorRT model, or application HTTP port.
"""

import argparse
import asyncio
from dataclasses import replace
import json
import time

from aioice import Connection
from aioice.ice import TransportPolicy

from .turn import DEFAULT_CONFIG, load_turn_settings, require_relay_candidates, selected_pair


async def probe(settings):
    parsed = settings.parsed
    connections = [Connection(
        ice_controlling=controlling,
        turn_server=(parsed["host"], parsed["port"]),
        turn_username=settings.username, turn_password=settings.password,
        turn_transport=parsed["transport"], turn_ssl=parsed["scheme"] == "turns",
        transport_policy=TransportPolicy.RELAY, use_ipv6=False,
    ) for controlling in (True, False)]
    result = {"turn_url": settings.url, "ok": False, "stage": "allocation"}
    try:
        await asyncio.wait_for(asyncio.gather(
            *(connection.gather_candidates() for connection in connections)), 12)
        for connection in connections:
            require_relay_candidates(connection)
        result["relay_addresses"] = [[candidate.host, candidate.port]
                                     for connection in connections
                                     for candidate in connection.local_candidates]
        result["stage"] = "ice_connect"
        a, b = connections
        for local, remote in ((a, b), (b, a)):
            local.remote_username, local.remote_password = remote.local_username, remote.local_password
            for candidate in remote.local_candidates:
                await local.add_remote_candidate(candidate)
            await local.add_remote_candidate(None)
        await asyncio.wait_for(asyncio.gather(a.connect(), b.connect()), 15)
        result["pairs"] = [selected_pair(connection) for connection in connections]
        if not all(pair and pair["relay_verified"] for pair in result["pairs"]):
            raise RuntimeError("ICE selected a non-relay pair")
        result["stage"] = "payload_roundtrip"
        roundtrips = []
        for index in range(5):
            start = time.monotonic()
            payload = f"gcp-turn-probe-{index}".encode()
            await a.send(payload)
            received = await asyncio.wait_for(b.recv(), 5)
            if received != payload:
                raise RuntimeError("Forward payload mismatch")
            await b.send(received)
            if await asyncio.wait_for(a.recv(), 5) != payload:
                raise RuntimeError("Return payload mismatch")
            roundtrips.append(round((time.monotonic() - start) * 1000, 2))
        result.update(ok=True, stage="complete", roundtrip_ms=roundtrips)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}".replace(settings.password, "[redacted]")
    finally:
        await asyncio.gather(*(connection.close() for connection in connections), return_exceptions=True)
    return result


async def probe_webrtc(settings):
    """Send small pre-encoded H.264 packets using the application's real track."""
    from fractions import Fraction
    from types import SimpleNamespace

    import av
    from aiortc import RTCPeerConnection

    from .codec import preferences, profile_from_sps, register_profile
    from .source import EncodedTrack
    from .turn import enforce_relay

    result = {"turn_url": settings.url, "probe": "webrtc_h264", "ok": False,
              "stage": "setup"}
    peers, producer = [], None
    try:
        # The diagnostic alone encodes this synthetic black frame. Production
        # still forwards the camera's compressed H.264 without re-encoding.
        encoder = av.CodecContext.create("libx264", "w")
        encoder.width, encoder.height, encoder.pix_fmt = 160, 120, "yuv420p"
        encoder.time_base, encoder.framerate = Fraction(1, 30), Fraction(30, 1)
        encoder.options = {"tune": "zerolatency", "preset": "ultrafast",
                           "profile": "baseline", "x264-params": "keyint=1"}
        frame = av.VideoFrame(160, 120, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        frame.pts = 0
        data = bytes(encoder.encode(frame)[0])
        profile = profile_from_sps(data)
        register_profile(profile)
        source = SimpleNamespace(tracks=set(), config=SimpleNamespace(playout_delay_ms=0),
                                 on_event=lambda *args: None)
        track = EncodedTrack(source)
        sender, receiver = [RTCPeerConnection(settings.rtc_configuration()) for _ in range(2)]
        peers = [sender, receiver]
        tx = sender.addTransceiver("video", direction="sendonly")
        tx.sender.replaceTrack(track)
        rx = receiver.addTransceiver("video", direction="recvonly")
        for transceiver in (tx, rx):
            transceiver.setCodecPreferences(preferences(profile))
        connections = [enforce_relay(transceiver) for transceiver in (tx, rx)]
        remote_track = asyncio.get_running_loop().create_future()

        @receiver.on("track")
        def received_track(incoming):
            if not remote_track.done():
                remote_track.set_result(incoming)

        result["stage"] = "signaling"
        await receiver.setLocalDescription(await receiver.createOffer())
        require_relay_candidates(connections[1])
        await sender.setRemoteDescription(receiver.localDescription)
        await sender.setLocalDescription(await sender.createAnswer())
        require_relay_candidates(connections[0])
        await receiver.setRemoteDescription(sender.localDescription)

        async def feed_packets():
            index = 0
            while True:
                packet = av.Packet(data)
                packet.pts = packet.dts = index * 3000
                packet.time_base, packet.is_keyframe = Fraction(1, 90000), True
                track.feed(packet)
                index += 1
                await asyncio.sleep(1 / 30)

        producer = asyncio.create_task(feed_packets())
        result["stage"] = "decoded_frames"
        incoming = await asyncio.wait_for(remote_track, 15)
        received = [await asyncio.wait_for(incoming.recv(), 15) for _ in range(5)]
        pairs = [selected_pair(connection) for connection in connections]
        if not all(pair and pair["relay_verified"] for pair in pairs):
            raise RuntimeError("WebRTC selected a non-relay pair")
        result.update(ok=True, stage="complete", frames=len(received),
                      dimensions=[received[0].width, received[0].height],
                      h264_profile=profile, pairs=pairs)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}".replace(settings.password, "[redacted]")
    finally:
        if producer is not None:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
    return result


async def run(args):
    settings = load_turn_settings(args.turn_config, args.turn_url)
    if args.both:
        parsed = settings.parsed
        host = parsed["host"]
        host = f"[{host}]" if ":" in host else host
        urls = [f"turn:{host}:{parsed['port']}?transport={transport}" for transport in ("udp", "tcp")]
    else:
        urls = [settings.url]
    results = []
    for url in urls:
        probe_function = probe_webrtc if args.webrtc else probe
        result = await asyncio.wait_for(probe_function(replace(settings, url=url)), 55)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
    return 0 if all(result["ok"] for result in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turn-config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--turn-url")
    parser.add_argument("--both", action="store_true", help="Test plain TURN UDP and TCP separately")
    parser.add_argument("--webrtc", action="store_true", help="Test ICE/DTLS and compressed H.264 delivery")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
