"""Plot the selected target's measured probabilities and separate overlapping detections."""

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
fixed = np.array(json.loads((directory/"fixed_crop_scores.json").read_text()))
records = [json.loads(line) for line in (directory/"detections.jsonl").read_text().splitlines()]
fig, axes = plt.subplots(3, 1, figsize=(11, 8.2), sharex=True,
                         gridspec_kw={"height_ratios": [2, 1.5, 1]})
colors = ["#2563eb", "#ea580c", "#16a34a"]
names = ["CM34", "Light tactical", "Medium tactical"]
for index, (name, color) in enumerate(zip(names, colors)):
    axes[0].plot(times, scores[:, index], label=name, color=color, linewidth=1.5)
axes[0].set_title("Selected center-upper target (ID 2): raw CM34 72/72, displayed CM34 72/72")
axes[0].set_ylabel("Raw model probability")
axes[0].set_ylim(0, 0.8)
axes[0].legend(loc="upper right", ncol=3, fontsize=9)
closest = int(np.argmin(scores[:, 0]-scores[:, 1]))
axes[0].annotate(f"Smallest CM34-light gap: {(scores[closest,0]-scores[closest,1])*100:.1f} pp",
                 xy=(times[closest], scores[closest, 0]), xytext=(1.6, 0.75),
                 arrowprops={"arrowstyle": "->", "color": "#444"}, fontsize=9)
axes[1].plot(times, scores[:, 0], label="Detector crop: follows each detected box",
             color=colors[0], linewidth=1.4)
axes[1].plot(times[:len(fixed)], fixed[:, 0], label="Fixed rectangle on the same frames",
             color="#7c3aed", linewidth=1.4)
axes[1].set_ylabel("CM34 probability")
axes[1].set_ylim(0.45, 0.76)
axes[1].legend(loc="upper right", fontsize=9)
for identity, marker, color in ((4, "o", "#ef4444"), (5, "s", "#a855f7")):
    other = [(row["sampleSeconds"], box["classifier_index"])
             for row in records for box in row["boxes"]
             if box["track_id"] == identity and "classifier_index" in box]
    if other:
        x, y = zip(*other)
        axes[2].scatter(x, y, label=f"Separate lower box ID {identity}",
                        marker=marker, color=color, s=15)
axes[2].set_yticks([1, 2], ["Light", "Medium"])
axes[2].set_ylim(0.7, 2.3)
axes[2].set_xlabel("Seconds after measurement start")
axes[2].legend(loc="upper right", fontsize=9)
for axis in axes:
    axis.grid(alpha=0.2)
    axis.set_xlim(0, 5)
fig.tight_layout()
fig.savefig(directory/"analysis.png", dpi=160)

report = """# 中上方目標的 5 秒分類短測

採用換好畫面後的 2026-10-13 08:58:14 測試，先前放錯畫面的資料不納入。
使用目前 cls.4 的 test3.engine、classifier_fp16.engine、legacy tracking、
最近五次等權重多數決；未啟動網頁服務或 GPS。TensorRT 暖機結果不納入採樣。
實際來源 PTS 跨度 4.9716 秒，共 72 次推論。

## 選取目標

中上方車輛為 ID 2，位置約 (426,126)，圖片大小 960×544。
見 [overview.jpg](overview.jpg) 的黃色框。此框 72 次都被偵測為 military_car，
沒有漏檢、沒有更換 ID。

| 指標 | CM34 | 輕型 | 中型 |
| --- | ---: | ---: | ---: |
| 原始最高分類別次數 | 72 | 0 | 0 |
| 多數決顯示次數 | 72 | 0 | 0 |
| 原始模型平均機率 | 60.65% | 36.46% | 2.89% |
| 原始模型機率範圍 | 50.86～70.99% | 26.17～46.00% | 2.01～3.68% |

這 5 秒未重現 CM34／輕型切換：原始與顯示分類均切換 0 次。
因此這次沒有發現多數決把正確 CM34 隱藏的情況。
投票比例 100% 是最近投票皆選 CM34，不代表模型原始機率為 100%。

## 輸入敏感度對照

固定同一裁切影像重跑五次，三類機率的最大差異為 0。
同一組即時影格改用固定位置／尺寸裁切，仍全部判 CM34。
動態偵測框的 CM34 機率跨度約 20.13 個百分點；固定裁切為 8.61 個百分點。
偵測框寬度 471.5～478.5 px，高度 224.25～246.5 px。
這支持裁切範圍會影響分數，且固定框仍有影像本身的變化；
由於未觀察到類別切換，不能據此確認先前跳動的成因。

## 另一個重疊框

畫面中間偏下另有較大的框（ID 4，後來 ID 5），框住電線／前景器材附近，
看起來可能是偵測誤框。它由 YOLO 實際輸出，不是追蹤補出的預測框。
這兩個 ID 的偵測信心約 0.30～0.45，共輸出 49 次，
顯示輕型 29 次、中型 20 次，合併的顯示序列切換 8 次。
它與 ID 2 的交集約占上方車輛框面積的 11.3～20.9%，
且其文字標籤會靠近上方車輛，可能造成同一台車在變類別的視覺混淆。
這是由此次畫面與記錄作出的可能解釋，不是先前跳動已被重現的證明。

## 建議

此短測的中上方目標分類穩定，先保留目前五次多數決。
先確認中間偏下的低信心重疊框是否為誤檢，再決定是否調整偵測處理。
短測不能保證換角度、距離或更長時間仍不切換；類別順序與前處理仍需與訓練端核對。

圖表見 [analysis.png](analysis.png)，裁切影像見 [target_crops.jpg](target_crops.jpg)。
原始記錄見 [detections.jsonl](detections.jsonl)、[target.json](target.json)、
[summary.json](summary.json)。diagnostic_dynamic.json 是停止串流後的同圖獨立分類對照，
不混入正式分支的原始／顯示統計。
"""
(directory/"report.md").write_text(report, encoding="utf-8")
print(json.dumps({"report": str(directory/"report.md"),
                  "plot": str(directory/"analysis.png")}, ensure_ascii=False))
