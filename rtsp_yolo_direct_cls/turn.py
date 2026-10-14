"""STUN/direct ICE with TURN fallback, plus optional relay-only enforcement."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from aioice.ice import TransportPolicy
from aiortc import RTCConfiguration, RTCIceServer
from aiortc.rtcicetransport import parse_stun_turn_uri


DEFAULT_CONFIG = Path(__file__).with_name(".turn.env")
DEFAULT_STUN_URL = "stun:104.155.197.179:3478"
KEYS = {"TURN_URL", "TURN_USERNAME", "TURN_PASSWORD"}


@dataclass(frozen=True)
class TurnSettings:
    url: str
    username: str
    password: str = field(repr=False)
    stun_url: str = DEFAULT_STUN_URL
    ice_transport_policy: str = "all"

    def __post_init__(self):
        if self.ice_transport_policy not in ("all", "relay"):
            raise ValueError("ICE transport policy must be all or relay")
        try:
            parsed = parse_stun_turn_uri(self.stun_url)
            valid = parsed["scheme"] == "stun" and 1 <= parsed["port"] <= 65535
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Invalid STUN_URL; use stun:host:port")

    @property
    def parsed(self):
        return parse_stun_turn_uri(self.url)

    def browser_configuration(self):
        servers = [{"urls": self.url, "username": self.username,
                    "credential": self.password}]
        if self.ice_transport_policy == "all":
            servers.insert(0, {"urls": self.stun_url})
        return {"iceServers": servers, "iceTransportPolicy": self.ice_transport_policy}

    def rtc_configuration(self):
        servers = [RTCIceServer(urls=self.url, username=self.username, credential=self.password)]
        # aioice gathers STUN srflx candidates even under its RELAY policy.
        # Omit STUN in relay-only mode so both endpoints remain relay-only.
        if self.ice_transport_policy == "all":
            servers.insert(0, RTCIceServer(urls=self.stun_url))
        return RTCConfiguration(iceServers=servers)

    def script_configuration(self):
        # Credentials may contain </script>; keep them inside the JSON literal.
        return json.dumps(self.browser_configuration()).replace("<", "\\u003c")


def load_turn_settings(path=DEFAULT_CONFIG, url_override=None, stun_url_override=None,
                       ice_transport_policy="all"):
    values = {}
    path = Path(path)
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or key not in KEYS | {"STUN_URL"}:
                raise ValueError(f"Invalid TURN config entry at line {number}")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key] = value
    for key in KEYS | {"STUN_URL"}:
        if key in os.environ:
            values[key] = os.environ[key]
    if url_override is not None:
        values["TURN_URL"] = url_override
    stun_url = (stun_url_override if stun_url_override is not None else
                values.get("STUN_URL", DEFAULT_STUN_URL))
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
    return TurnSettings(values["TURN_URL"], values["TURN_USERNAME"], values["TURN_PASSWORD"],
                        stun_url=stun_url, ice_transport_policy=ice_transport_policy)


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


def configure_ice(transceiver, settings):
    if settings.ice_transport_policy == "relay":
        return enforce_relay(transceiver)
    connection = relay_connection(transceiver)
    if not hasattr(connection, "_transport_policy") or connection._local_candidates_start:
        raise RuntimeError("Unsupported aiortc/aioice ICE API or ICE gathering already started")
    connection._transport_policy = TransportPolicy.ALL
    return connection


def require_relay_candidates(connection):
    candidates = connection.local_candidates
    if not candidates or any(candidate.type != "relay" for candidate in candidates):
        raise RuntimeError("TURN allocation failed: no relay-only candidates; check TURN authentication and firewall")


def require_ice_candidates(connection, policy):
    if policy == "relay":
        require_relay_candidates(connection)
    elif not connection.local_candidates:
        raise RuntimeError("ICE gathering failed: no candidates; check network interfaces and ICE servers")


def selected_pair(connection):
    if connection is None:
        return None
    pair = connection._nominated.get(1)
    if pair is None:
        return None
    local, remote = pair.local_candidate, pair.remote_candidate
    uses_turn = local.type == "relay" or remote.type == "relay"
    return {"local_type": local.type, "remote_type": remote.type,
            "local_address": local.host, "local_port": local.port,
            "remote_address": remote.host, "remote_port": remote.port,
            "candidate_transport": local.transport,
            "path": "turn" if uses_turn else "direct", "uses_turn": uses_turn,
            "relay_verified": local.type == "relay" and remote.type == "relay"}
