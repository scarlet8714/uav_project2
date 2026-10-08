"""Synthetic H.264 + metadata + channel replacement through the real TURN/server code.

Run: python -m rtsp_yolo_direct_with_gcp_and_datachannel.check_datachannel
Uses no camera, GPS device, YOLO model, HTTP port or production viewer session.
"""

import argparse
import asyncio
from collections import deque
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

from .turn import DEFAULT_CONFIG, enforce_relay, load_turn_settings, require_relay_candidates, selected_pair


async def probe(settings):
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription

    from . import server
    from .codec import preferences, profile_from_sps, register_profile
    from .metadata import LABEL, PROTOCOL
    from .source import EncodedTrack

    result = {"ok": False, "synthetic": True, "turn_url": settings.url, "stage": "setup"}
    browser, producer, app = None, None, None
    try:
        encoder = av.CodecContext.create("libx264", "w")
        encoder.width, encoder.height, encoder.pix_fmt = 160, 120, "yuv420p"
        encoder.time_base, encoder.framerate = Fraction(1, 30), Fraction(30, 1)
        encoder.options = {"tune": "zerolatency", "preset": "ultrafast", "profile": "baseline",
                           "x264-params": "keyint=1"}
        frame = av.VideoFrame(160, 120, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        frame.pts = 0
        encoded = bytes(encoder.encode(frame)[0])
        profile = profile_from_sps(encoded)
        register_profile(profile)

        source = SimpleNamespace(ready=True, generation=1, profile_id=profile, tracks=set(),
                                 config=SimpleNamespace(playout_delay_ms=0), on_event=lambda *args: None)
        source.new_track = lambda: EncodedTrack(source)
        config = SimpleNamespace(turn=settings)
        events = []
        app = {"config": config, "source": source, "peers": {}, "offer_lock": asyncio.Lock(),
               "recent_peer_closures": deque(maxlen=16),
               "log": SimpleNamespace(write=lambda kind, **fields: events.append((kind, fields)))}
        browser = RTCPeerConnection(settings.rtc_configuration())
        video = browser.addTransceiver("video", direction="recvonly")
        video.setCodecPreferences(preferences(profile))
        browser_ice = enforce_relay(video)
        remote_track = asyncio.get_running_loop().create_future()

        @browser.on("track")
        def on_track(track):
            if not remote_track.done():
                remote_track.set_result(track)

        def new_channel():
            channel = browser.createDataChannel(LABEL, ordered=True, protocol=PROTOCOL)
            opened = asyncio.Event()
            messages = asyncio.Queue()

            @channel.on("open")
            def on_open():
                opened.set()

            @channel.on("message")
            def on_message(data):
                messages.put_nowait(json.loads(data))

            return channel, opened, messages

        first, first_opened, first_messages = new_channel()
        result["stage"] = "signaling"
        await asyncio.wait_for(browser.setLocalDescription(await browser.createOffer()), 15)
        require_relay_candidates(browser_ice)

        async def offer_json():
            return {"sdp": browser.localDescription.sdp, "type": "offer",
                    "clientRevision": "synthetic-datachannel-probe"}

        response = await asyncio.wait_for(server.offer(SimpleNamespace(
            app=app, remote="synthetic-probe", json=offer_json)), 15)
        answer = json.loads(response.text)
        await browser.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        peer = app["peers"][answer["peerId"]]
        track = peer["track"]

        async def feed_packets():
            index = 0
            while True:
                packet = av.Packet(encoded)
                packet.pts = packet.dts = index * 3000
                packet.time_base, packet.is_keyframe = Fraction(1, 90000), True
                track.feed(packet)
                index += 1
                await asyncio.sleep(1 / 30)

        producer = asyncio.create_task(feed_packets())
        result["stage"] = "video_and_metadata"
        await asyncio.wait_for(first_opened.wait(), 15)
        incoming = await asyncio.wait_for(remote_track, 15)
        frames = [await asyncio.wait_for(incoming.recv(), 10) for _ in range(5)]
        origin = await asyncio.wait_for(first_messages.get(), 5)
        if origin != {"type": "origin", "rtpOrigin": peer["origin"]}:
            raise RuntimeError("Missing or incorrect RTP origin")
        payload = {"type": "detection", "generation": 1, "ptsSeconds": track.last_pts / 90000,
                   "width": 160, "height": 120,
                   "boxes": [{"label": "synthetic-car", "target_lat": 23.0, "target_lon": 121.0}]}
        server.publish(app, payload)
        if await asyncio.wait_for(first_messages.get(), 5) != payload:
            raise RuntimeError("YOLO/GPS payload mismatch")
        bundled = (browser.sctp.transport is video.sender.transport
                   and peer["pc"].sctp.transport is peer["pc"].getTransceivers()[0].sender.transport)
        if not bundled:
            raise RuntimeError("Video and metadata do not share a DTLS/ICE transport")

        result["stage"] = "replace_metadata_channel"
        closed = asyncio.Event()
        first.on("close", closed.set)
        first.close()
        await asyncio.wait_for(closed.wait(), 10)
        before = peer["sent_packets"]
        second, second_opened, second_messages = new_channel()
        await asyncio.wait_for(second_opened.wait(), 10)
        if await asyncio.wait_for(second_messages.get(), 5) != origin:
            raise RuntimeError("Replacement channel did not resend the same RTP origin")
        payload = {**payload, "ptsSeconds": track.last_pts / 90000}
        server.publish(app, payload)
        if await asyncio.wait_for(second_messages.get(), 5) != payload:
            raise RuntimeError("Replacement channel metadata mismatch")
        await asyncio.wait_for(incoming.recv(), 10)
        pairs = [selected_pair(browser_ice), selected_pair(peer["ice_connection"])]
        if not all(pair and pair["relay_verified"] for pair in pairs):
            raise RuntimeError("ICE selected a non-relay pair")
        if (browser.connectionState != "connected" or peer["pc"].connectionState != "connected"
                or peer["sent_packets"] <= before):
            raise RuntimeError("Video did not remain live during metadata channel replacement")
        result.update(ok=True, stage="complete", frames=len(frames) + 1,
                      dimensions=[frames[0].width, frames[0].height], bundled=bundled,
                      pairs=pairs, origin_resent=True, metadata_payloads=2,
                      video_preserved=True, offer_count=1,
                      metadata=peer["metadata"].snapshot())
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}".replace(settings.password, "[redacted]")
    finally:
        if producer is not None:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        if app is not None:
            await asyncio.gather(*(server.close_peer(app, peer_id, "probe_complete")
                                   for peer_id in tuple(app["peers"])), return_exceptions=True)
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), 10)
            except Exception:
                pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turn-config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--turn-url")
    parser.add_argument("--output", type=Path, help="Save the sanitized probe result as JSON")
    args = parser.parse_args()
    settings = load_turn_settings(args.turn_config, args.turn_url)
    result = asyncio.run(asyncio.wait_for(probe(settings), 75))
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")
    print(encoded)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
