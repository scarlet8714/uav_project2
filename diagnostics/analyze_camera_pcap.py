"""Summarize camera traffic and RTCP BYE from dumpcap pcapng files."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import socket
import struct


def packets(path):
    with path.open("rb") as f:
        endian = "<"
        while header := f.read(8):
            if len(header) != 8:
                break
            kind, size = struct.unpack(endian + "II", header)
            if kind == 0x0A0D0D0A:
                marker = f.read(4)
                endian = "<" if marker == b"\x4d\x3c\x2b\x1a" else ">"
                f.seek(size - 12, 1)
                continue
            body = f.read(size - 8)
            if kind != 6 or len(body) != size - 8:
                continue
            _, hi, lo, caplen, _ = struct.unpack_from(endian + "IIIII", body)
            yield (hi << 32 | lo) / 1_000_000_000, body[20:20 + caplen]


def decode(frame):
    if len(frame) < 34 or frame[12:14] != b"\x08\x00":
        return None
    ip = frame[14:]
    ihl = (ip[0] & 15) * 4
    if len(ip) < ihl + 8:
        return None
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    proto = ip[9]
    data = ip[ihl:]
    if proto == 17:
        sport, dport = struct.unpack_from("!HH", data)
        return src, dst, "udp", sport, dport, data[8:]
    if proto == 6 and len(data) >= 20:
        sport, dport = struct.unpack_from("!HH", data)
        offset = (data[12] >> 4) * 4
        flags = data[13]
        return src, dst, "tcp", sport, dport, data[offset:], flags
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--camera", default="192.168.144.135")
    args = parser.parse_args()
    counts = Counter()
    special = []
    last_camera = {}
    for path in args.paths:
        for stamp, frame in packets(path):
            decoded = decode(frame)
            if not decoded:
                continue
            src, dst, proto, sport, dport, payload, *rest = decoded
            if args.camera not in (src, dst):
                continue
            direction = "from_camera" if src == args.camera else "to_camera"
            counts[int(stamp), direction, proto] += 1
            last_camera[direction, proto] = stamp
            when = datetime.fromtimestamp(stamp, timezone.utc).astimezone().isoformat(timespec="milliseconds")
            if proto == "tcp":
                flags = rest[0]
                if flags & 0x05:
                    special.append((when, direction, "TCP FIN/RST", sport, dport, hex(flags)))
                for marker in (b"TEARDOWN", b"RTSP/1.0", b"GET_PARAMETER", b"OPTIONS"):
                    if payload.startswith(marker):
                        special.append((when, direction, "RTSP", sport, dport, payload[:100].decode("ascii", "replace")))
            elif proto == "udp":
                pos = 0
                while pos + 4 <= len(payload) and payload[pos] >> 6 == 2:
                    packet_type = payload[pos + 1]
                    if packet_type not in range(200, 205):
                        break
                    length = (struct.unpack_from("!H", payload, pos + 2)[0] + 1) * 4
                    if packet_type == 203:
                        special.append((when, direction, "RTCP BYE", sport, dport, payload[pos:pos + min(length, 32)].hex()))
                    if length <= 0:
                        break
                    pos += length
    print("Last packet by direction/protocol:")
    for key, stamp in last_camera.items():
        print(key, datetime.fromtimestamp(stamp, timezone.utc).astimezone().isoformat(timespec="milliseconds"))
    print("Special events:")
    for item in special:
        print(*item)
    print("Last 120 seconds of per-second counts:")
    if counts:
        end = max(key[0] for key in counts)
        for second in range(end - 119, end + 1):
            values = [counts[second, direction, proto] for direction, proto in
                      (("from_camera", "udp"), ("from_camera", "tcp"),
                       ("to_camera", "udp"), ("to_camera", "tcp"))]
            if any(values):
                print(datetime.fromtimestamp(second, timezone.utc).astimezone().isoformat(timespec="seconds"), *values)


if __name__ == "__main__":
    main()
