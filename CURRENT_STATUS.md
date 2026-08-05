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

| 程式 | 傳輸 | GPS | 硬體路徑 |
|---|---|---:|---|
| `mjpeg_yolo_minimal.py` | MJPEG | 無 | OpenCV／tcambin 軟體路徑 |
| `webrtc_yolo_minimal.py` | WebRTC | 無 | OpenCV／tcambin 軟體路徑 |
| `webrtc_yolo_minimal_hw.py` | WebRTC | 無 | GStreamer／tcambin 使用 VIC |
| `webrtc_yolo_minimal_jetson_h264.py` | WebRTC H.264 | 無 | VIC + Jetson NVENC |
| `yolo_final.py` | WebRTC | 有 | 軟體路徑 |
| `yolo_final_mjpeg.py` | MJPEG | 有 | 軟體路徑 |
| `yolo_final_hw.py` | WebRTC | 有 | GStreamer／tcambin 使用 VIC |
| `yolo_final_jetson_h264.py` | WebRTC H.264 | 有 | VIC + Jetson NVENC |

四個 final 共用 YOLO、GPS、連續幀確認、控制 GUI及截圖核心。
`yolo_final_hw.py` 只替換相機轉換層；`yolo_final_jetson_h264.py` 再將
WebRTC 輸出替換為 Jetson H.264。選擇 OpenCV backend 時相機輸入仍不使用
VIC。目前沒有 MJPEG + VIC 的 final 入口。

目前建議的工業相機正式入口：

```bash
python yolo_final_jetson_h264.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --h264-bitrate 3000000
```

此入口的相機 YUY2→BGRx 使用 Jetson VIC，WebRTC 輸出使用
`nvv4l2h264enc`、H.264 constrained baseline、3 Mbps CBR。encoder 後
appsink 為 `drop=false`，避免丟失已編碼參考幀。

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
- Minimal 與 Final 都已有 Jetson H.264 硬體編碼入口
- H.264 SDP 強制 constrained baseline，不會退回 VP8
- H.264 支援 SPS/PPS、PLI `force-IDR` 與 aiortc RTP packetization

### 手動擷取圖片

四個 minimal 與四個 final 都提供：

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
- Minimal MJPEG、WebRTC 軟體、WebRTC VIC 及 Jetson H.264 均完成真實
  client 端到端測試
- `yolo_final.py` 與 `yolo_final_hw.py` 已用目前的
  `11s_car_544_960.engine`、tcambin、1920×1080 @ 30 FPS 完成真實
  WebRTC client 端到端測試
- `yolo_final_jetson_h264.py` 已用相同 final engine、GStreamer
  `/dev/video0`、1920×1080 @ 30 FPS 完成 NVENC WebRTC 端到端測試
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

### Jetson H.264

兩個 H.264 入口已用 `/dev/video0`、1920×1080 @ 30 FPS 與實際
TensorRT YOLO 完成 localhost WebRTC 測試：

```text
YOLO annotated BGR
→ BGRx appsrc
→ nvvidconv → NVMM NV12
→ nvv4l2h264enc（3 Mbps CBR）
→ Annex-B H.264
→ aiortc RTP packetization
→ WebRTC client decode
```

實際 SDP answer 只包含 `H264/90000`、`profile-level-id=42e01f`。server
log 已確認建立 NVENC channel。Minimal `drop=false` 測試 30.03 FPS，Final
`drop=false` 測試 30.03 FPS，兩者皆為 0 RTP packet loss。

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
- `JETSON_H264_WEBRTC_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_JETSON_H264_PERFORMANCE_REPORT.md`

### 階段三：軟體 WebRTC encoder → Jetson H.264

實際 DFK 相機、TensorRT YOLO、10 秒暖機加 30 秒量測：

| 指標 | Minimal VP8 | Minimal H.264 | Final VP8 | Final H.264 |
|---|---:|---:|---:|---:|
| Server CPU | 204.58% | 120.58% | 226.05% | 157.93% |
| Client FPS | 31.63* | 30.03 | 28.73 | 30.03 |
| 幀間隔 P95 | 41.82 ms | 43.48 ms | 48.15 ms | 42.84 ms |
| RTP packets lost | 0 | 0 | 0 | 0 |
| VDD_IN | 8.578 W | 8.248 W | 9.415 W | 9.366 W |

Minimal server CPU 降低 41.1%，約省 0.84 core；Final 降低 30.1%，約省
0.68 core。Final H.264 同時將接收 FPS 從 28.73 提升至 30.03。

軟體版正式測試實際協商 VP8，初始目標 500 kbps、動態範圍
250 kbps～1.5 Mbps；Jetson H.264 固定 3 Mbps CBR。H.264 畫質與快速移動
細節較有餘裕，但需要較高且穩定的網路頻寬。

\* Minimal VP8 超過 30 FPS 是 `CameraVideoTrack` 建連後的排程追趕，不代表
相機或 YOLO 產生超過 30 個新幀。

### Minimal 截圖

三個既有 minimal 已用 DFK AFU130-L53、tcambin、1920×1080 @ 30 FPS、
曝光 20000 µs實測五張圖片。JPEG 均可讀回為三通道 1920×1080，
HTTP 202／429 冷卻行為亦通過。

### Final 截圖

已完成：

- Python 語法檢查
- 路由、處理幀提交、FPS及 shutdown wiring 檢查
- 合成 BGR frame 的五張 JPEG 背景寫入
- 目錄命名、metadata 檔名與冷卻邏輯
- `git diff --check`

尚未以有效 GPS 資料對 final 系列做完整目標定位與實體相機截圖整合
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
- `webrtc_yolo_minimal_jetson_h264.py`
- `yolo_final_jetson_h264.py`
- 三組 minimal 實測 JPEG 目錄
- `camera_test.py`
- `MJPEG_WEBRTC_PERFORMANCE_REPORT.md`
- `INDUSTRIAL_CAMERA_STREAMING_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_INDUSTRIAL_CAMERA_PERFORMANCE_REPORT.md`
- `TWO_STAGE_STREAMING_OPTIMIZATION_SUMMARY.md`
- `JETSON_H264_WEBRTC_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_JETSON_H264_PERFORMANCE_REPORT.md`

## Jetson H.264 整合時遇到的困難

### 1. aiortc 沒有公開的 Jetson encoder plugin API

aiortc 1.15.0 預設由內部 encoder factory 建立 libvpx/libx264。現在以明確
版本限制的 adapter 替換 H.264 factory，並重用 aiortc 的 STAP-A／FU-A
packetizer。升級 aiortc 時必須重新驗證私有介面。

### 2. Codec preference 設定時機太晚會繼續使用 VP8

初版在 `setRemoteDescription()` 後才呼叫 `setCodecPreferences()`。aiortc
此時已固定 common codec list，實際 answer 仍以 VP8 為第一個 payload，
也完全沒有建立 NVENC。修正方式是先建立 send-only transceiver、限制 H.264，
再套用 remote offer，最後以 `replaceTrack()` 接上影像。

### 3. 第一幀前呼叫 `force-IDR` 會 segmentation fault

Jetson Linux R36.5.0 上，NVENC channel 尚未由第一個 input buffer 建立前，
呼叫 `nvv4l2h264enc` 的 `force-IDR` action 會使 process crash。新 encoder
自然由 IDR 開始，因此目前只在至少成功輸出一幀後回應 WebRTC PLI。

### 4. 每幀同步等待 NVENC 會無法維持 30 FPS

若 `encode()` push 一幀後同步等待同一 access unit，nvvidconv 與 NVENC
無法 pipeline 並行，完整 WebRTC 曾只有約 24～27 FPS。現在保留一幀硬體
pipeline latency；aiortc 在 access unit 尚未完成時允許空 payload，下一輪
再取已完成輸出，最終恢復 30 FPS。

### 5. Encoded appsink `drop=true` 會偶發破圖

初版 encoder 後使用 `appsink max-buffers=1 drop=true`。它可能丟掉已形成
H.264 參考鏈的 P-frame，造成短暫破圖直到下一個 IDR；因遺失發生在 RTP
之前，client `packetsLost` 仍可能是 0。改為 `drop=false` 後使用者初步測試
未再看到破圖，重測也沒有量到明顯 CPU 或延遲代價。encoder 前仍保留
leaky raw queue，超載時優先丟 raw frame。

### 6. Jetson R36 無法在 PLAYING 動態修改 bitrate

`nvv4l2h264enc bitrate` 只允許在 NULL／READY 修改。曾嘗試依 REMB 重建
encoder，但每次會產生約 200 ms 初始化停頓與新 IDR，反而降低 FPS。目前
同一解析度生命週期固定使用 CLI bitrate；預設為 3 Mbps。

### 7. 功耗與溫度容易受測試順序誤導

NVENC 不是 GR3D CUDA workload，1 Hz GR3D sampling 也會受 YOLO burst 相位
影響。連續執行兩組短測試會有散熱器熱累積，因此 30 秒數據可比較 CPU／FPS，
但不能用約 1°C 的差異直接宣稱哪一版更冷。熱穩態需交錯順序並各跑
10～15 分鐘。

## 已知限制

- 同一時間通常只能有一個程序持有相機。
- 一般 webcam 可能只在 MJPEG 提供 1920×1080 @ 30 FPS；HW 版固定
  YUYV 時可能無法以該設定啟動。
- MJPEG 1920×1080 頻寬很高。
- WebRTC 跨主機、NAT 或防火牆環境可能需要 STUN/TURN。
- WebRTC offer 至首幀目前約 10.25 秒。
- `CameraVideoTrack` 在協商前開始時基，連線後會 burst catch-up；client
  FPS 也可能包含重複最新 YOLO frame。
- Jetson H.264 同一解析度期間固定 bitrate，尚未支援不中斷的 REMB 動態調碼率。
- H.264 adapter 使用 aiortc 1.15.0 私有 factory／packetizer，升級需重驗。
- `drop=false` 保護參考鏈，但下游長時間阻塞時會向上游產生 backpressure。
- 每個 H.264 WebRTC peer 仍各自建立一個 NVENC instance。
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
3. 減少 BGRx→BGR、latest frame、BGR→BGRx 與 VideoFrame 的重複 copy。
4. 評估不中斷的 H.264 動態 bitrate，或在弱網路時安全重建 encoder。
5. 用遠端實體 client 測試 Chrome／Firefox、純 server 功耗、LAN 延遲
   與 STUN/TURN。
6. 鎖定 exposure、gain、white balance 與場景，軟體／VIC 交錯各跑
   5 次，並做 30～60 分鐘 soak test。
7. 接上 `/dev/ttyUSB0` GPS 後測 NMEA、目標座標、GPS 更新延遲與五張
   final 截圖完整流程。
8. 測試 1、2、4 viewer；目前每個 WebRTC peer 仍有獨立 encoder。
