"""Replay legacy on the same low-threshold detections as the live ByteTrack measurement."""

from collections import Counter
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/cls_live_matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rtsp_yolo_direct_cls.tracking import TargetTracker


directory = Path(sys.argv[1])
records = [json.loads(line) for line in (directory/"detections.jsonl").read_text().splitlines()]
summary = json.loads((directory/"summary.json").read_text())
duration = summary["seconds"]
legacy_tracker = TargetTracker(hold_seconds=0.5)
observations = []


def select(boxes, width, height):
    candidates = [box for box in boxes if box["center_x"]/width < 0.25
                  and box["center_y"]/height > 0.55]
    return min(candidates, key=lambda box: abs(box["center_x"]/width-0.1) +
               abs(box["center_y"]/height-0.85)) if candidates else None


for row in records:
    raw = row["rawDetections"]
    high = [box for box in raw if box["confidence"] >= 0.3]
    legacy_boxes = legacy_tracker.update(high, row["generation"], row["ptsSeconds"],
                                         (row["width"], row["height"]))
    arguments = row["width"], row["height"]
    observations.append({"t": row["sampleSeconds"], "pts": row["ptsSeconds"],
                         "raw": select(raw, *arguments),
                         "legacy": select(legacy_boxes, *arguments),
                         "bytetrack": select(row["boxes"], *arguments)})


def statistics(key):
    sequence = [bool(row[key]) for row in observations]
    visible = [row[key] for row in observations if row[key]]
    ids = [box["track_id"] for box in visible] if key != "raw" else []
    gaps = []
    begin = None
    for i, value in enumerate(sequence):
        if not value and begin is None:
            begin = i
        if value and begin is not None:
            gaps.append({"start": observations[begin]["t"], "end": observations[i]["t"],
                         "updates": i-begin})
            begin = None
    if begin is not None:
        gaps.append({"start": observations[begin]["t"], "end": duration,
                     "updates": len(sequence)-begin})
    return {"present": len(visible), "missing": len(sequence)-len(visible),
            "present_fraction": len(visible)/len(sequence),
            "visibility_transitions": sum(a != b for a, b in zip(sequence, sequence[1:])),
            "missing_episodes": len(gaps), "gaps": gaps,
            "longest_missing_seconds": max((item["end"]-item["start"] for item in gaps), default=0),
            "ids": sorted(set(ids)), "id_changes": sum(a != b for a, b in zip(ids, ids[1:])),
            "weak_outputs": sum(box["confidence"] < 0.3 for box in visible),
            "display_labels": dict(Counter(box["label"] for box in visible))}


comparison = {"seconds": duration, "updates": len(records),
              "method": "same YOLO detections: live ByteTrack (0.1 low, 0.3 high) vs legacy replay (0.3)",
              "raw": statistics("raw"), "legacy": statistics("legacy"),
              "bytetrack": statistics("bytetrack"),
              "byte_only_present": sum(bool(row["bytetrack"]) and not row["legacy"] for row in observations),
              "legacy_only_present": sum(bool(row["legacy"]) and not row["bytetrack"] for row in observations)}
(directory/"tracking_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2))
(directory/"tracking_frames.json").write_text(json.dumps(observations, ensure_ascii=False, indent=2))

times = [row["t"] for row in observations]
fig, axes = plt.subplots(3, 1, figsize=(12, 7.5), sharex=True,
                         gridspec_kw={"height_ratios": [1, 1, 1.6]})
for axis, key, color in ((axes[0], "legacy", "#ea580c"), (axes[1], "bytetrack", "#2563eb")):
    states = [int(bool(row[key])) for row in observations]
    axis.step(times, states, where="post", color=color, linewidth=1.2)
    axis.fill_between(times, states, step="post", alpha=0.1, color=color)
    stats = comparison[key]
    axis.set_title(f'{key}: present {stats["present"]}/{len(records)}, '
                   f'missing {stats["missing"]}, ID changes {stats["id_changes"]}')
    axis.set_yticks([0, 1], ["Missing", "Visible"])
    axis.set_ylim(-0.15, 1.15)
confidence = [row["raw"]["confidence"] if row["raw"] else np.nan for row in observations]
axes[2].plot(times, confidence, color="#444", linewidth=1, label="Raw target detection confidence")
weak = [(row["t"], row["bytetrack"]["confidence"]) for row in observations
        if row["bytetrack"] and row["bytetrack"]["confidence"] < 0.3]
if weak:
    x, y = zip(*weak)
    axes[2].scatter(x, y, s=12, color="#16a34a", label="Actual weak matches returned by ByteTrack")
rejected = [(row["t"], row["legacy"]["confidence"]) for row in observations
            if row["legacy"] and not row["bytetrack"]]
if rejected:
    x, y = zip(*rejected)
    axes[2].scatter(x, y, s=16, facecolors="none", edgecolors="#ef4444", label="High-score detection absent from ByteTrack output")
axes[2].axhline(0.3, color="#f97316", linestyle="--", linewidth=1, label="0.3 high threshold")
axes[2].axhline(0.1, color="#16a34a", linestyle=":", linewidth=1, label="0.1 low threshold")
axes[2].set_ylim(0, 1)
axes[2].set_ylabel("Detection confidence")
axes[2].set_xlabel("Seconds")
axes[2].legend(fontsize=8, loc="upper right")
for axis in axes:
    axis.set_xlim(0, duration)
    axis.grid(alpha=0.2)
fig.suptitle("Lower-left target: both trackers compared using the same measured frames")
fig.tight_layout()
fig.savefig(directory/"tracking_comparison.png", dpi=160)

legacy, byte = comparison["legacy"], comparison["bytetrack"]
report = f'''# 左下角目標：ByteTrack 與 legacy 同影格對照

資料：{directory.name}，{duration:g} 秒、{len(records)} 次推論。
ByteTrack 實際運行，YOLO 門檻 0.1，高分／新軌跡門檻 0.3。
保留同一批 YOLO NMS 後候選，再取 >=0.3 的候選回放目前 legacy TargetTracker。
這不是再拍一次影片，兩者看到的是同一批影格／同一批偵測候選。
两者均保留 ID 0.5 秒、只輸出實際匹配框，沒有預測補框。
legacy 回放只比較框與 ID，不重新執行 classifier；其 label 是偵測類別。

| 指標 | legacy 回放 | ByteTrack 實際輸出 |
| --- | ---: | ---: |
| 有框更新 | {legacy["present"]} | {byte["present"]} |
| 無框更新 | {legacy["missing"]} | {byte["missing"]} |
| 有框比例 | {legacy["present_fraction"]*100:.2f}% | {byte["present_fraction"]*100:.2f}% |
| 出現／消失切換 | {legacy["visibility_transitions"]} | {byte["visibility_transitions"]} |
| 消失段數 | {legacy["missing_episodes"]} | {byte["missing_episodes"]} |
| 最長消失 | {legacy["longest_missing_seconds"]:.3f} 秒 | {byte["longest_missing_seconds"]:.3f} 秒 |
| ID 變更 | {legacy["id_changes"]} | {byte["id_changes"]} |

ByteTrack 實際回傳 {byte["weak_outputs"]} 次低於 0.3 的低分配對框。
ByteTrack 有框而 legacy 無框的更新 {comparison["byte_only_present"]} 次；
legacy 有高分框而 ByteTrack 無輸出的更新 {comparison["legacy_only_present"]} 次。
追蹤器可延续既有低分配對，但新軌跡確認、配對失敗、lost 狀態等條件仍會限制輸出。
低門檻候選中目標實際出現 {comparison["raw"]["present"]} 次，
完全沒有 >=0.1 候選 {comparison["raw"]["missing"]} 次。

前次 legacy 30 秒（09:05）373/423 有框，而第一段 ByteTrack 30 秒（09:17）
僅 2/425 有框。這兩段不是同一批影格，不應用來單獨量化追蹤器增益。
補測 5 秒的同影格對照為 legacy 35/68、ByteTrack 38/68；
本報告再以完整 30 秒的原始候選給出較完整的公平對照。
標註畫面見 [overview.jpg](overview.jpg)，圖表見 [tracking_comparison.png](tracking_comparison.png)。
原始資料見 [detections.jsonl](detections.jsonl)、[tracking_comparison.json](tracking_comparison.json)。
正式 cls 的預設模式未修改。
'''
(directory/"tracking_report.md").write_text(report, encoding="utf-8")
print(json.dumps({key: value for key,value in comparison.items() if key not in ("raw","legacy","bytetrack")},ensure_ascii=False))
for key in ("raw", "legacy", "bytetrack"):
    print(key, json.dumps({name: value for name,value in comparison[key].items() if name!="gaps"}, ensure_ascii=False))
