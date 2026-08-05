# 工業相機 MJPEG／WebRTC／WebRTC VIC 效能報告

測試日期：2026-08-05（Asia/Taipei）  
平台：NVIDIA Jetson Orin NX、Jetson Linux R36.5.0、Python 3.10.12  
相機：The Imaging Source DFK AFU130-L53，serial `26410280`  
模型：`yolo11s.engine`（TensorRT）

## 結論

工業相機已被 Linux V4L2、tiscamera 及實際三支應用程式成功偵測和取像。

三組共同使用 `1920×1080 @ 30 FPS`。WebRTC VIC 版本是三者中較適合作為正式方向的版本：相較一般 WebRTC 軟體色彩轉換路徑，server CPU 平均由 254.94% 降至 207.28%，降低 **18.7%**；client 接收間隔 P95 由 57.27 ms 改善至 43.76 ms。

但目前 WebRTC 的接收 FPS 仍受既有的「協商後追趕」與重複最新 YOLO frame 影響，32.77 FPS 不能當成新的 YOLO 結果 FPS。若要判斷 VIC 是否提高真正推論更新率，程式必須加入 capture `frame_id` 和各階段 timestamp。

| 指標 | MJPEG 軟體 | WebRTC 軟體 | WebRTC VIC HW |
|---|---:|---:|---:|
| 輸入／輸出解析度 | 1920×1080 | 1920×1080 | 1920×1080 |
| Client 收到 FPS | 15.38 | 26.70* | 32.77* |
| Client 幀間隔平均 | 65.02 ms | 37.45 ms* | 30.51 ms* |
| Client 幀間隔 P95 | 72.78 ms | 57.27 ms* | 43.76 ms* |
| Server CPU 平均 | 157.71% | 254.94% | **207.28%** |
| Server CPU P95 | 170.7% | 297.9% | **262.9%** |
| Server RSS | 1332.64 MiB | **1532.60 MiB** | 1577.66 MiB |
| 網路流量 | 49.84 Mb/s | **0.569 Mb/s** | 0.795 Mb/s |
| 封包遺失（localhost） | 不適用 | 0 / 899 | 0 / 987 |
| WebRTC offer 至首幀 | 不適用 | 10.291 s | 10.237 s |

\* WebRTC 指標包含排程追趕及重複最新 frame，不能解讀成 unique camera/YOLO FPS。

## 工業相機偵測結果

```text
Model: DFK AFU130-L53
Serial: 26410280
Driver: uvcvideo
Bus: usb-3610000.usb-1.1
Video node: /dev/video0
Metadata node: /dev/video1
tcambin: 0.14.0_master/031c7762_rev_3054
```

`/dev/video1` 是 UVC payload metadata，不應當作影像來源。

### 支援格式

相機只列出未壓縮 `YUYV 4:2:2`：

| 解析度 | 可用 FPS |
|---|---|
| 4128×3096 | 1 |
| 3264×2448 | 1 |
| 2592×1944 | 1 |
| 1920×1080 | 30、25、20、15、10、5 |
| 1600×1200 | 30、25、20、15、10、5 |
| 1280×960 | 30、25、20、15、10、5 |
| 1280×720 | 30、25、20、15、10、5 |
| 800×480 | 30、25、20、15、10、5 |
| 640×480 | 30、25、20、15、10、5 |

裝置初次查詢時顯示 `4128×3096 @ 30 FPS`，但完整 format enumeration 明確指出該解析度只有 1 FPS。驅動當下的 FPS 欄位不能單獨當成格式能力；真正測試應以完整 caps 與實際到幀時間為準。

這與先前 webcam 很不同：webcam 的 1080p/30 輸入是壓縮 MJPEG；工業相機的 1080p/30 是未壓縮 YUYV，原始資料率約為：

```text
1920 × 1080 × 2 bytes × 30 ≈ 124.4 MB/s ≈ 995 Mb/s
```

所以換工業相機後，USB、記憶體搬移與色彩轉換的成本大幅增加。

## 實際 pipeline

### `mjpeg_yolo_minimal.py`

```text
tcambin YUYV
→ tcambin 輸出 BGRx
→ videoconvert（CPU）轉 BGR
→ NumPy copy
→ YOLO TensorRT
→ plot
→ cv2 JPEG 編碼
→ HTTP multipart
```

啟動命令：

```bash
python mjpeg_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

### `webrtc_yolo_minimal.py`

```text
tcambin YUYV
→ tcambin 輸出 BGRx
→ videoconvert（CPU）轉 BGR
→ NumPy copy
→ YOLO TensorRT 背景 producer
→ 最新 frame
→ aiortc/PyAV 視訊編碼
→ RTP
```

啟動命令：

```bash
python webrtc_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

### `webrtc_yolo_minimal_hw.py`

```text
tcambin YUY2
→ nvvidconv compute-hw=2（Jetson VIC）轉 BGRx
→ NumPy 移除 X channel 並 copy 成 BGR
→ YOLO TensorRT 背景 producer
→ 最新 frame
→ aiortc/PyAV 視訊編碼
→ RTP
```

啟動命令：

```bash
python webrtc_yolo_minimal_hw.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

實測 pipeline 成功進入 PLAYING，沒有退回 OpenCV 或軟體 `videoconvert`。

## 詳細測試結果

### MJPEG 軟體路徑

暖機 60 幀後統計 300 幀，共 19.442 秒：

| 指標 | 結果 |
|---|---:|
| FPS | 15.379 |
| 幀間隔平均／P95 | 65.024 / 72.781 ms |
| JPEG 平均／P95 | 394.253 / 437.998 KiB |
| payload bitrate | 49.836 Mb/s |
| server CPU 平均／P95 | 157.713 / 170.7% |
| server RSS | 1332.638 MiB |

本次場景的 JPEG 比先前 webcam 測試更大，因此 MJPEG 頻寬從約 38.55 增至 49.84 Mb/s。JPEG 大小會隨場景、雜訊、曝光與 gain 改變，不是相機固定常數。

`tegrastats` 在真正 client 負載期間約 7.4～7.7 W，最高 junction 約 52°C。測試也發現 tiscamera/MJPEG 流程有一個 CPU core 長時間 100%；client 中斷後仍曾持續，需進一步確認 Flask generator 是否立即收到斷線，以及 tcambin/控制執行緒的行為。

### WebRTC 軟體色彩轉換

暖機 60 幀後統計 300 個 client decode frame：

| 指標 | 結果 |
|---|---:|
| Client FPS | 26.701* |
| 幀間隔平均／P95 | 37.452 / 57.272 ms* |
| server CPU 平均／P95 | 254.936 / 297.9% |
| server RSS | 1532.595 MiB |
| loopback RX bitrate | 0.569 Mb/s |
| RTP packets received/lost | 899 / 0 |
| offer 至首幀 | 10290.965 ms |

### WebRTC VIC 硬體色彩轉換

暖機 60 幀後統計 300 個 client decode frame：

| 指標 | 結果 |
|---|---:|
| Client FPS | 32.771* |
| 幀間隔平均／P95 | 30.515 / 43.759 ms* |
| server CPU 平均／P95 | 207.275 / 262.9% |
| server RSS | 1577.660 MiB |
| loopback RX bitrate | 0.795 Mb/s |
| RTP packets received/lost | 987 / 0 |
| offer 至首幀 | 10236.621 ms |

VIC 路徑降低 server CPU，但 RSS 比軟體路徑多約 45 MiB。本次 bitrate 較高不代表 VIC 必然增加 bitrate；視訊 codec 會依畫面內容和當下 rate control 改變，兩個短測片段不能作為畫質／bitrate A/B 結論。

VIC WebRTC 無 client 時整機約 6.95～7.23 W；本機 client 真正開始編碼與解碼後約 8.5～8.6 W，最高 junction 約 54.1°C。連線值包含同一台 Jetson 上的 client 解碼成本，不能視為純 server 遠端收流功耗。

## 與先前 webcam 的主要差異

| 項目 | Webcam | DFK AFU130-L53 |
|---|---|---|
| 1080p/30 輸入 | MJPEG | YUYV 4:2:2 |
| 相機到 host 資料 | 壓縮 | 約 995 Mb/s 未壓縮 |
| OpenCV/tiscamera 成本 | JPEG decode | raw 色彩轉換＋大流量 copy |
| JPEG decode 警告 | 持續出現 corrupt JPEG warning | 本次沒有該 JPEG warning |
| MJPEG server CPU | 約 64.6% | 約 157.7% |
| MJPEG FPS | 約 13.74 | 約 15.38 |

工業相機的 MJPEG server FPS略高，但 CPU 大幅增加；原因不能只由 FPS 判斷，YUYV 輸入讓 CPU 色彩轉換與記憶體搬移變重，而相機到幀節奏也不同。

## 測試限制

- localhost 排除了實際 LAN/Wi-Fi packet loss、jitter、NAT 和 TURN。
- WebRTC client 與 server 在同一台 Jetson；系統功耗包含 client decode。
- 每組是短時間單次測試，尚未建立重複試驗的信賴區間。
- 畫面內容並未使用固定錄製素材，因此不能嚴格比較 codec 畫質與 bitrate。
- 沒有高速相機／LED timecode，未量 glass-to-glass latency。
- WebRTC 現有排程 bug 會在協商後追趕，且 sender 可能重複最新 YOLO frame。
- 未量 4128×3096，因相機在此解析度只支援 1 FPS，且三支程式固定要求 1080p/30。
- 未長時間壓力測試 USB drop、溫度穩態與記憶體洩漏。

## 下一步優先事項

1. 在 capture 時加入單調遞增 `frame_id`，記錄 capture、YOLO complete、send、client decode/render timestamp；分開計算 capture FPS、unique YOLO FPS 和 transport FPS。
2. 修正 `CameraVideoTrack` 的起始時基，連線後不要 burst catch-up。
3. 用另一台實體電腦作 WebRTC client，測純 Jetson server 功耗及 LAN glass-to-glass latency。
4. 固定場景與相機曝光、gain、white balance，再各跑 5 次、每次至少 5 分鐘。
5. 進行 30～60 分鐘 soak test，記錄 USB/UVC error、capture failure、RTP loss、RSS、溫度與降頻。
6. 目前 HW 只加速 YUY2→BGRx；WebRTC encoder 仍是 aiortc/PyAV 軟體編碼。下一個最大 CPU 優化點是整合 Jetson 硬體 H.264 encoder。
7. 確認 BGRx→BGR copy 是否能藉由模型 preprocess 或 CUDA buffer path 減少一次 1080p 記憶體複製。
8. 多 viewer 前先限制連線數或導入共享 encoder/SFU；每個 WebRTC peer 目前仍有獨立視訊 encoder。

## 建議選擇

- 除錯、單 viewer、需要直接 JPEG：可用 MJPEG，但約 50 Mb/s，且 server CPU 約 158%。
- 一般遠端顯示：WebRTC 明顯節省頻寬。
- 這台工業相機的正式方向：**`webrtc_yolo_minimal_hw.py` 的 VIC 相機路徑，再加 Jetson 硬體 H.264 encoder**。

目前可以確定的實測結論是：**VIC 路徑確實運作，並將相同工業相機 WebRTC 測試的 server CPU 平均降低約 18.7%；但 WebRTC FPS 在修正 frame ID 與追趕排程前不可當成真正 YOLO 效能。**
