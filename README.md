# UAV YOLO 串流專案

本專案在 NVIDIA Jetson Orin NX 上整合工業相機／USB webcam、YOLO
TensorRT、GPS 目標定位與瀏覽器串流。主要入口分成 minimal 與 final：

- minimal：用來驗證相機、YOLO、控制 GUI、FPS、截圖與串流
- final：在相同相機控制基礎上加入 GPS、連續幀確認與目標座標標註

目前預設影像設定為 1920×1080 @ 30 FPS。TensorRT engine 與 JetPack、
TensorRT 版本及硬體相關，不建議直接搬到不同平台使用。

## 環境

目前平台：

- NVIDIA Jetson Orin NX Engineering Reference Developer Kit
- aarch64
- Jetson Linux R36.5.0（Linux 5.15 tegra）
- Python 3.10.12

啟用既有環境：

```bash
source .venv/bin/activate
```

安裝 Python 相依套件：

```bash
python -m pip install -r requirements.txt
```

或：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

GStreamer／tiscamera 路徑另需系統提供：

- GStreamer 1.0 與 PyGObject GI
- tiscamera／tcambin 0.14.0
- Tcam 0.1 introspection
- Jetson `nvvidconv`（VIC/H.264 HW 版本需要）
- Jetson `nvv4l2h264enc`（H.264 HW 版本需要）

檢查裝置與插件：

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
gst-inspect-1.0 tcambin
gst-inspect-1.0 nvvidconv
gst-inspect-1.0 nvv4l2h264enc
```

## 快速選擇

| 程式 | 傳輸 | GPS／目標定位 | 硬體路徑 |
|---|---|---:|---|
| `mjpeg_yolo_minimal.py` | MJPEG | 無 | OpenCV 或 tcambin 軟體路徑 |
| `webrtc_yolo_minimal.py` | WebRTC | 無 | OpenCV 或 tcambin 軟體路徑 |
| `webrtc_yolo_minimal_hw.py` | WebRTC | 無 | GStreamer／tcambin 使用 VIC |
| `webrtc_yolo_minimal_jetson_h264.py` | WebRTC H.264 | 無 | VIC + Jetson NVENC |
| `yolo_final.py` | WebRTC | 有 | 軟體路徑 |
| `yolo_final_mjpeg.py` | MJPEG | 有 | 軟體路徑 |
| `yolo_final_hw.py` | WebRTC | 有 | GStreamer／tcambin 使用 VIC |
| `yolo_final_jetson_h264.py` | WebRTC H.264 | 有 | VIC + Jetson NVENC |

所有上述入口都有右側相機控制面板。四個 minimal 與四個 final 都提供
平滑 FPS 疊字及「立即儲存 5 張」功能。

## Minimal

預設模型：

```text
yolo11s.engine
```

### MJPEG

```bash
python mjpeg_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

```bash
python mjpeg_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

瀏覽：

```text
http://127.0.0.1:5000
```

MJPEG 只有在 `/video_feed` 有 client 時才持續取像、推論及截圖。暫時
斷幀時後端會重試；HTTP 中斷時前端每秒重新連線。

### WebRTC

```bash
python webrtc_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

```bash
python webrtc_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

瀏覽：

```text
http://localhost:8080
```

### WebRTC + Jetson VIC

```bash
python webrtc_yolo_minimal_hw.py \
  --camera-source v4l2 \
  --v4l2-device /dev/video0
```

或 The Imaging Source 相機：

```bash
python webrtc_yolo_minimal_hw.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

HW 路徑固定使用相機原生 YUY2/YUYV：

```text
YUY2 → nvvidconv compute-hw=2（VIC）→ BGRx → BGR NumPy
```

它不會自動改用 MJPEG、降低解析度/FPS或退回 OpenCV。

### WebRTC + Jetson VIC + H.264

```bash
python webrtc_yolo_minimal_jetson_h264.py \
  --camera-source v4l2 \
  --v4l2-device /dev/video0 \
  --h264-bitrate 3000000
```

此入口保留 minimal 的相機控制、YOLO、FPS、截圖與 shutdown，並將
WebRTC encoder 改為 Jetson `nvv4l2h264enc`。實際 SDP 只允許 H.264
constrained baseline，不會退回 VP8。

輸出路徑：

```text
YOLO BGR → BGRx → nvvidconv → NVMM NV12
→ nvv4l2h264enc → H.264 RTP → WebRTC
```

預設為固定 3 Mbps CBR。encoder 前的 raw queue 可丟舊 frame 以限制延遲；
encoder 後使用 `appsink max-buffers=1 drop=false`，避免丟失 H.264 參考幀
造成短暫破圖。

## Final

Final 共用以下功能：

- YOLO TensorRT 推論，預設模型 `11s_car_544_960.engine`
- 推論尺寸 544×960
- GPS 讀取與目標座標推算
- 連續幀確認與完整畫面標註
- 三種來源：OpenCV、GStreamer/v4l2src、tiscamera/tcambin
- 執行中切換來源、解析度、FPS及相機屬性
- 平滑 FPS
- 非阻塞背景保存五張完整 YOLO/GPS 標註 JPEG

### WebRTC final

```bash
python yolo_final.py \
  --camera-backend opencv \
  --camera-index 0
```

```bash
python yolo_final.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0
```

```bash
python yolo_final.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

### MJPEG final

```bash
python yolo_final_mjpeg.py \
  --camera-backend opencv \
  --camera-index 0
```

其他 backend 參數與 WebRTC final 相同。

### WebRTC final + Jetson VIC

```bash
python yolo_final_hw.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0
```

```bash
python yolo_final_hw.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

`yolo_final_hw.py` 重用 `yolo_final.py` 的 WebRTC、YOLO、GPS、控制、
截圖與 shutdown，只替換 GStreamer／tcambin 相機轉換層。若選
`--camera-backend opencv`，仍是 OpenCV 軟體路徑，不會使用 VIC。

### WebRTC final + Jetson VIC + H.264

```bash
python yolo_final_jetson_h264.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --h264-bitrate 3000000
```

或使用 tiscamera：

```bash
python yolo_final_jetson_h264.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280 \
  --h264-bitrate 3000000
```

此入口重用 `yolo_final.py` 的 final processor 與
`yolo_final_hw.py` 的 VIC camera manager，再接上共用 Jetson H.264 adapter。
GPS、temporal confirmation、控制 API、截圖與 shutdown 都保留。預設 H.264
為 3 Mbps CBR，encoded appsink 為 `drop=false`。

Final 預設連接埠為 8080：

```text
http://127.0.0.1:8080
```

可用 `--model-path` 覆寫模型，例如：

```bash
python yolo_final.py --model-path yolo11s.pt
```

## 相機格式與硬體加速

目前各 backend 的實際策略：

| Backend | 要求的相機格式 | 處理方式 |
|---|---|---|
| `opencv` | 優先要求 MJPG | OpenCV 解碼成 BGR |
| 一般 `gstreamer` | YUY2/YUYV | `videoconvert` 軟體轉換 |
| HW `gstreamer` | YUY2/YUYV | `nvvidconv` VIC 轉換 |
| 一般 `tiscamera` | raw video | tcambin／軟體轉換 |
| HW `tiscamera` | YUY2 | `nvvidconv` VIC 轉換 |

OpenCV 的 FOURCC 設定是向驅動提出要求；裝置仍可能拒絕或協商成其他
格式。程式執行時可確認實際格式：

```bash
v4l2-ctl -d /dev/video0 --get-fmt-video
```

Final CLI 仍保留 `--jpeg-decoder jpegdec|nvjpegdec`，但目前只是舊版
相容參數。現行 GStreamer 與 HW pipeline 都使用 YUY2，沒有經過
`image/jpeg → jpegdec/nvjpegdec`，因此切換該參數不會改變 pipeline。

一般 webcam 常在 1920×1080 @ 30 FPS 只提供 MJPEG，而 YUYV 只能較低
FPS。HW 版本不會自動協商 fallback；使用前應先查看
`--list-formats-ext`。

## WebRTC codec 與 bitrate

一般 WebRTC 入口未強制 codec；目前 aiortc client 實測會優先選 VP8。VP8
初始目標為 500 kbps，依 REMB 在 250 kbps～1.5 Mbps 之間調整。

兩個 Jetson H.264 入口只允許 H.264 constrained baseline，預設：

```text
bitrate=3000000（3 Mbps）
control-rate=CBR
IDR interval=30 frames
insert SPS/PPS at IDR
encoded appsink drop=false
```

可用 `--h264-bitrate` 改成其他值。3 Mbps 對 1080p30 快速移動、細節與
YOLO/GPS 文字較有餘裕，但需要比原 VP8 更高且穩定的頻寬。Jetson R36 的
encoder 在 PLAYING 狀態不能不中斷修改 bitrate，因此目前同一解析度期間不會
依 REMB 動態調整。

## 相機控制與截圖

右側面板支援：

- 相機來源
- 解析度與 FPS
- 曝光時間
- 亮度
- ATR 對比
- 飽和度
- 增益
- 銳利度
- One Push Focus
- 立即儲存 5 張

「預設」只會填入欄位，仍需按「套用」。4128×3096 會強制使用 1 FPS。
手動曝光會關閉自動曝光；手動增益會關閉自動增益。

截圖 API：

```text
POST /api/capture
```

每次保存接下來五個新的 YOLO 處理幀，JPEG quality 95，磁碟寫入在背景
thread 執行。前後端都有 10 秒冷卻，冷卻期間後端回 HTTP 429。目錄以
啟動檔名命名，例如：

```text
webrtc_yolo_minimal/
yolo_final/
yolo_final_mjpeg/
yolo_final_hw/
webrtc_yolo_minimal_jetson_h264/
yolo_final_jetson_h264/
```

檔名包含時間、批次編號、曝光、解析度與 FPS。Final 圖片包含 YOLO、
連續幀確認、GPS 標註與 FPS。

## 共用模組與舊版

- `minimal_camera_control.py`：相機來源、控制、格式切換與鎖
- `minimal_control_ui.py`：右側控制面板
- `minimal_frame_capture.py`：五張圖片 queue、冷卻及背景 JPEG 寫入
- `gps_geolocation.py`：GPS 讀取與目標座標估算
- `webrtc_yolo_minimal_jetson_h264.py`：共用 Jetson H.264 encoder adapter
- `yolo_final_old.py`、`yolo_final_mjpeg_old.py`：重構前備份

`hahaha2.py`、`hahaha3.py` 與 `yolo_gstreamer2.py` 是早期實驗程式，
保留供參考；新工作應優先使用 minimal 或 final 系列。

## 執行注意事項

- 同一時間通常只能有一個程序持有 `/dev/video0`。
- `0.0.0.0` 是 bind 位址，不應作為瀏覽器網址。
- localhost WebRTC 可使用 HTTP；跨主機、NAT 或防火牆環境可能需要
  STUN/TURN。
- tcambin pipeline 重建與高解析度首幀可能較慢。
- MJPEG 1920×1080 頻寬很高，低頻寬鏈路應優先使用 WebRTC。
- Jetson H.264 預設固定 3 Mbps；弱網路環境應先測 2～3 Mbps 的畫質與穩定性。
- H.264 encoder 後必須保持 `drop=false`；丟失已編碼 P-frame 可能短暫破圖。
- 每個 H.264 viewer 目前各自建立一個 NVENC instance，多 viewer 需另行壓測。
- One Push Focus 是一次性動作，只能確認命令被接受。
- 受限 sandbox 無法存取 USB、`/dev/video*` 或 Jetson GPU 時，需在
  主機環境執行實機測試。

## 效能報告

- `MJPEG_WEBRTC_PERFORMANCE_REPORT.md`
- `INDUSTRIAL_CAMERA_STREAMING_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_INDUSTRIAL_CAMERA_PERFORMANCE_REPORT.md`
- `TWO_STAGE_STREAMING_OPTIMIZATION_SUMMARY.md`
- `JETSON_H264_WEBRTC_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_JETSON_H264_PERFORMANCE_REPORT.md`

最新實機 30 秒穩態比較：Minimal H.264 相較 VP8 的 server CPU 降低
41.1%；Final H.264 降低 30.1%，並將 final client FPS 從 28.73 提升至
30.03。詳細測試條件、功耗、溫度、bitrate 與 `drop=false` 取捨請看後兩份
H.264 報告。
