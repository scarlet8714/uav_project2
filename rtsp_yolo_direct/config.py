"""Command line and fixed projection settings for this application."""

import argparse
from dataclasses import dataclass


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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resilient direct RTSP/WebRTC video with YOLO/GPS Canvas overlay")
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--rtsp-timeout", type=float, default=5.0)
    parser.add_argument("--playout-delay-ms", type=float, default=150.0,
                        help="WebRTC packet pacing buffer; 0 disables it")
    parser.add_argument("--model-path", default="yolo11s.engine")
    parser.add_argument("--gps-port", default="/dev/ttyUSB0")
    parser.add_argument("--gps-baudrate", type=int, default=9600)
    parser.add_argument("--no-gps", action="store_true")
    parser.add_argument("--altitude-agl-m", type=float, default=75.0)
    parser.add_argument("--hfov-deg", type=float, default=52.0)
    parser.add_argument("--vfov-deg", type=float, default=31.0)
    parser.add_argument("--camera-yaw-offset-deg", type=float, default=180.0)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-dir", default="diagnostics")
    args = parser.parse_args()
    if args.rtsp_timeout <= 0 or args.gps_baudrate <= 0:
        parser.error("RTSP timeout and GPS baudrate must be positive")
    if args.playout_delay_ms < 0:
        parser.error("playout delay must not be negative")
    if args.altitude_agl_m <= 0 or not 0 < args.hfov_deg < 180 or not 0 < args.vfov_deg < 180:
        parser.error("invalid camera projection settings")
    return Config(**vars(args))
