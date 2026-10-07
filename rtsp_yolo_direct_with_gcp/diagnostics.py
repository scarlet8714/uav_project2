"""Compact terminal status without querying or blocking media transports."""


def _age(value):
    return "--" if value is None else f"{value:.3f}s"


def format_status(snapshot):
    rtsp, yolo = snapshot["rtsp"], snapshot["yolo"]
    fps = "--" if yolo["fps"] is None else f"{yolo['fps']:.1f}"
    inference = yolo.get("inference_ms")
    inference = "--" if inference is None else f"{inference:.1f}ms"
    peers = []
    for peer in snapshot["peers"]:
        track = peer["track"]
        queue = "--" if track is None else f"{track['queue_size']}/{track['queue_capacity']}"
        keyframe = "" if track is None or not track["waiting_keyframe"] else ",waiting-keyframe"
        pair = peer.get("ice_pair")
        relay = "" if pair is None else f",path={pair['local_type']}/{pair['remote_type']}"
        peers.append(f"{peer['id']}:{peer['connection_state']}/ICE={peer['ice_state']}"
                     f",tx={peer['sent_packets']},tx-age={_age(peer['last_rtp_age_s'])}"
                     f",queue={queue}{keyframe}{relay}")
    return (f"RTSP={'up' if rtsp['connected'] else 'down'}"
            f" packets={rtsp['packets']} age={_age(rtsp['last_packet_age_s'])}"
            f" reconnects={rtsp['reconnects']}"
            f" | decode={rtsp.get('decoded_frames', '--')}"
            f" age={_age(rtsp.get('last_decoded_age_s'))}"
            f" | YOLO={fps}fps/{inference} age={_age(yolo['last_frame_age_s'])}"
            f" queue={yolo.get('queue_size', '--')}/1 dropped={yolo.get('dropped_frames', 0)}"
            f" | GPS={yolo['gps_status']}"
            f" | WebRTC={len(peers)} " + ("; ".join(peers) if peers else "no-viewer"))


def format_event(kind, fields):
    parts = [kind]
    for name in ("peer_id", "reason", "state", "connection_state", "generation",
                 "profile_id", "reconnects", "error", "sent_packets", "last_rtp_age_s",
                 "model_path", "tracker", "transport", "receive_max_delay_ms",
                 "playout_delay_ms", "log_directory", "turn_url", "ice_transport_policy",
                 "ice_pair", "frontend_revision", "client_revision", "client_reconnect_reason"):
        if name in fields:
            parts.append(f"{name}={fields[name]}")
    if kind in ("input_stall", "input_recovered"):
        rtsp, yolo = fields["rtsp"], fields["yolo"]
        parts.extend((f"RTSP={'up' if rtsp['connected'] else 'down'}",
                      f"YOLO-age={_age(yolo['last_frame_age_s'])}"))
    return " ".join(parts).replace("\n", " ").replace("\r", " ")
