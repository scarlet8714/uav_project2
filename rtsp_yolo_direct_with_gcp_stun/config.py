"""Command line and fixed projection settings for this application."""

import argparse
from dataclasses import dataclass
import math

from .gps import (GPS_PORT, GPS_BAUDRATE, DEFAULT_ALTITUDE_AGL_M,
                  DEFAULT_CAMERA_PITCH_DEG, DEFAULT_HFOV_DEG, DEFAULT_VFOV_DEG,
                  DEFAULT_CAMERA_YAW_OFFSET_DEG)
from .turn import DEFAULT_CONFIG, TurnSettings, load_turn_settings


@dataclass(frozen=True)
class Config:
    rtsp_url: str
    transport: str
    rtsp_timeout: float
    playout_delay_ms: float
    model_path: str
    gps_port: str
    gps_baudrate: int
    no_gps: bool
    altitude_agl_m: float
    hfov_deg: float
    vfov_deg: float
    camera_yaw_offset_deg: float
    host: str
    port: int
    log_dir: str
    turn: TurnSettings
    tracker: str = "legacy"
    bytetrack_buffer: int = 5
    camera_pitch_deg: float = DEFAULT_CAMERA_PITCH_DEG


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="RTSP/WebRTC video with GCP STUN/direct ICE and TURN fallback, YOLO/GPS Canvas overlay")
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--rtsp-timeout", type=float, default=8.0)
    parser.add_argument("--playout-delay-ms", type=float, default=300.0,
                        help="WebRTC packet pacing buffer; 0 disables it")
    parser.add_argument("--model-path", default="test2.engine")
    parser.add_argument("--tracker", choices=("legacy", "bytetrack"), default="legacy",
                        help="Target matching: legacy (original) or ByteTrack")
    parser.add_argument("--bytetrack-buffer", type=int, default=5,
                        help="Lost track retention in YOLO updates (not video frames)")
    parser.add_argument("--gps-port", default=GPS_PORT)
    parser.add_argument("--gps-baudrate", type=int, default=GPS_BAUDRATE)
    parser.add_argument("--no-gps", action="store_true")
    parser.add_argument("--altitude-agl-m", type=float, default=DEFAULT_ALTITUDE_AGL_M)
    parser.add_argument("--hfov-deg", type=float, default=DEFAULT_HFOV_DEG)
    parser.add_argument("--vfov-deg", type=float, default=DEFAULT_VFOV_DEG)
    parser.add_argument("--camera-yaw-offset-deg", type=float, default=DEFAULT_CAMERA_YAW_OFFSET_DEG)
    parser.add_argument("--camera-pitch-deg", type=float, default=DEFAULT_CAMERA_PITCH_DEG,
                        help="Fixed camera pitch: 0 is horizontal, -90 is straight down")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--log-dir", default="diagnostics")
    parser.add_argument("--turn-config", default=str(DEFAULT_CONFIG),
                        help="TURN credentials file (default: module .turn.env)")
    parser.add_argument("--turn-url", help="Override TURN URL; one UDP, TCP or TLS URL per run")
    parser.add_argument("--stun-url", help="Override STUN URL (default: stun:104.155.197.179:3478)")
    parser.add_argument("--ice-transport-policy", choices=("all", "relay"), default="all",
                        help="all: allow direct ICE with TURN fallback; relay: force TURN on both peers")
    args = parser.parse_args(argv)
    if args.bytetrack_buffer < 0:
        parser.error("ByteTrack buffer must not be negative")
    if args.rtsp_timeout <= 0 or args.gps_baudrate <= 0:
        parser.error("RTSP timeout and GPS baudrate must be positive")
    if args.playout_delay_ms < 0:
        parser.error("playout delay must not be negative")
    if not all(math.isfinite(value) for value in (
        args.altitude_agl_m, args.hfov_deg, args.vfov_deg,
        args.camera_yaw_offset_deg, args.camera_pitch_deg,
    )):
        parser.error("camera projection settings must be finite")
    if args.altitude_agl_m <= 0 or not 0 < args.hfov_deg < 180 or not 0 < args.vfov_deg < 180:
        parser.error("invalid camera projection settings")
    if not -90 <= args.camera_pitch_deg < 0:
        parser.error("camera pitch must be at least -90 and below 0 degrees")
    try:
        turn = load_turn_settings(args.turn_config, args.turn_url, args.stun_url,
                                  args.ice_transport_policy)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    values = vars(args)
    values.pop("turn_config")
    values.pop("turn_url")
    values.pop("stun_url")
    values.pop("ice_transport_policy")
    return Config(**values, turn=turn)
