# Current Status

更新日期：2026-07-28

## 專案目前狀態

`mjpeg_yolo_minimal.py` 與 `webrtc_yolo_minimal.py` 目前支援兩種相機來源：

- `opencv`
- `tiscamera`

預設相機來源仍為 `opencv`。

## 已修改檔案

- `mjpeg_yolo_minimal.py`
- `webrtc_yolo_minimal.py`

## OpenCV 相機來源

OpenCV 模式使用 `cv2.VideoCapture` 取得影像。

執行方式：

```bash
python3 mjpeg_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

```bash
python3 webrtc_yolo_minimal.py \
  --camera-source opencv \
  --camera-index 0
```

`--camera-index` 用來指定 OpenCV 相機裝置索引，預設值為 `0`。

## tiscamera 相機來源

tiscamera 模式的目標環境為：

- Linux
- tiscamera 0.14.0
- 相容的 tcamdutils 0.14.0
- GStreamer 1.0
- Python GObject introspection bindings
- NumPy

程式使用以下流程取得影像：

```text
tcambin
  -> BGRx 1920x1080 30 FPS
  -> videoconvert
  -> BGR
  -> appsink
  -> NumPy
  -> OpenCV / YOLO
```

GStreamer 本身不是 Linux 專用，但目前使用的
`tiscamera 0.14.0 + tcambin` 相機路徑限制在 Linux。

程式不依賴 OpenCV 的 GStreamer backend，而是透過 PyGObject
直接使用 GStreamer，取得影像後再轉成 NumPy BGR 陣列。

### 使用第一台 tiscamera 相機

```bash
python3 mjpeg_yolo_minimal.py --camera-source tiscamera
```

```bash
python3 webrtc_yolo_minimal.py --camera-source tiscamera
```

### 使用指定序號的相機

```bash
python3 mjpeg_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 12345678
```

```bash
python3 webrtc_yolo_minimal.py \
  --camera-source tiscamera \
  --tiscamera-serial 12345678
```

在 tiscamera 模式下，`--camera-index` 不會使用；相機應透過
`--tiscamera-serial` 選擇。不指定序號時，由 `tcambin` 選擇第一台相機。

## 影像設定

目前兩種來源都以以下格式為目標：

- 寬度：1920
- 高度：1080
- 幀率：30 FPS
- YOLO 模型：`yolo11s.pt`

實際可用的解析度、幀率和像素格式仍取決於相機型號與驅動支援。

## 已完成驗證

由於目前開發環境沒有 Linux 和 tiscamera 相機，現階段只完成靜態驗證：

- 兩個 Python 檔案皆通過 AST 語法解析
- `--camera-source` 接受 `opencv` 和 `tiscamera`
- `--tiscamera-serial` 已加入兩個程式
- 兩個程式會產生相同的 `tcambin` GStreamer 管線
- 已檢查有指定和未指定相機序號的管線內容

## 尚未完成驗證

以下項目需要在 Linux 實機上驗證：

- tiscamera 0.14.0 是否正確安裝
- `tcambin` 是否可由 GStreamer 找到
- tcamdutils 0.14.0 是否可由 `tcambin` 使用
- PyGObject 是否能載入 `Gst 1.0`
- 相機是否支援 1920x1080、30 FPS、BGRx 輸出
- 未指定序號時是否正確開啟第一台相機
- 指定序號時是否正確選擇相機
- MJPEG 串流是否正常
- WebRTC 串流是否正常
- YOLO 推論效能是否能維持需求幀率
- 程式結束時 GStreamer pipeline 是否正常釋放

## Linux 實機建議檢查

確認 tiscamera 元件：

```bash
gst-inspect-1.0 tcambin
```

確認相機能透過 GStreamer 取像：

```bash
gst-launch-1.0 \
  tcambin \
  ! video/x-raw,format=BGRx,width=1920,height=1080,framerate=30/1 \
  ! videoconvert \
  ! autovideosink
```

如果需要指定序號：

```bash
gst-launch-1.0 \
  tcambin serial="12345678" \
  ! video/x-raw,format=BGRx,width=1920,height=1080,framerate=30/1 \
  ! videoconvert \
  ! autovideosink
```

確認 Python GStreamer bindings：

```bash
python3 -c \
  'import gi; gi.require_version("Gst", "1.0"); from gi.repository import Gst; print("GStreamer Python OK")'
```

## 已知風險

1. 相機可能不支援目前指定的 1920x1080、30 FPS 或 BGRx 格式。
2. tcamdutils 未安裝或版本不相容時，BGRx 轉換可能失敗。
3. Linux Python 虛擬環境可能找不到系統安裝的 `gi`。
4. tiscamera 0.14.0 屬於舊版本，系統 GStreamer 或作業系統版本可能造成相容性問題。
5. 目前尚未取得 GStreamer bus error 的詳細訊息；首次實機測試後可能需要補強錯誤輸出。
6. WebRTC 與 YOLO 同時執行時，實際效能需要依硬體重新評估。

## 下一步

取得 Linux 與相機環境後，依序進行：

1. 使用 `gst-inspect-1.0 tcambin` 確認插件。
2. 使用 `gst-launch-1.0` 單獨測試相機取像。
3. 測試 `mjpeg_yolo_minimal.py` 的 tiscamera 模式。
4. 測試 `webrtc_yolo_minimal.py` 的 tiscamera 模式。
5. 記錄實際相機支援的解析度、幀率及像素格式。
6. 根據實機結果調整 GStreamer pipeline 和錯誤處理。
