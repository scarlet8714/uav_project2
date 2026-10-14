"""Short standalone RTSP classification measurement, without an HTTP/WebRTC service."""

import argparse
import asyncio
from collections import Counter, OrderedDict
from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rtsp_yolo_direct_cls.config import parse_args
from rtsp_yolo_direct_cls.classification import ClassificationManager
from rtsp_yolo_direct_cls.inference import InferenceWorker
from rtsp_yolo_direct_cls.source import RtspSource


def crop(image, box):
    h, w = image.shape[:2]
    x1, y1 = max(0, math.floor(box["x1"])), max(0, math.floor(box["y1"]))
    x2, y2 = min(w, math.ceil(box["x2"])), min(h, math.ceil(box["y2"]))
    return image[y1:y2, x1:x2].copy()


def changes(values):
    return sum(a != b for a, b in zip(values, values[1:]))


async def measure(seconds, tracker="legacy", target_region="center-upper"):
    directory = ROOT / "diagnostics" / datetime.now().strftime("cls_live_%Y%m%d_%H%M%S")
    directory.mkdir(parents=True)
    config = replace(parse_args(["--no-gps", "--tracker", tracker]), rtsp_timeout=4.0)
    loop = asyncio.get_running_loop()
    frames = OrderedDict()
    raw_predictions = {}
    records, events, target_rows, fixed_crops, previews = [], [], [], [], []
    started = None
    anchor = None
    target_id = None

    def event(kind, **fields):
        events.append({"time": time.monotonic(), "kind": kind, **fields})
        if kind in ("rtsp_error", "decoder_error", "yolo_error", "classifier_state"):
            print(json.dumps({"kind": kind, **fields}), flush=True)

    def on_frame(frame):
        if not (directory/"source_first.jpg").exists():
            cv2.imwrite(str(directory/"source_first.jpg"), frame.image)
        frames[(frame.generation, frame.pts90k)] = frame.image
        while len(frames) > 24:
            frames.popitem(last=False)
        worker.submit(frame)

    def on_result(result):
        nonlocal started, anchor, target_id
        now = time.monotonic()
        image = frames.get((result["generation"], result["pts90k"]))
        if started is None:
            # Exclude a stale first result produced during TensorRT warm-up.
            if image is None:
                return
            started = now
            print(f"Measurement started: {seconds:g} seconds of live source results", flush=True)
        if now-started > seconds:
            return
        result = dict(result, sampleSeconds=round(now-started, 6),
                      rawDetections=raw_predictions.pop((result["generation"], result["pts90k"]), []))
        records.append(result)
        boxes = result["boxes"]
        if anchor is None and image is not None and boxes:
            def in_region(box):
                x, y = box["center_x"]/result["width"], box["center_y"]/result["height"]
                return (x < 0.25 and y > 0.55 if target_region == "lower-left" else
                        0.2 <= x <= 0.8 and y <= 0.55)

            candidates = [box for box in boxes if box.get("detector_label") == "military_car"
                          and in_region(box)]
            if not candidates:
                candidates = [box for box in boxes if in_region(box)]
            if candidates:
                aim_x, aim_y = (0.1, 0.85) if target_region == "lower-left" else (0.5, 0.25)
                best = min(candidates, key=lambda box:
                           abs(box["center_x"]/result["width"]-aim_x) +
                           0.5*abs(box["center_y"]/result["height"]-aim_y))
                anchor, target_id = dict(best), best["track_id"]
                overview = image.copy()
                for box in boxes:
                    color = (0, 255, 255) if box["track_id"] == target_id else (0, 220, 0)
                    p1 = (int(box["x1"]), int(box["y1"]))
                    p2 = (int(box["x2"]), int(box["y2"]))
                    cv2.rectangle(overview, p1, p2, color, 2)
                    cv2.putText(overview, f'ID {box["track_id"]} {box["label"]}',
                                (p1[0], max(20, p1[1]-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.imwrite(str(directory/"overview.jpg"), overview)
                print(f"Selected {target_region} target: ID {target_id}", flush=True)
        if anchor is None:
            return
        target = next((box for box in boxes if box["track_id"] == target_id), None)
        if target is None and boxes:
            nearest = min(boxes, key=lambda box: math.hypot(
                box["center_x"]-anchor["center_x"], box["center_y"]-anchor["center_y"]))
            if math.hypot(nearest["center_x"]-anchor["center_x"],
                          nearest["center_y"]-anchor["center_y"]) <= 50:
                target, target_id = nearest, nearest["track_id"]
        row = {"t": result["sampleSeconds"], "pts": result["ptsSeconds"],
               "generation": result["generation"], "box": target}
        target_rows.append(row)
        if image is not None:
            if target is not None:
                fixed_crops.append(crop(image, anchor))
                previews.append((row["t"], crop(image, target), target.get("classifier_raw_index"),
                                 target.get("classifier_index")))

    worker = InferenceWorker(config, loop, on_result, event)
    original_process, original_predict = worker._process, worker.model.predict

    def process_with_frame(frame):
        worker.probe_frame = frame
        return original_process(frame)

    def predict_with_raw(image, *args, **kwargs):
        results = original_predict(image, *args, **kwargs)
        result = results[0]
        raw = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            raw.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "center_x": (x1+x2)/2, "center_y": (y1+y2)/2,
                        "label": str(result.names[int(box.cls[0])]),
                        "confidence": float(box.conf[0])})
        frame = worker.probe_frame
        raw_predictions[(frame.generation, frame.pts90k)] = raw
        return results

    worker._process, worker.model.predict = process_with_frame, predict_with_raw
    source = None
    try:
        source = RtspSource(config, loop,
                            lambda frame: loop.call_soon_threadsafe(on_frame, frame), event)
        timeout = time.monotonic()+40
        while started is None and time.monotonic() < timeout:
            await asyncio.sleep(0.05)
        if started is None:
            raise RuntimeError(f"No inference results; source={source.status()}, inference={worker.status()}")
        while time.monotonic()-started < seconds:
            await asyncio.sleep(0.05)
        measured_source_status = source.status()
        measured_worker_status = worker.status()
        source.running = False
        if source._pipeline is not None:
            source._pipeline.send_event(source.Gst.Event.new_eos())
        # Stop new inference jobs; finish the current crop before controlled comparisons.
        await asyncio.to_thread(worker.close)
        await asyncio.to_thread(source.close)
        source = None
        labels = worker.classifier.settings["labels"] if worker.classifier.settings else []
        real = [row for row in target_rows if row["box"] is not None]
        classified = [row for row in real if "classifier_raw_index" in row["box"]]
        raw = [row["box"]["classifier_raw_index"] for row in classified]
        displayed = [row["box"]["classifier_index"] for row in classified]
        fixed = []
        diagnostic_dynamic = []
        if worker.classifier.runner is not None:
            for image in fixed_crops:
                fixed.append(worker.classifier.runner.predict(image).tolist())
            diagnostic = ClassificationManager(config.classifier_model_path, config.classifier_config,
                                               history_size=config.classifier_history)
            diagnostic.runner, diagnostic.settings = worker.classifier.runner, worker.classifier.settings
            diagnostic.state = "ready"
            for t, image, _, _ in previews:
                h, w = image.shape[:2]
                box = {"x1": 0, "y1": 0, "x2": w, "y2": h, "track_id": 0,
                       "observed": True, "label": "military_car"}
                diagnostic.update([box], image, {0})
                diagnostic_dynamic.append({"t": t, "box": box})
            previews[:] = [(item["t"], preview[1], item["box"]["classifier_raw_index"],
                            item["box"]["classifier_index"])
                           for item, preview in zip(diagnostic_dynamic, previews)]
        fixed_indexes = [int(np.argmax(scores)) for scores in fixed]
        deterministic = []
        if fixed_crops and worker.classifier.runner is not None:
            deterministic = [worker.classifier.runner.predict(fixed_crops[0]).tolist()
                             for _ in range(5)]
        if previews:
            indexes = np.linspace(0, len(previews)-1, min(12, len(previews)), dtype=int)
            tiles = []
            for index in indexes:
                t, image, raw_index, shown_index = previews[index]
                image = cv2.resize(image, (240, 150))
                tile = np.zeros((190, 240, 3), dtype=np.uint8)
                tile[:150] = image
                cv2.putText(tile, f"{t:.2f}s raw={raw_index} shown={shown_index}", (5, 176),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                tiles.append(tile)
            while len(tiles) % 4:
                tiles.append(np.zeros_like(tiles[0]))
            sheet = np.vstack([np.hstack(tiles[i:i+4]) for i in range(0, len(tiles), 4)])
            cv2.imwrite(str(directory/"target_crops.jpg"), sheet)
        boxes = [row["box"] for row in real]
        dimensions = [[box["x2"]-box["x1"], box["y2"]-box["y1"]] for box in boxes]
        summary = {"directory": str(directory), "seconds": seconds,
                   "tracker": tracker, "target_region": target_region,
                   "source_pts_span": records[-1]["ptsSeconds"]-records[0]["ptsSeconds"] if records else 0,
                   "inference_results": len(records), "target_anchor": anchor,
                   "labels": labels, "target_observed": len(real),
                   "target_missing": len(target_rows)-len(real),
                   "target_track_ids": sorted({box["track_id"] for box in boxes}),
                   "detector_labels": dict(Counter(box.get("detector_label") for box in boxes)),
                   "raw_counts": dict(Counter(labels[index] for index in raw)),
                   "display_counts": dict(Counter(labels[index] for index in displayed)),
                   "raw_switches": changes(raw), "display_switches": changes(displayed),
                   "diagnostic_raw_counts": dict(Counter(labels[item["box"]["classifier_raw_index"]]
                       for item in diagnostic_dynamic)),
                   "diagnostic_display_counts": dict(Counter(labels[item["box"]["classifier_index"]]
                       for item in diagnostic_dynamic)),
                   "diagnostic_raw_switches": changes([item["box"]["classifier_raw_index"]
                       for item in diagnostic_dynamic]),
                   "diagnostic_display_switches": changes([item["box"]["classifier_index"]
                       for item in diagnostic_dynamic]),
                   "fixed_crop_counts": dict(Counter(labels[index] for index in fixed_indexes)),
                   "fixed_crop_switches": changes(fixed_indexes),
                   "same_image_repeat_max_difference": float(np.max(np.ptp(np.array(deterministic), axis=0)))
                       if deterministic else None,
                   "bbox_dimensions_min": np.min(dimensions, axis=0).tolist() if dimensions else None,
                   "bbox_dimensions_max": np.max(dimensions, axis=0).tolist() if dimensions else None,
                   "source_status": measured_source_status, "inference_status": measured_worker_status}
        for name, data in (("summary.json", summary), ("target.json", target_rows),
                           ("fixed_crop_scores.json", fixed),
                           ("diagnostic_dynamic.json", diagnostic_dynamic), ("events.json", events)):
            (directory/name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        (directory/"detections.jsonl").write_text("".join(
            json.dumps(row, ensure_ascii=False)+"\n" for row in records))
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if anchor is None:
            raise RuntimeError(f"No target was detected in the {target_region} region")
    finally:
        if source is not None:
            await asyncio.to_thread(source.close)
        if worker.running:
            await asyncio.to_thread(worker.close)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--tracker", choices=("legacy", "bytetrack"), default="legacy")
    parser.add_argument("--target-region", choices=("center-upper", "lower-left"), default="center-upper")
    args = parser.parse_args()
    if not 0 < args.seconds <= 30:
        parser.error("seconds must be between 0 and 30")
    asyncio.run(measure(args.seconds, args.tracker, args.target_region))
