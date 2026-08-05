# Current Status

更新日期：2026-08-05

## 目前基準

- 平台：NVIDIA Jetson Orin NX，aarch64
- 系統：Jetson Linux R36.5.0／Linux 5.15 tegra
- Python：3.10.12，環境位於 `.venv`
- 工業相機：The Imaging Source DFK AFU130-L53
- 相機序號：`26410280`
- tiscamera／tcambin：0.14.0
- GStreamer：1.20.3

主要模型：

- Minimal：`yolo11s.engine`
- Final：`11s_car_544_960.engine`
- Final 推論尺寸：544×960
- 預設相機設定：1920×1080 @ 30 FPS

TensorRT engine 與 JetPack、TensorRT 版本及硬體綁定，不視為跨平台
可直接使用的模型檔。

## 可用入口

| 程式 | 傳輸 | GPS | 相機轉換 |
|---|---|---:|---|
| `mjpeg_yolo_minimal.py` | MJPEG | 無 | OpenCV／tcambin 軟體路徑 |
| `webrtc_yolo_minimal.py` | WebRTC | 無 | OpenCV／tcambin 軟體路徑 |
| `webrtc_yolo_minimal_hw.py` | WebRTC | 無 | GStreamer／tcambin 使用 VIC |
| `yolo_final.py` | WebRTC | 有 | 軟體路徑 |
| `yolo_final_mjpeg.py` | MJPEG | 有 | 軟體路徑 |
| `yolo_final_hw.py` | WebRTC | 有 | GStreamer／tcambin 使用 VIC |

三個 final 共用 YOLO、GPS、連續幀確認、控制 GUI及截圖核心。
`yolo_final_hw.py` 只替換相機轉換層；選擇 OpenCV backend 時仍不使用
VIC。目前沒有 MJPEG + VIC 的 final 入口。

目前建議的工業相機正式入口：

```bash
python yolo_final_hw.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

此 HW 入口只有相機輸入的 YUY2→BGRx 使用 Jetson VIC。WebRTC 輸出仍
由 aiortc/PyAV 軟體編碼，尚未使用 Jetson `nvv4l2h264enc`。

## 已完成功能

### 相機與控制

- V4L2/OpenCV、GStreamer/v4l2src、tiscamera/tcambin
- 執行中切換來源、解析度與 FPS
- 曝光、亮度、ATR 對比、飽和度、增益與銳利度
- One Push Focus
- 4128×3096 強制 1 FPS
- 相機讀取、pipeline 重建與控制操作共用 reentrant lock
- 來源或格式重建失敗時嘗試恢復原來源

### 串流與推論

- Minimal 使用 YOLO TensorRT 並輸出標註畫面
- Final 加入 GPS 目標座標、連續幀確認及完整標註
- MJPEG 暫時斷幀重試及前端 HTTP 重連
- WebRTC peer 在 failed、closed、disconnected 與頁面離開時清理
- 所有目前入口均提供左上角平滑 FPS

### 手動擷取圖片

三個 minimal 與三個 final 都提供：

- 網頁「立即儲存 5 張」
- `POST /api/capture`
- 10 秒前端與後端冷卻
- 冷卻期間 HTTP 429 與 `retry_after`
- JPEG quality 95
- 有限 queue 與背景 thread 寫檔
- 檔名記錄時間、批次編號、曝光、解析度與 FPS
- 依實際啟動檔名建立輸出目錄

截圖取自新的 YOLO 處理完成幀，不會把 WebRTC 重送幀或 client 重複
取得的最新幀重複計入。Final 圖片包含 YOLO、目標確認、GPS 標註與
FPS。

## 相機格式現況

| Backend | 相機格式 | 處理路徑 |
|---|---|---|
| OpenCV | 優先要求 MJPG | OpenCV 解碼成 BGR |
| 一般 GStreamer | YUY2/YUYV | `videoconvert` → BGR |
| HW GStreamer | YUY2/YUYV | `nvvidconv compute-hw=2` → BGRx/BGR |
| 一般 tcambin | raw video | tcambin／軟體轉換 |
| HW tcambin | YUY2 | `nvvidconv compute-hw=2` → BGRx/BGR |

HW 版本不會自動：

- 從 YUYV 改用 MJPEG
- 降低解析度或 FPS
- 退回 OpenCV
- 改用其他 `/dev/video*`

Final 的 `--jpeg-decoder jpegdec|nvjpegdec` 目前僅保留 CLI 相容性。
現行 pipeline 沒有使用 JPEG 輸入，因此該參數不會改變實際處理路徑。

## 已驗證

### 相機與串流驗證

- DFK AFU130-L53 的 V4L2 與 tcambin 均可取像
- 1920×1080 可用 30、25、20、15、10、5 FPS
- 4128×3096 可用 1 FPS
- 工業相機 `/dev/video0` 是影像節點；`/dev/video1` 是 UVC metadata
- 工業相機 1920×1080 @ 30 FPS 輸入為未壓縮 YUYV 4:2:2
- Minimal MJPEG、WebRTC 軟體及 WebRTC VIC 均完成真實 client 端到端測試
- `yolo_final.py` 與 `yolo_final_hw.py` 已用目前的
  `11s_car_544_960.engine`、tcambin、1920×1080 @ 30 FPS 完成真實
  WebRTC client 端到端測試
- Webcam 已確認 1920×1080 @ 30 FPS 輸入為 MJPEG；YUYV 最高只有
  640×480 @ 30 FPS
- 兩個既有 final 曾以 `yolo11s.pt`、1280×720 完成三來源測試

目前 final 的實測沒有 `/dev/ttyUSB0`，因此 GPS 驗證範圍是 reader
無資料容錯及 `GPS unavailable` 標註；尚未驗證有效 NMEA、目標座標與
GPS 更新延遲。

### Jetson VIC

`webrtc_yolo_minimal_hw.py` 已在 `/dev/video0` 驗證：

```text
YUYV 1920×1080 @ 30
→ nvvidconv（VIC）
→ BGRx
→ contiguous BGR NumPy
→ yolo11s.engine
→ annotated frame
```

除早期 30 幀取流測試外，現已用 aiortc client 完成 SDP、ICE、DTLS、
RTP 與解碼驗證。Minimal VIC 及 Final VIC 都是 1920×1080，localhost
測試均為 0 RTP packet loss。

## 效能測試摘要

### 階段一：MJPEG → WebRTC

以 1920×1080 @ 30 FPS webcam 為例：

| 指標 | MJPEG | WebRTC |
|---|---:|---:|
| Client 收到 FPS | 13.74 | 38.14* |
| 網路流量 | 38.55 Mb/s | 1.14 Mb/s |
| Server CPU | 64.6% | 203.9% |
| Server RSS | 1254.6 MiB | 1451.2 MiB |

WebRTC 將頻寬降低約 97%，代價是 aiortc/PyAV 軟體編碼增加 CPU 與
記憶體。此處 WebRTC FPS 包含啟動追趕與重複最新 frame，不代表真正
有 38 FPS 的新 YOLO 結果。

### 階段二：CPU 色彩轉換 → Jetson VIC

工業相機 Minimal：

| 指標 | WebRTC 軟體 | WebRTC VIC |
|---|---:|---:|
| Server CPU 平均 | 254.94% | 207.28% |
| Client 幀間隔 P95* | 57.27 ms | 43.76 ms |

VIC 使 Minimal 平均 CPU 降低約 18.7%。

工業相機 Final：

| 指標 | `yolo_final.py` | `yolo_final_hw.py` |
|---|---:|---:|
| Server CPU 平均 | 253.56% | 230.75% |
| Server CPU P95 | 298.4% | 287.0% |
| Client 幀間隔 P95* | 57.66 ms | 45.87 ms |
| Server RSS | 1409.62 MiB | 1482.64 MiB |

VIC 使 Final 平均 CPU 降低約 9.0%，client 幀間隔 P95 改善約 20.4%，
但 RSS 多約 73 MiB。本輪功耗條件不足以判定 VIC 是否節能。

\* WebRTC client 指標仍受重複 frame 與排程追趕影響，不等同 unique
YOLO frame latency。

完整報告：

- `MJPEG_WEBRTC_PERFORMANCE_REPORT.md`
- `INDUSTRIAL_CAMERA_STREAMING_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_INDUSTRIAL_CAMERA_PERFORMANCE_REPORT.md`
- `TWO_STAGE_STREAMING_OPTIMIZATION_SUMMARY.md`

### Minimal 截圖

三個 minimal 已用 DFK AFU130-L53、tcambin、1920×1080 @ 30 FPS、
曝光 20000 µs實測五張圖片。JPEG 均可讀回為三通道 1920×1080，
HTTP 202／429 冷卻行為亦通過。

### Final 截圖

已完成：

- Python 語法檢查
- 路由、處理幀提交、FPS及 shutdown wiring 檢查
- 合成 BGR frame 的五張 JPEG 背景寫入
- 目錄命名、metadata 檔名與冷卻邏輯
- `git diff --check`

尚未以有效 GPS 資料對三個 final 做完整目標定位與實體相機截圖整合
測試。

## 目前 Git working tree 重點

主要已修改：

- `CURRENT_STATUS.md`
- `README.md`
- `minimal_control_ui.py`
- `mjpeg_yolo_minimal.py`
- `webrtc_yolo_minimal.py`
- `yolo_final.py`
- `yolo_final_mjpeg.py`

主要未追蹤：

- `11s_car_544_960.engine`
- `minimal_frame_capture.py`
- `webrtc_yolo_minimal_hw.py`
- `yolo_final_hw.py`
- 三組 minimal 實測 JPEG 目錄
- `camera_test.py`
- `MJPEG_WEBRTC_PERFORMANCE_REPORT.md`
- `INDUSTRIAL_CAMERA_STREAMING_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_INDUSTRIAL_CAMERA_PERFORMANCE_REPORT.md`
- `TWO_STAGE_STREAMING_OPTIMIZATION_SUMMARY.md`

## 已知限制

- 同一時間通常只能有一個程序持有相機。
- 一般 webcam 可能只在 MJPEG 提供 1920×1080 @ 30 FPS；HW 版固定
  YUYV 時可能無法以該設定啟動。
- MJPEG 1920×1080 頻寬很高。
- WebRTC 跨主機、NAT 或防火牆環境可能需要 STUN/TURN。
- WebRTC offer 至首幀目前約 10.25 秒。
- `CameraVideoTrack` 在協商前開始時基，連線後會 burst catch-up；client
  FPS 也可能包含重複最新 YOLO frame。
- WebRTC 目前使用 aiortc/PyAV 軟體視訊編碼，HW 版本尚未使用 Jetson
  硬體 H.264 encoder。
- WebRTC server 啟動後即使沒有 viewer 仍持續相機、YOLO 與標註。
- 工業相機 YUYV 1920×1080 @ 30 FPS 原始資料率約 995 Mb/s，USB、
  記憶體 copy 與色彩轉換成本高。
- 目前測試只有 4 個 CPU cores online；nvpmodel 變更會影響效能數據。
- Final 尚未用有效 `/dev/ttyUSB0` GPS 做 NMEA 與目標座標端到端驗證。
- tcambin 重建與高解析度首幀可能較慢。
- 相機控制值讀回一致不代表畫面效果已量測驗證。

## 下一步

1. 修正 WebRTC 約 10 秒首幀等待與 `started_at` burst catch-up。
2. 在 capture、YOLO、annotation、send、client decode/render 加入
   `frame_id` 與 timestamps，量測 unique YOLO FPS。
3. 整合 Jetson 硬體 H.264 encoder；目前 GStreamer 只負責相機輸入與
   VIC 色彩轉換。
4. 減少 BGRx→BGR、latest frame 與 VideoFrame 的重複 copy。
5. 用遠端實體 client 測試 Chrome／Firefox、純 server 功耗、LAN 延遲
   與 STUN/TURN。
6. 鎖定 exposure、gain、white balance 與場景，軟體／VIC 交錯各跑
   5 次，並做 30～60 分鐘 soak test。
7. 接上 `/dev/ttyUSB0` GPS 後測 NMEA、目標座標、GPS 更新延遲與五張
   final 截圖完整流程。
8. 測試 1、2、4 viewer；目前每個 WebRTC peer 仍有獨立 encoder。
