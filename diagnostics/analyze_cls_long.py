"""Analyze a completed live classification measurement with data-derived summaries."""

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


directory = Path(sys.argv[1])
summary = json.loads((directory/"summary.json").read_text())
rows = json.loads((directory/"target.json").read_text())
valid = [row for row in rows if row["box"] and "classifier_raw_probs" in row["box"]]
times = np.array([row["t"] for row in valid])
scores = np.array([row["box"]["classifier_raw_probs"] for row in valid])
raw = np.array([row["box"]["classifier_raw_index"] for row in valid])
displayed = np.array([row["box"]["classifier_index"] for row in valid])
labels = summary["labels"]
cm, light = labels.index("cm34"), labels.index("light_tactical")
fixed = np.array(json.loads((directory/"fixed_crop_scores.json").read_text()))
diagnostic = json.loads((directory/"diagnostic_dynamic.json").read_text())
fixed_times = np.array([row["t"] for row in diagnostic])
duration = summary["seconds"]
anchor = summary["target_anchor"]
records = [json.loads(line) for line in (directory/"detections.jsonl").read_text().splitlines()]
target_ids = summary["target_track_ids"]


def episodes(sequence):
    result = []
    start = 0
    for end in range(1, len(sequence)+1):
        if end == len(sequence) or sequence[end] != sequence[start]:
            if sequence[start] != cm:
                stop = float(times[end]) if end < len(sequence) else duration
                result.append({"label": labels[int(sequence[start])], "start": float(times[start]),
                               "end": stop, "duration": stop-float(times[start]), "count": end-start})
            start = end
    return result


raw_episodes, display_episodes = episodes(raw), episodes(displayed)
others = [(row["sampleSeconds"], box) for row in records for box in row["boxes"]
          if box["track_id"] not in target_ids and "classifier_index" in box
          and abs(box["center_x"]-anchor["center_x"]) <= max(100, (anchor["x2"]-anchor["x1"])/2)
          and box["center_y"] > anchor["center_y"]+max(20, (anchor["y2"]-anchor["y1"])/4)]
other_ids = sorted({box["track_id"] for _, box in others})
analysis = {"samples": len(valid), "raw_episodes": raw_episodes,
            "display_episodes": display_episodes,
            "raw_probability_min": scores.min(0).tolist(),
            "raw_probability_mean": scores.mean(0).tolist(),
            "raw_probability_max": scores.max(0).tolist(),
            "fixed_probability_min": fixed.min(0).tolist(),
            "fixed_probability_mean": fixed.mean(0).tolist(),
            "fixed_probability_max": fixed.max(0).tolist(),
            "raw_cm34_but_display_other": int(np.sum((raw == cm) & (displayed != cm))),
            "raw_other_but_display_cm34": int(np.sum((raw != cm) & (displayed == cm))),
            "other_ids": other_ids,
            "other_display_counts": dict(Counter(box["label"] for _, box in others))}
(directory/"analysis_stats.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2))

fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                         gridspec_kw={"height_ratios": [2, 1.3, 1.5]})
colors = ["#2563eb", "#ea580c", "#16a34a"]
names = {"cm34": "CM34", "light_tactical": "Light tactical", "medium_tactical": "Medium tactical"}
for index, label in enumerate(labels):
    axes[0].plot(times, scores[:, index], label=names.get(label, label),
                 color=colors[index], linewidth=1.1)
for episode in display_episodes:
    axes[0].axvspan(episode["start"], episode["end"], color="#ef4444", alpha=0.16)
axes[0].set_title(f'{duration:g}s center-upper target (ID {",".join(map(str,target_ids))}): '
                  f'raw CM34 {summary["raw_counts"].get("cm34",0)}/{len(valid)}, '
                  f'displayed CM34 {summary["display_counts"].get("cm34",0)}/{len(valid)}')
axes[0].set_ylabel("Raw model probability")
axes[0].set_ylim(0, 1)
axes[0].legend(loc="upper right", ncol=3, fontsize=9)
axes[1].scatter(times, raw, s=10, label="Raw class", color="#fb923c", alpha=0.8)
axes[1].step(times, displayed, where="post", linewidth=1.6, label="5-vote displayed class", color="#2563eb")
axes[1].set_yticks(range(len(labels)), [names.get(label, label) for label in labels])
axes[1].set_ylim(-0.2, len(labels)-0.8)
axes[1].legend(loc="upper right", fontsize=9)
axes[1].set_ylabel("Class index")
axes[2].plot(times, scores[:, cm], label="Current detector crop", color="#2563eb", linewidth=1)
axes[2].plot(fixed_times, fixed[:, cm], label="Fixed rectangle on the same frames", color="#7c3aed", linewidth=1)
axes[2].set_ylabel("CM34 probability")
axes[2].legend(loc="upper right", fontsize=9)
axes[2].set_ylim(max(0, min(scores[:,cm].min(),fixed[:,cm].min())-0.04),
                 min(1, max(scores[:,cm].max(),fixed[:,cm].max())+0.06))
axes[2].set_xlabel("Seconds after measurement start")
for axis in axes:
    axis.grid(alpha=0.2)
    axis.set_xlim(0, duration)
fig.tight_layout()
fig.savefig(directory/"analysis.png", dpi=160)

fig2, axes2 = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
axes2[0].plot(times, scores[:,cm], label="CM34", color=colors[cm], marker=".")
axes2[0].plot(times, scores[:,light], label="Light tactical", color=colors[light], marker=".")
axes2[0].legend()
axes2[0].set_ylabel("Raw probability")
axes2[1].step(times, raw, where="post", label="Raw class", color="#ea580c")
axes2[1].step(times, displayed, where="post", label="Displayed class", color="#2563eb")
axes2[1].set_yticks([cm, light], ["CM34", "Light"])
axes2[1].legend()
axes2[1].set_xlabel("Seconds")
for axis in axes2:
    axis.grid(alpha=0.2)
    if display_episodes:
        axis.set_xlim(max(0,display_episodes[0]["start"]-0.5), min(duration,display_episodes[0]["end"]+0.5))
fig2.suptitle("Short class change and return: majority voting introduces a small delay")
fig2.tight_layout()
fig2.savefig(directory/"switch_detail.png", dpi=160)

means = scores.mean(0)
rows_table = "\n".join(f'| {names.get(label,label)} | {summary["raw_counts"].get(label,0)} | '
                       f'{summary["display_counts"].get(label,0)} | {means[i]*100:.2f}% |'
                       for i,label in enumerate(labels))
episode_text = "\n".join(f'- {entry["start"]:.3f}～{entry["end"]:.3f} 秒：{entry["label"]}，'
                         f'{entry["count"]} 次更新，約 {entry["duration"]:.3f} 秒。'
                         for entry in display_episodes) or '- 無其他類別顯示時段。'
report = f'''# 中上方目標 {duration:g} 秒分類測試

測試資料夾：{directory.name}。來源 PTS 跨度 {summary["source_pts_span"]:.3f} 秒，
共 {summary["inference_results"]} 次推論；目標實際出現 {summary["target_observed"]} 次，
漏檢 {summary["target_missing"]} 次，追蹤 ID 為 {target_ids}。
使用 test3.engine、classifier_fp16.engine、legacy tracking、最近五次等權重多數決。
只做獨立短測，沒有啟動 HTTP/WebRTC/GPS，TensorRT 暖機舊結果不納入。

## 分類結果

| 類別 | 原始最高分類別次數 | 多數決顯示次數 | 原始平均機率 |
| --- | ---: | ---: | ---: |
{rows_table}

原始分類切換 {summary["raw_switches"]} 次，多數決後切換 {summary["display_switches"]} 次。
實際顯示其他類別的時段：

{episode_text}

原始 CM34 機率 {scores[:,cm].min()*100:.2f}～{scores[:,cm].max()*100:.2f}%；
輕型機率 {scores[:,light].min()*100:.2f}～{scores[:,light].max()*100:.2f}%。
原始已回到 CM34 但投票仍顯示其他類別的更新有 {analysis["raw_cm34_but_display_other"]} 次；
原始為其他類別而投票維持 CM34 的更新有 {analysis["raw_other_but_display_cm34"]} 次。
因此投票確實减少瞬間跳動，也帶來少量恢復延遲；沒有因投票把偵測框刪除。

## 固定裁切對照

同一批 {len(fixed)} 個影格使用第一個實際偵測框的固定位置／尺寸裁切，
結果為 {summary["fixed_crop_counts"]}，切換 {summary["fixed_crop_switches"]} 次。
固定裁切只是診斷對照，不是部署行為。
同一張裁切影像重跑五次，最大機率差異 {summary["same_image_repeat_max_difference"]}。
動態框 CM34 機率跨度 {(scores[:,cm].max()-scores[:,cm].min())*100:.2f} 個百分點，
固定框跨度 {(fixed[:,cm].max()-fixed[:,cm].min())*100:.2f} 個百分點。
偵測框寬度 {summary["bbox_dimensions_min"][0]:.2f}～{summary["bbox_dimensions_max"][0]:.2f} px，
高度 {summary["bbox_dimensions_min"][1]:.2f}～{summary["bbox_dimensions_max"][1]:.2f} px。
同一物體同一影格換成固定裁切後分類較穩定，支持裁切範圍浮動是這次分類跳動的重要因素。
影像、壓縮與模型本身仍會影響分數，不能據此保證換角度／移動後的分類準確率。

## 其他中央偏下的框

另外分開統計中央偏下的偵測框，ID 包含 {other_ids}，
顯示次數為 {analysis["other_display_counts"]}。它們不混入上方目標的統計。
標註画面中的此區主要是前景設備／電線附近，需要另外確認是否偵測誤框。

## 建議

先保留目前五次多數決。下一步可針對 classifier 的裁切框做輕度平滑、
跟著實際目標更新，優先降低微小框變動造成的輸入差異。
本次固定裁切只適合靜止對照，不建議把分類框永久固定在畫面座標上。
本次沒有修改正式串流的裁切、投票或偵測門檻；類別順序與前處理仍待訓練端核對。

[完整機率圖](analysis.png) · [切換細節](switch_detail.png) ·
[標註畫面](overview.jpg) · [裁切影像](target_crops.jpg) · [統計資料](analysis_stats.json)
'''
(directory/"report.md").write_text(report, encoding="utf-8")
print(json.dumps(analysis, ensure_ascii=False, indent=2))
