"""Probe the configured STUN server, direct H.264, TURN fallback, and forced TURN.

Run: python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_ice
Both test peers run on this Jetson; this does not prove NAT traversal from a remote browser.
Does not open the camera, GPS, TensorRT model, or application HTTP port.
"""

import argparse
import asyncio
from dataclasses import replace
import json

from aioice import Connection
from aioice.ice import TransportPolicy
from aiortc.rtcicetransport import parse_stun_turn_uri

from .check_turn import probe_webrtc
from .turn import DEFAULT_CONFIG, load_turn_settings


async def probe_stun(settings):
    parsed = parse_stun_turn_uri(settings.stun_url)
    connection = Connection(ice_controlling=True, stun_server=(parsed["host"], parsed["port"]),
                            transport_policy=TransportPolicy.ALL, use_ipv6=False)
    result = {"probe": "stun_binding", "stun_url": settings.stun_url, "ok": False}
    try:
        await asyncio.wait_for(connection.gather_candidates(), 12)
        result["candidate_types"] = sorted({candidate.type for candidate in connection.local_candidates})
        result["srflx_addresses"] = [[candidate.host, candidate.port]
                                     for candidate in connection.local_candidates if candidate.type == "srflx"]
        if not result["srflx_addresses"]:
            raise RuntimeError("STUN returned no server-reflexive candidates")
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}".replace(settings.password, "[redacted]")
    finally:
        await connection.close()
    return result


async def run(args):
    settings = load_turn_settings(args.turn_config, args.turn_url, args.stun_url)
    checks = (
        ("stun_binding", lambda: probe_stun(settings)),
        ("direct_h264", lambda: probe_webrtc(settings, expected_path="direct")),
        # Both SDP descriptions expose only relay candidates to simulate missing
        # direct routes. The sender keeps the application's default ALL policy.
        ("turn_fallback_h264", lambda: probe_webrtc(settings, receiver_policy="relay", expected_path="turn",
                                                   relay_candidates_only=True)),
        ("forced_turn_h264", lambda: probe_webrtc(replace(settings, ice_transport_policy="relay"),
                                                 expected_path="turn")),
    )
    results = []
    for name, check in checks:
        try:
            result = await asyncio.wait_for(check(), 55)
        except asyncio.TimeoutError:
            result = {"ok": False, "error": "Probe timed out after 55 seconds"}
        result["check"] = name
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)
    return 0 if all(result["ok"] for result in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turn-config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--turn-url")
    parser.add_argument("--stun-url")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
