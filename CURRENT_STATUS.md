# Current Status

更新日期：2026-07-29

## 專案目前狀態

目前工作平台：

- NVIDIA Jetson Orin NX Engineering Reference Developer Kit
- aarch64
- Jetson Linux R36.5.0（Linux 5.15 tegra）

本文件保留先前環境的既有實測狀態；下列舊結果除非明確標示 Jetson
Orin，否則不視為已在 Orin 上重新驗證。

本次 Jetson Orin 更新：

- 新增根目錄 TensorRT engine：`yolo11n.engine`、`11s_car_960.engine`
- `mjpeg_yolo_minimal.py` 的預設模型改為 `yolo11n.engine`
- tcambin 的 One Push Focus 屬性名稱修正為
  `Auto Focus One Push`

本輪已完成：

- 建立 Python 3.10.12 `.venv`，由 `uv 0.11.33` 管理
- 實機確認 The Imaging Source DFK AFU130-L53
- 實機確認 tiscamera／tcambin 0.14.0 與 GStreamer 1.20.3
- 完成兩個 minimal 的 V4L2 與 tcambin 雙來源
- 完成兩個 minimal 共用相機控制 GUI
- 完成 MJPEG 與 WebRTC 的四組端到端實測
- 建立 `yolo_final_mjpeg.py`
- 两个 final 均完成三种相机路径与控制 GUI
- 建立 `yolo_final_old.py`、`yolo_final_mjpeg_old.py`
- 建立完整 `README.md`

## 本輪檔案

已修改：

- `mjpeg_yolo_minimal.py`
- `webrtc_yolo_minimal.py`

已新增：

- `minimal_camera_control.py`
- `minimal_control_ui.py`
- `yolo_final_mjpeg.py`
- `yolo_final_old.py`
- `yolo_final_mjpeg_old.py`
- `README.md`

## Python 環境

環境位置：

```text
.venv
```

啟用：

```bash
source .venv/bin/activate
```

主要已安裝版本：

- Python 3.10.12
- OpenCV 5.0.0
- Ultralytics 8.4.108
- aiohttp 3.14.3
- aiortc 1.15.0
- PyAV 17.1.0
- pyserial 3.5
- pynmea2 1.19.0

虛擬環境以 `--system-site-packages` 建立，原因是 Ubuntu 的 PyGObject／
GStreamer GI bindings 由系統套件提供。`uv` cache 在受限環境中需使用
可寫位置，例如 `/tmp/uv-cache`。

## 實機與相機能力

> 本節為先前實機驗證紀錄，暫時保留原始軟硬體版本與測試結果，尚未
> 全部在目前的 Jetson Orin NX 上重跑。

相機：

```text
Model: DFK AFU130-L53
Serial: 26410280
USB ID: 199e:8457
```

軟體：

- Linux 6.8 / Ubuntu 22.04
- tiscamera／tcambin 0.14.0
- GStreamer 1.20.3
- V4L2 `uvcvideo`

已確認格式：

| 解析度 | FPS |
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

目前 GUI 提供上述常用格式及 4128×3096。選擇 4128×3096 時強制
1 FPS；切回其他解析度時若仍是 1 FPS，會恢復 30 FPS。

實際取得的 frame：

```text
V4L2 4128×3096 @ 1 FPS -> (3096, 4128, 3)
tcambin 4128×3096 @ 1 FPS -> (3096, 4128, 3)
V4L2 1280×720 @ 25 FPS -> (720, 1280, 3)
tcambin 1280×720 @ 25 FPS -> (720, 1280, 3)
```

## Minimal 相機架構

CLI 保留：

```text
--camera-source opencv
--camera-source tiscamera
```

Linux 的 `opencv` 模式現在由共用控制層明確使用：

```text
cv2.VideoCapture(index, cv2.CAP_V4L2)
```

GUI 顯示名稱為 `V4L2`。

tiscamera 模式：

```text
tcambin name=camera_source
  -> BGRx
  -> videoconvert
  -> BGR
  -> appsink
  -> NumPy
  -> YOLO
```

`tcambin` 需載入 `Gst 1.0` 及 `Tcam 0.1` GI namespace，否則 Python
物件不會出現 `get_tcam_property_names()` 與
`set_tcam_property()`。

## 相機控制 GUI

兩個 minimal 共用 `minimal_camera_control.py` 與
`minimal_control_ui.py`。

控制項：

- 來源：V4L2、tiscamera／tcambin
- 解析度
- FPS
- 曝光時間
- 亮度
- ATR 對比
- 飽和度
- 增益
- 銳利度
- One Push Focus

各數值控制都有獨立的「預設」與「套用」：

| 控制 | 預設值 |
|---|---:|
| 解析度 | 1920×1080 |
| FPS | 30 |
| 曝光時間 | 33333 µs |
| 亮度 | 0 |
| ATR 對比 | 64 |
| 飽和度 | 32 |
| 增益 | 100 |
| 銳利度 | 8 |

「預設」只填欄位，不送出設定；必須再按「套用」。

面板：

- 固定在網頁右側
- 預設關閉
- 以 `transform: translateX(100%)` 收合到視窗右側之外
- 保留箭頭按鈕開關
- 透明度 0.6
- 欄位可縮小，窄螢幕自動換行

## 控制映射與實測

| GUI | V4L2 | tiscamera |
|---|---|---|
| 曝光 | `exposure_time_us` | `Exposure Time (us)` |
| 亮度 | `brightness` | `Brightness` |
| 對比 | `atr_contrast` | `ATR Contrast` |
| 飽和度 | `saturation` | `Saturation` |
| 增益 | `gain` | `Gain` |
| 銳利度 | `sharpness` | `Sharpness` |
| One Push Focus | `auto_focus_one_push` | `Auto Focus One Push` |

已在兩套來源逐項寫入並讀回。亮度另做了可觀察的
`0 → 1 → 0` 測試，兩套來源均讀回正確。測試後已恢復亮度 0、
自動曝光與自動增益。

注意：

- 手動設定曝光會關閉 `auto_shutter`／`Exposure Auto`
- 手動設定增益會關閉 `gain_auto`／`Gain Auto`
- One Push Focus 是一次性動作，沒有完成狀態可讀，只能確認命令被接受
- 屬性讀回一致不代表肉眼一定能看到明顯差異

## 來源與格式切換

`CameraManager` 使用 reentrant lock 序列化：

- camera read
- V4L2／tcambin 切換
- 解析度與 FPS pipeline 重建
- 控制寫入與讀回

已實測執行中：

```text
V4L2 -> tiscamera -> V4L2
```

切換後均能繼續取像。解析度與 FPS 會關閉目前來源、建立新來源；若建立
失敗，會嘗試恢復原來源。

tcambin `try-pull-sample` 的等待上限目前為 5 秒。這是最大等待時間；
正常取得 frame 時會立即返回。

## 串流驗證

四組均已通過：

| 程式 | V4L2 | tiscamera |
|---|---:|---:|
| `mjpeg_yolo_minimal.py` | 通過 | 通過 |
| `webrtc_yolo_minimal.py` | 通過 | 通過 |

MJPEG：

- `/` HTTP 200
- `/video_feed` HTTP 200
- 實際收到 multipart MJPEG frame
- 1920×1080 的 25 秒測試曾接收約 315 MB
- 同一 HTTP response 中切換 1920×1080 → 1280×720 → 1920×1080，
  三階段都繼續收到 frame

WebRTC：

- `/offer` HTTP 200
- aiortc offer/answer 成功
- V4L2 與 tiscamera 均實際收到 1920×1080 frame

## MJPEG 暫時斷幀恢復

原始 `mjpeg_yolo_minimal.py` 在 `camera.read()` 暫時失敗時會
`break`，導致 `/video_feed` response 永久結束，必須重整網頁。

已改為：

- 暫時失敗時保留 generator 與 HTTP response
- 每 0.1 秒重試
- 相機恢復後繼續從同一 response 傳送
- HTTP 真正中斷時，瀏覽器每 1 秒自動重連 `/video_feed`

此设计已移植到 `yolo_final_mjpeg.py`。

## WebRTC 現況與痛點

aiortc 自動化客戶端的四組測試均成功，但實際瀏覽器曾出現
`WebRTC: failed`。

已確認當時：

- 只有使用者從 VS Code terminal 啟動的一個 WebRTC 程序
- 程序正常持有 `/dev/video0`
- 正常監聽 8080
- 不是先前測試殘留的孤兒程序

使用注意：

- 瀏覽器使用 `http://localhost:8080` 或 `http://127.0.0.1:8080`
- 不要瀏覽 `http://0.0.0.0:8080`
- localhost 只接收 WebRTC 不需要 HTTPS
- LAN IP、跨網段、NAT、UDP 防火牆和 ICE candidate 都可能影響連線
- 目前沒有 STUN/TURN
- 多次重新整理可能留下舊 peer connection
- 前端尚未在 `pagehide`／`beforeunload` 主動 `peer.close()`
- 後端 cleanup 目前只處理 `failed`／`closed`，應考慮
  `disconnected`

前端 `pagehide` 目前已主动 `peer.close()`，后端也会处理
`disconnected`；STUN/TURN 与实际浏览器网络环境仍需继续验证。

## `yolo_final_mjpeg.py`

已建立 MJPEG 版本，保留：

- `yolo_final.py` 的相機來源
- YOLO TensorRT 推論
- GPS 定位
- 連續幀確認

並將 WebRTC transport 替換為 Flask multipart MJPEG。

目前它透過 import 重用 `yolo_final.py` 的 YOLO/GPS 核心類別，並已整合：

- OpenCV/V4L2
- GStreamer/v4l2src
- GStreamer/tcambin
- minimal 共用相機控制層
- 右側控制 GUI
- MJPEG 暫時斷幀重試與瀏覽器重連

## Final 三路徑實測

測試模型：

```text
yolo11s.pt
```

正式預設仍為：

```text
model/11s_car_960.engine
```

可用 `--model-path` 覆寫，不需修改程式。

六組結果：

| Final | OpenCV/V4L2 | GStreamer/v4l2src | GStreamer/tcambin |
|---|---:|---:|---:|
| WebRTC `yolo_final.py` | 通過 | 通過 | 通過 |
| MJPEG `yolo_final_mjpeg.py` | 通過 | 通過 | 通過 |

验证标准：

- GUI 含三种来源
- `/api/camera` 回报正确来源
- MJPEG 实际收到多个 multipart frame
- WebRTC offer/answer HTTP 200
- WebRTC 实际收到 1280×720 frame
- 使用 yolo11s.pt 完成推论
- tcambin 最终复测可正常关闭，无 core dump

相机的 V4L2 能力只公开 YUYV，没有 MJPEG，因此新版
GStreamer/v4l2src 使用：

```text
v4l2src
  -> video/x-raw,format=YUY2
  -> videoconvert
  -> BGR
  -> appsink
```

旧 `image/jpeg -> jpegdec/nvjpegdec` 不适用于目前 DFK AFU130-L53。
`--jpeg-decoder` 暂时仅为 CLI 相容保留。

## Final 舊版備份

- `yolo_final_old.py`：由 Git 基线精确还原
- `yolo_final_mjpeg_old.py`：还原旧 MJPEG 架构并引用
  `yolo_final_old.py`

## 已移植到兩個 `yolo_final` 的項目

本轮实际一起移植：

1. `CameraManager` 鎖與來源生命週期
2. V4L2 與 tcambin 的控制映射
3. `Tcam 0.1` GI namespace 初始化
4. 解析度／FPS 重建及失敗回復
5. 4128×3096 與 1 FPS 綁定
6. 手動曝光／增益與自動模式的相依性
7. One Push Focus 的 action 語意
8. MJPEG generator 不可因暫時斷幀而結束
9. WebRTC 切換格式時應持續提供最新 frame 或明確等待
10. WebRTC peer 的前後端 cleanup
11. STUN/TURN、UDP firewall 與實際瀏覽器 ICE 測試
12. 高解析度 frame 的 YOLO、JPEG／WebRTC 編碼效能與記憶體壓力

## 已知執行痛點

1. `uv` 預設 cache 路徑在受限環境可能不可寫，需指定
   `UV_CACHE_DIR=/tmp/uv-cache`。
2. PyGObject 通常不是純 pip 套件，venv 需看到系統 site packages。
3. Ultralytics/PyTorch 安裝量大，可能下載數 GB CUDA runtime。
4. tiscamera 0.14.0 較舊，GI 與新系統相容性需持續注意。
5. 在受限 sandbox 執行 tcambin 會因 libusb 權限失敗，實機測試需直接
   存取 USB／`/dev/video0`。
6. 同一時間通常只能有一個程序持有相機。
7. tcambin pipeline 重建的首幀可能延遲，不能把單次 timeout 當永久故障。
8. 4128×3096 的 1 FPS 會放大首幀延遲、推論時間及記憶體需求。
9. MJPEG 1920×1080 頻寬非常高，不適合低頻寬鏈路。
10. WebRTC 自動客戶端成功不代表所有瀏覽器與網路環境都成功。
11. 相機控制值可讀回不等於畫面效果已被量測驗證。
12. 強制中止 GStreamer/WebRTC 過程曾出現 native termination 訊息，
    正式版本需強化 thread join 與 pipeline shutdown 順序。

## 下一步

1. 修正 WebRTC 前端與後端 peer cleanup。
2. 以 Chrome／Firefox 實際觀察 ICE candidate 與 browser console。
3. 評估是否加入 STUN/TURN 設定。
4. 使用 TensorRT engine 重測兩個 final 的六組路徑。
5. 在 GPS 真實輸入與完整目標流程同時運作時重測所有格式。
6. 評估 4128×3096 是否應先縮放再進 YOLO，以控制延遲與記憶體。
