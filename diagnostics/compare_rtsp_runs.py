#!/usr/bin/env python3
"""Summarize source freshness separately from browser playback clocks."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def describe(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return {"mean": round(statistics.mean(values), 4),
            "p99": round(values[min(len(values)-1, int((len(values)-1)*.99))], 4),
            "max": round(values[-1], 4)}


def analyze(directory):
    events = read_events(directory / "stress_events.jsonl")
    samples = [e for e in events if e["kind"] == "sample"]
    if len(samples) < 2:
        return {"directory": str(directory), "samples": len(samples)}
    first, last = samples[0], samples[-1]
    duration = last["elapsed_s"] - first["elapsed_s"]
    rates = {}
    for group, key in [("rtsp", "frames"), ("yolo", "processed_frames")]:
        rates[group] = round((last["health"][group][key] - first["health"][group][key]) / duration, 4)
    early = [s for s in samples if s["elapsed_s"] <= 900]
    early_rates = {group: round((early[-1]["health"][group][key] - early[0]["health"][group][key])
                               / (early[-1]["elapsed_s"]-early[0]["elapsed_s"]), 4)
                   for group, key in [("rtsp", "frames"), ("yolo", "processed_frames")]}
    first300 = [s for s in samples if s["elapsed_s"] <= 300]
    first300_rates = {group: round((first300[-1]["health"][group][key] - first300[0]["health"][group][key])
                                  / (first300[-1]["elapsed_s"]-first300[0]["elapsed_s"]), 4)
                      for group, key in [("rtsp", "frames"), ("yolo", "processed_frames")]}
    stale = [s for s in samples if (s["health"]["yolo"].get("last_frame_age_s") or 0) >= 5]
    recovery = []
    for event in events:
        if event["kind"] == "browser_reload":
            candidate = next((s for s in samples if s["monotonic"] > event["monotonic"]
                              and s["browser"].get("peerState") == "connected"
                              and (s["browser"].get("videoCurrentTime") or 0) > 0
                              and (s["browser"].get("videoWidth") or 0) > 0), None)
            recovery.append(None if candidate is None else round(candidate["monotonic"]-event["monotonic"], 3))
    server_events = [e for p in directory.glob("server_diagnostics/*/events.jsonl") for e in read_events(p)]
    console = (directory / "server_console.log").read_text()
    tegra = (directory / "tegrastats.log").read_text()
    def numbers(pattern):
        return [float(x) for x in re.findall(pattern, tegra)]
    frozen_time = sum(b["elapsed_s"]-a["elapsed_s"] for a,b in zip(samples,samples[1:])
                      if (a["health"]["yolo"].get("last_frame_age_s") or 0) >= 5)
    return {
        "directory": str(directory), "samples": len(samples),
        "first_sample_time": first["time"], "last_sample_time": last["time"],
        "sample_span_s": round(duration, 3), "rates_fps": rates,
        "first_900s_rates_fps": early_rates,
        "first_300s_rates_fps": first300_rates,
        "last_rtsp": last["health"]["rtsp"], "last_yolo": last["health"]["yolo"],
        "yolo_age_s": describe([s["health"]["yolo"].get("last_frame_age_s") for s in samples]),
        "rtsp_age_s": describe([s["health"]["rtsp"].get("last_frame_age_seconds") for s in samples]),
        "yolo_stale_ge5s_samples": len(stale),
        "yolo_stale_ge5s_approx_seconds": round(frozen_time, 3),
        "first_yolo_stale_ge5s_elapsed_s": stale[0]["elapsed_s"] if stale else None,
        "eos_console_count": len(re.findall(r"^RTSP pipeline reached end of stream; reconnecting in 1 second$", console, re.M)),
        "udp_timeout_console_count": len(re.findall(r"^RTSP UDP input timed out after 5 seconds without a frame; reconnecting in 1 second$", console, re.M)),
        "estimated_final_yolo_frame_elapsed_s": round(last["elapsed_s"] - last["health"]["yolo"]["last_frame_age_s"], 3),
        "browser_refreshes": len(recovery),
        "browser_refresh_recovered": sum(x is not None for x in recovery),
        "browser_refresh_to_playing_s": describe(recovery),
        "max_peers": max(len(s["health"].get("peers", [])) for s in samples),
        "max_encoders": max(len(s["health"].get("encoders", [])) for s in samples),
        "encoder_errors_at_end": last["health"].get("recent_encoder_errors", []),
        "server_event_counts": dict(Counter(e["kind"] for e in server_events)),
        "configured": next((e.get("settings") for e in server_events if e["kind"] == "configured"), None),
        "resources": {"ram_mb": describe(numbers(r"RAM (\d+)/")),
                      "swap_mb": describe(numbers(r"SWAP (\d+)/")),
                      "temperature_c": describe(numbers(r"@(\d+(?:\.\d+)?)C")),
                      "vdd_in_mw": describe(numbers(r"VDD_IN (\d+)mW")),
                      "gr3d_percent": describe(numbers(r"GR3D_FREQ (\d+)%"))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    print(json.dumps([analyze(p) for p in args.runs], indent=2, ensure_ascii=False))
    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
        for directory in args.runs:
            samples = [e for e in read_events(directory / "stress_events.jsonl") if e["kind"] == "sample"]
            transport = samples[-1]["health"]["rtsp"].get("transport", "tcp (historical)")
            label = directory.name.split("_")[2] + " " + transport.upper()
            times, fps = [], []
            anchor = samples[0]
            for sample in samples[1:]:
                dt = sample["elapsed_s"] - anchor["elapsed_s"]
                if dt >= 10:
                    times.append((sample["elapsed_s"]+anchor["elapsed_s"])/120)
                    fps.append((sample["health"]["rtsp"]["frames"] - anchor["health"]["rtsp"]["frames"])/dt)
                    anchor = sample
            axes[0].plot(times, fps, label=label, linewidth=1.6)
            axes[1].plot([s["elapsed_s"]/60 for s in samples],
                         [s["health"]["yolo"]["last_frame_age_s"] for s in samples],
                         label=label, linewidth=1.6)
        axes[0].set_ylabel("New decoded RTSP frames / s")
        axes[0].set_ylim(bottom=0)
        axes[0].legend()
        axes[1].set_ylabel("Age of last YOLO output (s)")
        axes[1].set_xlabel("Elapsed test time (minutes)")
        axes[1].set_ylim(bottom=0)
        for axis in axes:
            axis.grid(alpha=.25)
            axis.set_xlim(0, 20)
        fig.suptitle("20-minute RTSP + YOLO + browser endurance comparison")
        fig.text(.5, .01, "Historical comparison: different Jetson power mode, RAM, model and browser; not a controlled transport A/B.",
                 ha="center", fontsize=8)
        fig.tight_layout(rect=(0,.035,1,.96))
        fig.savefig(args.plot, dpi=160)
        plt.close(fig)
