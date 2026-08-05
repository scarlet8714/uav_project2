# `yolo_final.py` 與 `yolo_final_hw.py` 工業相機效能報告

測試日期：2026-08-05（Asia/Taipei）  
平台：NVIDIA Jetson Orin NX、Jetson Linux R36.5.0、Python 3.10.12  
工業相機：The Imaging Source DFK AFU130-L53，serial `26410280`  
輸入：1920×1080 @ 30 FPS，YUYV 4:2:2  
模型：`11s_car_544_960.engine`，`imgsz=(544, 960)`

## 結論

兩支 final 程式均成功運行工業相機、TensorRT YOLO、連續幀確認、GPS unavailable 標註與 WebRTC。`yolo_final_hw.py` 的 `nvvidconv compute-hw=2` 已確認啟動，沒有退回軟體 `videoconvert`。

相較 `yolo_final.py`，VIC HW 版本：

- server CPU 平均由 253.56% 降至 230.75%，降低 **9.0%**。
- server CPU P95 由 298.4% 降至 287.0%，降低 **3.8%**。
- client 幀間隔 P95 由 57.66 ms 改善至 45.87 ms，降低 **20.4%**。
- server RSS 由 1409.62 MiB 增至 1482.64 MiB，多約 **73.0 MiB**。
- 本輪功耗沒有呈現硬體版節能；測試順序、溫度與畫面未完全固定，不能據此判定 VIC 比軟體路徑耗電。

| 指標 | `yolo_final.py` | `yolo_final_hw.py` | 差異 |
|---|---:|---:|---:|
| Client 收到 FPS | 27.63* | 30.45* | +10.2%* |
| 幀間隔平均 | 36.20 ms* | 32.85 ms* | -9.3%* |
| 幀間隔 P95 | 57.66 ms* | 45.87 ms* | **-20.4%*** |
| Server CPU 平均 | 253.56% | **230.75%** | **-9.0%** |
| Server CPU P95 | 298.4% | **287.0%** | -3.8% |
| Server RSS | **1409.62 MiB** | 1482.64 MiB | +73.0 MiB |
| Loopback RX bitrate | 0.573 Mb/s | 0.636 Mb/s | 場景／rate control 影響 |
| RTP packets lost | 0 / 878 | 0 / 859 | localhost 均無丟包 |
| Offer 至首幀 | 10.264 s | 10.255 s | 幾乎相同 |
| 本機 client 收流功耗 | 約 9.0～9.24 W | 約 9.24～9.51 W | 不足以作節能結論 |

\* 兩支 WebRTC 程式都有既有的啟動追趕與重複最新 YOLO frame 行為；client decode FPS 不能當成 unique capture 或 unique YOLO FPS。

目前較佳選擇是 `yolo_final_hw.py`，因為它在完整 final 功能下確實降低 CPU 並改善 client 幀間隔尾端延遲。下一階段必須加入 frame ID/timestamp 並用遠端 client 重測，才能確認真正的新 YOLO 結果率與 glass-to-glass latency。

## 測試環境與功能設定

```text
Camera: DFK AFU130-L53
Serial: 26410280
Driver: uvcvideo
Video node: /dev/video0
Metadata node: /dev/video1
Bus: usb-3610000.usb-1.1
tcambin: 0.14.0_master/031c7762_rev_3054

Model: 11s_car_544_960.engine
imgsz: 544 × 960
confidence: 0.4
IoU: 0.45
temporal confirmation: enabled
confirmation frames: 3
max missing frames: 5
output: 1920 × 1080 WebRTC
```

相機的 1920×1080 @ 30 FPS 是未壓縮 YUYV，原始資料率約 124.4 MB/s（995 Mb/s），與先前 webcam 的 MJPEG 壓縮輸入不同。

兩支程式共用 `yolo_final.py` 的 YOLO、GPS、目標座標估算、連續幀確認、標註、WebRTC、UI、相機控制及 shutdown 邏輯；刻意差異只有相機色彩轉換層。

### GPS 狀態

測試時沒有 `/dev/ttyUSB0`，所以 GPS reader 無可用 serial device。影像 pipeline 繼續執行並走 `GPS unavailable` 標註路徑。

本次有覆蓋 GPS reader 無資料容錯、YOLO、temporal confirmation、GPS unavailable 標註和 WebRTC；沒有覆蓋 NMEA 解析、有效定位、目標 GPS 座標計算及 GPS serial I/O 負載。

## 實際 pipeline

### `yolo_final.py`

```bash
python yolo_final.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

```text
tcambin YUYV
→ BGRx
→ videoconvert（CPU）轉 BGR
→ appsink max-buffers=1 drop=true
→ YOLO TensorRT 544×960
→ temporal confirmation／GPS unavailable／標註
→ aiortc/PyAV 視訊編碼
→ RTP/WebRTC
```

### `yolo_final_hw.py`

```bash
python yolo_final_hw.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

```text
tcambin YUY2
→ queue max-size-buffers=1 leaky=downstream
→ nvvidconv compute-hw=2（Jetson VIC）轉 BGRx
→ BGR channel removal + NumPy copy
→ YOLO TensorRT 544×960
→ temporal confirmation／GPS unavailable／標註
→ aiortc/PyAV 視訊編碼
→ RTP/WebRTC
```

`--jpeg-decoder` 顯示為 `jpegdec`，但兩個 tiscamera pipeline 都是 raw video，不經 JPEG，此參數在本測試沒有作用。

HW 版本只加速 YUY2→BGRx；WebRTC encoder 仍由 aiortc/PyAV 負責，沒有使用 `nvv4l2h264enc`。網頁和 server 也沒有強制 H.264。本次 client 預設 codec 順序以 VP8 為先，因此應視為預設 VP8 軟體編碼測試。

## 測試方法

1. 每次只啟動一個 server，使用相同相機、serial、解析度、FPS、engine 與 final 設定。
2. 同一台 Jetson 的 aiortc client 完成 SDP、ICE、DTLS、RTP 與解碼。
3. 收到 360 個 decode frame，丟棄前 60 個，統計後 300 個。
4. server CPU/RSS 由 `psutil` 取得；CPU 100% 代表一個 core。
5. WebRTC 流量由 loopback counters 量測，包含 RTP/RTCP/DTLS/ICE 開銷。
6. RTP loss 由 aiortc inbound stats 取得。
7. 功耗、CPU per-core、GPU、RAM、溫度由 `tegrastats` 每秒取樣。
8. 另建立 450-frame client 負載供功耗取樣。

這是單次短時間工程比較，不是具有信賴區間的正式 benchmark。影像內容、溫度、clock、相機自動曝光與測試順序會影響結果。

## 詳細結果

### `yolo_final.py` 軟體轉換

暖機後 300 個 client frame，10.823 秒：

| 指標 | 結果 |
|---|---:|
| Client FPS | 27.626* |
| 幀間隔平均／P95 | 36.198 / 57.662 ms* |
| Server CPU 平均／P95 | 253.562 / 298.4% |
| Server RSS | 1409.621 MiB |
| Loopback RX bitrate | 0.573 Mb/s |
| 解析度 | 1920×1080 |
| RTP packets received/lost | 878 / 0 |
| Offer 至首幀 | 10263.837 ms |

`tegrastats`：無 client 但持續相機＋YOLO約 8.14～8.42 W；本機 client 真正開始編碼／解碼約 9.0～9.24 W；最高 junction 約 53.9°C。一個 CPU core 長時間達 100%。

### `yolo_final_hw.py` VIC 轉換

暖機後 300 個 client frame，9.821 秒：

| 指標 | 結果 |
|---|---:|
| Client FPS | 30.446* |
| 幀間隔平均／P95 | 32.845 / 45.874 ms* |
| Server CPU 平均／P95 | 230.748 / 287.0% |
| Server RSS | 1482.644 MiB |
| Loopback RX bitrate | 0.636 Mb/s |
| 解析度 | 1920×1080 |
| RTP packets received/lost | 859 / 0 |
| Offer 至首幀 | 10255.451 ms |

`tegrastats`：無 client 但持續相機＋YOLO約 8.96～9.60 W；本機 client 開始編碼／解碼約 9.24～9.51 W；最高 junction 約 55.5°C。

HW 測試在軟體測試之後，起始溫度較高；相機 auto exposure/gain 與畫面內容也沒有鎖定。只能說本輪未觀察到功耗下降，不能歸因為 VIC 本身更耗電。正式功耗 A/B 必須交錯測試順序並固定相機參數。

## 為何 CPU 只降低 9%

VIC 只取代 YUY2→BGRx 色彩轉換。以下仍會消耗 CPU 或記憶體頻寬：

- BGRx→BGR 的 1080p NumPy copy
- Ultralytics preprocess、TensorRT postprocess
- temporal confirmation／bbox matching
- GPS／文字／bbox 標註
- latest frame copy、BGR→VideoFrame conversion
- aiortc/PyAV 軟體視訊編碼
- 每個 WebRTC peer 的獨立 encoder

下一個大幅降低 CPU 的重點是 Jetson 硬體 H.264 encoder，以及減少 BGR buffer copy。

## WebRTC FPS 與頻寬限制

`CameraVideoTrack.started_at` 在 SDP/ICE 完成前就開始計時；約 10 秒協商後，`recv()` 會暫時不 sleep 以追趕。producer 和 sender 又是解耦的，sender 可以重複送最新一張 YOLO frame。

因此 30.45 client FPS 不代表 30.45 unique YOLO FPS，HW 高 10.2% 也不足以證明推論吞吐增加 10.2%。應在 capture 加 `frame_id`，記錄 capture、YOLO、annotation、send、RTP、client decode/render timestamps。

0.573 與 0.636 Mb/s 的差異可能來自畫面、auto exposure/gain、codec adaptation 和 keyframe 落點，不能認為 VIC 會增加 bitrate。

## 已觀察問題與後續建議

1. 修正 WebRTC `started_at` 和 burst catch-up；首幀約 10.26 秒與 VIC 無關。
2. 加入 capture `frame_id` 和全 pipeline timestamps，分開統計 capture、unique YOLO、transport FPS。
3. 使用遠端實體 client，分離 Jetson server 與 client decode 功耗。
4. 鎖定 exposure、gain、white balance 與場景，軟體／HW 交錯各跑至少 5 次、每次 5～10 分鐘。
5. 跑 30～60 分鐘 soak test，觀察 RSS、溫度、USB drop 與 RTP loss。
6. 整合 `nvv4l2h264enc` 或其他 WebRTC 可用的 Jetson 硬體 H.264 路徑。
7. 減少 BGRx→BGR、latest frame、VideoFrame 的重複 copy。
8. 接上 GPS 後另測 NMEA、有效定位、目標 GPS 計算及更新延遲。
9. 測 1、2、4 viewer；目前每個 peer 仍有獨立 encoder。
10. 記錄並固定 `nvpmodel`、online cores 與 clock；本次只有 4 CPU cores online。

## 最終選擇

目前建議：

```bash
python yolo_final_hw.py \
  --camera-backend tiscamera \
  --tiscamera-serial 26410280
```

VIC pipeline 已實際生效，server CPU 平均降低 9.0%，client 幀間隔 P95 改善 20.4%，且完整功能與 `yolo_final.py` 相同。代價是本輪 RSS 多約 73 MiB，功耗也沒有顯示下降；這兩點需用固定場景、交錯順序與長時間測試再確認。
