"""TURN configuration and relay enforcement for browser and aiortc peers."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from aioice.ice import TransportPolicy
from aiortc import RTCConfiguration, RTCIceServer
from aiortc.rtcicetransport import parse_stun_turn_uri


DEFAULT_CONFIG = Path(__file__).with_name(".turn.env")
KEYS = {"TURN_URL", "TURN_USERNAME", "TURN_PASSWORD"}


@dataclass(frozen=True)
class TurnSettings:
    url: str
    username: str
    password: str = field(repr=False)

    @property
    def parsed(self):
        return parse_stun_turn_uri(self.url)

    def browser_configuration(self):
        return {"iceServers": [{"urls": self.url, "username": self.username,
                                "credential": self.password}],
                "iceTransportPolicy": "relay"}

    def rtc_configuration(self):
        return RTCConfiguration(iceServers=[RTCIceServer(
            urls=self.url, username=self.username, credential=self.password)])

    def script_configuration(self):
        # Credentials may contain </script>; keep them inside the JSON literal.
        return json.dumps(self.browser_configuration()).replace("<", "\\u003c")


def load_turn_settings(path=DEFAULT_CONFIG, url_override=None):
    values = {}
    path = Path(path)
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in KEYS:
                raise ValueError(f"Invalid TURN config entry at line {number}")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    for key in KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    if url_override is not None:
        values["TURN_URL"] = url_override
    missing = sorted(key for key in KEYS if not values.get(key))
    if missing:
        raise ValueError("Missing " + ", ".join(missing) +
                         "; configure .turn.env or environment variables")
    try:
        parsed = parse_stun_turn_uri(values["TURN_URL"])
    except ValueError:
        raise ValueError("Invalid TURN_URL; use turn:host:port?transport=udp or tcp") from None
    if (parsed["scheme"] not in ("turn", "turns") or
            parsed.get("transport") not in ("udp", "tcp") or
            (parsed["scheme"] == "turns" and parsed["transport"] != "tcp") or
            not 1 <= parsed["port"] <= 65535):
        raise ValueError("TURN_URL must use turn UDP/TCP or turns TCP with a valid port")
    return TurnSettings(values["TURN_URL"], values["TURN_USERNAME"], values["TURN_PASSWORD"])


def relay_connection(transceiver):
    # aiortc 1.15 has no public iceTransportPolicy option. aioice 0.10 does.
    return transceiver.sender.transport.transport.iceGatherer._connection


def enforce_relay(transceiver):
    connection = relay_connection(transceiver)
    if not hasattr(connection, "_transport_policy") or connection._local_candidates_start:
        raise RuntimeError("Unsupported aiortc/aioice relay API or ICE gathering already started")
    if connection.turn_server is None:
        raise RuntimeError("TURN server is missing; refusing a direct connection")
    connection._transport_policy = TransportPolicy.RELAY
    return connection


def require_relay_candidates(connection):
    candidates = connection.local_candidates
    if not candidates or any(candidate.type != "relay" for candidate in candidates):
        raise RuntimeError("TURN allocation failed: no relay-only candidates; check TURN authentication and firewall")


def selected_pair(connection):
    if connection is None:
        return None
    pair = connection._nominated.get(1)
    if pair is None:
        return None
    local, remote = pair.local_candidate, pair.remote_candidate
    return {"local_type": local.type, "remote_type": remote.type,
            "local_address": local.host, "local_port": local.port,
            "remote_address": remote.host, "remote_port": remote.port,
            "candidate_transport": local.transport,
            "relay_verified": local.type == "relay" and remote.type == "relay"}
