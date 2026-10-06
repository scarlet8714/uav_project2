"""Five-minute GPS receiver rate probe; prints aggregate statistics only."""

import collections
import json
import statistics
import time

import pynmea2
import serial

from gps_geolocation import GPS_PORT, GPS_BAUDRATE, _configure_5hz


def main():
    counts = collections.Counter()
    intervals = []
    last_rmc = None
    start = time.monotonic()
    with serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1, exclusive=True) as ser:
        _configure_5hz(ser)
        while time.monotonic() - start < 300:
            raw = ser.readline()
            if not raw:
                counts["timeout"] += 1
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if not line.startswith("$"):
                counts["non_nmea"] += 1
                continue
            try:
                msg = pynmea2.parse(line, check=True)
            except pynmea2.ParseError:
                counts["parse_or_checksum_error"] += 1
                continue
            counts[msg.sentence_type] += 1
            if msg.sentence_type == "RMC":
                now = time.monotonic()
                if last_rmc is not None:
                    intervals.append(now - last_rmc)
                last_rmc = now
                counts["rmc_valid_fix" if msg.status == "A" else "rmc_invalid_fix"] += 1
            if int(time.monotonic() - start) % 60 == 0 and counts["RMC"] % 5 == 0:
                print(json.dumps({"elapsed_s": round(time.monotonic() - start, 1), "rmc": counts["RMC"]}), flush=True)
    result = {"elapsed_s": round(time.monotonic() - start, 1), "counts": dict(counts)}
    if intervals:
        result["rmc_rate_hz"] = round((len(intervals) / sum(intervals)), 3)
        result["rmc_interval_median_ms"] = round(statistics.median(intervals) * 1000, 1)
        result["rmc_interval_max_ms"] = round(max(intervals) * 1000, 1)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
