# UAV YOLO 串流專案

本專案包含數個相機取像、YOLO 偵測、GPS 目標定位及瀏覽器串流實驗。
`gps_geolocation.py` 是其他程式匯入的 GPS 共用模組，本文件依需求不列出其獨立用法。

## 環境

目前已在 Ubuntu 22.04、Python 3.10.12、The Imaging Source
DFK AFU130-L53 上驗證。專案虛擬環境由 `uv` 建立：

```bash
source .venv/bin/activate
```

主要 Python 套件包括：

- OpenCV、NumPy、Ultralytics
- Flask
- aiohttp、aiortc、PyAV
- pyserial、pynmea2
- PyGObject（使用系統套件，供 GStreamer GI 使用）

一鍵安裝 Python 套件：

```bash
python -m pip install -r requirements.txt
```

或使用 uv：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

Jetson 上若需 NVIDIA 特製的 PyTorch／TorchVision wheel，應先依 JetPack
版本安裝正確版本，再執行 `requirements.txt`。本檔不直接固定 PyTorch，
由 Ultralytics 使用現有版本或解析相依套件。

tiscamera 路徑另需：

- GStreamer 1.0
- tiscamera／tcambin 0.14.0
- Tcam 0.1 introspection
- 相容的 tcamdutils

可先確認：

```bash
gst-inspect-1.0 tcambin
tcam-ctrl --list
v4l2-ctl -d /dev/video0 --all
```

## 程式用法

### `hahaha2.py`

功能：

- OpenCV `VideoCapture` 取像
- 背景 camera thread，只保留最新 frame
- YOLO TensorRT 推論
- 連續幀目標確認
- HSV 紅色目標判斷
- GPS 目標定位與標註
- Flask MJPEG，連接埠 5000

執行前需直接修改檔案頂部常數，例如：

```python
CAMERA_SOURCE = 0
MODEL_PATH = "model/11s_car_rec.engine"
GPS_PORT = "/dev/ttyUSB0"
ALTITUDE_AGL_M = 80.0
HFOV_DEG = 52.0
VFOV_DEG = 31.0
CAMERA_YAW_OFFSET_DEG = 0.0
```

執行：

```bash
python hahaha2.py
```

瀏覽：

```text
http://127.0.0.1:5000
```

### `hahaha3.py`

用法與 `hahaha2.py` 相同：

```bash
python hahaha3.py
```

它是 `hahaha2.py` 的調整版，主要差異是：

- 明確要求相機輸出 MJPG
- 要求 1280×720、15 FPS
- HSV ROI 半徑由 9 改為 11
- HSV 判斷加入較寬的紅色範圍及紫色範圍
- GPS 標籤字體由 0.45 放大到 0.65
- GPS 標籤間距由 4 增加到 5
- HTML 影像容器版面有調整

模型、GPS、飛行高度與 FOV 等仍需在檔案頂部修改。

### `yolo_gstreamer2.py`

功能：

- 可在 OpenCV 與 GStreamer GI 取像間切換
- GStreamer 使用 `v4l2src → image/jpeg → jpegdec/nvjpegdec`
- 可選擇是否啟用背景 camera thread
- YOLO TensorRT、GPS 定位、連續幀確認
- Flask MJPEG，連接埠 5000

此程式沒有 CLI，需修改檔案頂部設定：

```python
CAMERA_BACKEND = "gstreamer_gi"  # 或 "opencv"
CAMERA_SOURCE = 0
GSTREAMER_DEVICE = "/dev/video0"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
GSTREAMER_JPEG_DECODER = "jpegdec"  # 或 "nvjpegdec"
ENABLE_CAMERA_THREAD = True
MODEL_PATH = "model/11s_car_960.engine"
```

執行：

```bash
python yolo_gstreamer2.py
```

瀏覽：

```text
http://127.0.0.1:5000
```

### `yolo_final.py`

整合版 WebRTC 程式，包含：

- OpenCV/V4L2、GStreamer `v4l2src`、GStreamer `tcambin` 三種來源
- YOLO、GPS 定位、連續幀確認
- 背景推論，只保留最新標註畫面
- aiohttp + aiortc WebRTC，連接埠 8080

OpenCV：

```bash
python yolo_final.py \
  --camera-backend opencv \
  --camera-index 0
```

GStreamer 軟體 JPEG 解碼：

```bash
python yolo_final.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --model-path yolo11s.pt
```

tcambin：

```bash
python yolo_final.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280 \
  --model-path yolo11s.pt
```

正式默认模型仍是 `model/11s_car_960.engine`。`--model-path yolo11s.pt`
用于不依赖 TensorRT 的测试。DFK AFU130-L53 的 `v4l2src` 路径实际使用
YUY2 raw；`--jpeg-decoder` 仅保留为旧版相容参数。

瀏覽：

```text
http://127.0.0.1:8080
```

`0.0.0.0` 是伺服器監聽位址，不應作為瀏覽器目的位址。

### `yolo_final_mjpeg.py`

`yolo_final.py` 的 MJPEG 輸出版，重用其相機、YOLO、GPS 及追蹤處理：

```bash
python yolo_final_mjpeg.py \
  --camera-backend opencv \
  --camera-index 0
```

三种相机来源及 `--model-path` 用法与 `yolo_final.py` 相同。

```bash
python yolo_final_mjpeg.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --model-path yolo11s.pt
```

瀏覽：

```text
http://127.0.0.1:8080
```

它使用 `yolo_final.py` 的 YOLO/GPS 核心类，因此两个文件必须放在同一目录。
相机路径、控制 GUI 和控制 API 已与 WebRTC final 共用。

### Final 舊版備份

- `yolo_final_old.py`：三來源與控制 GUI 整合前的 WebRTC 原版
- `yolo_final_mjpeg_old.py`：整合前的 MJPEG 原版，引用
  `yolo_final_old.py`

舊版只提供 `opencv` 與旧式 `gstreamer` 两个 backend，不包含 tcambin、
动态控制 GUI 或 `--model-path`。

### `mjpeg_yolo_minimal.py`

最小化 MJPEG 實驗，可從 CLI 選擇 V4L2/OpenCV 或 tcambin：

```bash
python mjpeg_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

```bash
python mjpeg_yolo_minimal.py \
  --camera-source tiscamera
```

指定 tiscamera 序號：

```bash
python mjpeg_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 26410280
```

瀏覽：

```text
http://127.0.0.1:5000
```

網頁包含可收合的右側相機控制面板。MJPEG 暫時失去 frame 時會保留
multipart response；若 HTTP 真的中斷，前端每秒自動重連。

### `webrtc_yolo_minimal.py`

最小化 WebRTC 實驗，相機 CLI 與 MJPEG minimal 相同：

```bash
python webrtc_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

```bash
python webrtc_yolo_minimal.py \
  --camera-source tiscamera
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

本機接收 WebRTC 不需要 HTTPS。從其他電腦連線時使用主機實際 IP，
不要使用 `0.0.0.0`。跨網段或 NAT 環境可能需要 STUN/TURN。

### 共用 minimal 模組

以下檔案不直接執行：

- `minimal_camera_control.py`：V4L2、tcambin、來源切換、格式與屬性控制
- `minimal_control_ui.py`：兩個 minimal 共用的右側控制面板

## 相機控制 GUI

兩個 minimal 共用同一套控制面板，支援執行中切換：

- V4L2（CLI 名稱仍為 `opencv`，Linux 上明確以 `CAP_V4L2` 開啟）
- tiscamera／tcambin

可控制：

- 解析度
- FPS
- 曝光時間
- 亮度
- ATR 對比
- 飽和度
- 增益
- 銳利度
- One Push Focus

除來源與一次性 One Push Focus 外，每項都有「預設」及「套用」按鈕。
「預設」只填值，使用者仍需按「套用」。選擇 4128×3096 時後端強制
1 FPS，FPS 選單與按鈕會停用。

面板預設收合在右側，以 `translateX(100%)` 移出視窗；箭頭可展開。
面板透明度為 0.6，窄螢幕會將標籤與控制項換行。

## 比較

### `hahaha2`、`hahaha3`、`yolo_gstreamer2`

| 面向 | `hahaha2.py` | `hahaha3.py` | `yolo_gstreamer2.py` |
|---|---|---|---|
| 輸出 | Flask MJPEG | Flask MJPEG | Flask MJPEG |
| 相機來源 | OpenCV | OpenCV | OpenCV 或 GStreamer GI `v4l2src` |
| 相機格式 | 1280×720，未明確 FPS/FourCC | 1280×720、15 FPS、MJPG | 1280×720、30 FPS、JPEG |
| 模型 | `11s_car_rec.engine` | `11s_car_rec.engine` | `11s_car_960.engine` |
| GPS | 有 | 有 | 有 |
| 連續幀確認 | 有 | 有 | 有 |
| HSV 顏色判斷 | 標準雙紅色區間 | 擴大紅色並納入紫色 | 無 `hahaha2/3` 的 HSV 紅色分類流程 |
| Camera thread | 固定啟用 | 固定啟用 | 可開關 |
| 設定方式 | 修改常數 | 修改常數 | 修改常數 |

`hahaha3` 是針對相機格式、色彩 ROI 和標籤可讀性調整的
`hahaha2`。`yolo_gstreamer2` 的重點則是比較 OpenCV 與 GStreamer GI
相機路徑、JPEG decoder 和 camera thread，並不是 `hahaha3` 的單純後繼版。

### 上述三支與兩個 minimal 的主要差異

`hahaha2`、`hahaha3`、`yolo_gstreamer2` 是應用功能較完整的版本：

- 使用 TensorRT engine
- 整合 GPS 目標定位
- 有連續幀目標確認
- 前兩支另有 HSV 色彩分類
- 主要參數依靠修改程式常數

兩個 minimal 的目的則是隔離並驗證相機與串流：

- 使用 `yolo11s.pt`
- 不含 GPS 與完整目標邏輯
- 可從 CLI 選 V4L2 或 tcambin
- 有共用的網頁相機控制 GUI
- 支援執行中切換來源、格式與相機屬性
- 已針對實際 DFK AFU130-L53 驗證

minimal 的控制层已移植到 `yolo_final.py` 与
`yolo_final_mjpeg.py`，包含执行绪同步、pipeline 重建及
WebRTC/MJPEG 暂时中断恢复。

### 兩個 minimal 的比較

| 面向 | `mjpeg_yolo_minimal.py` | `webrtc_yolo_minimal.py` |
|---|---|---|
| 傳輸 | HTTP multipart MJPEG | WebRTC |
| 伺服器 | Flask | aiohttp + aiortc |
| 預設連接埠 | 5000 | 8080 |
| 瀏覽器元素 | `<img>` | `<video>` |
| 推論時機 | `/video_feed` generator 內 | 背景 thread 持續推論 |
| 無觀眾時 | 不執行串流 generator | 仍持續取像與推論 |
| 畫面策略 | 每個串流請求依序處理 | 只保存最新標註 frame |
| 時序 | 無視訊 PTS | 90 kHz clock 與 PTS |
| 頻寬 | 高，每幀獨立 JPEG | 通常較低 |
| 延遲 | 簡單但通常較高 | 通常較適合即時影像 |
| 暫時斷幀 | 保留 response 並重試 | camera thread 持續重試 |
| 網路需求 | 一般 HTTP 即可 | ICE；跨網段可能需要 STUN/TURN |

## 執行注意事項

- 同一時間通常只能有一個程序持有 `/dev/video0`。
- 先前測試程序若未關閉，可用 `fuser -v /dev/video0` 及
  `ss -ltnup | grep 8080` 檢查。
- 手動曝光會關閉自動曝光；手動增益會關閉自動增益。
- 屬性 API 回傳的「實際值」代表驅動接受且可讀回，不等同肉眼一定能看出差異。
- One Push Focus 是一次性、無完成狀態的動作；只能確認命令被接受。
- tcambin 格式重建時首幀可能較慢，目前單次讀取等待上限為 5 秒。
- 4128×3096 只能使用 1 FPS。
- MJPEG 會消耗大量頻寬；1920×1080 實測 25 秒曾超過 300 MB。
- WebRTC 在 localhost 使用 HTTP 即可；`0.0.0.0` 只供 bind。
- WebRTC 瀏覽器顯示 `failed` 時，應檢查 ICE、UDP 防火牆、舊 peer
  connection、網址與 STUN/TURN，而不只檢查相機。
