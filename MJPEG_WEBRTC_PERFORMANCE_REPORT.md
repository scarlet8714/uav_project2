# `mjpeg_yolo_minimal.py` 與 `webrtc_yolo_minimal.py` 效能比較

測試日期：2026-08-05（Asia/Taipei）  
測試主機：NVIDIA Jetson Orin NX，Jetson Linux R36.5.0，aarch64，Python 3.10.12  
測試輸入：GENERAL WEBCAM（UVC，`/dev/video0`），1920×1080、MJPEG、30 FPS  
模型：`yolo11s.engine`（TensorRT，約 21 MiB）

## 結論摘要

若目前目標是低網路流量、瀏覽器即時顯示及之後跨網路使用，建議以 WebRTC 為主；若目標是程式最簡單、方便除錯、擷取每一張已推論 JPEG，MJPEG 較直觀。

不過，現有 WebRTC 程式有兩個會讓表面數字失真的問題：

1. 收到的 30～38 FPS 不代表有 30～38 張新的 YOLO 結果。YOLO 背景執行緒約只能產生 14 FPS 的新結果，WebRTC track 會重複送出最新一張。
2. track 的排程起點早於 SDP/ICE 協商完成，連線後會短暫「追趕」，本機測得約 38 FPS。它是排程追趕，不是相機或推論效能。

在本次 1080p webcam 實測中：

| 指標 | MJPEG | WebRTC | 判讀 |
|---|---:|---:|---|
| Client 收到 FPS | **13.74** | 38.14（追趕期） | WebRTC 數字包含重複影格，不能直接當有效 YOLO FPS |
| 有效新 YOLO 結果上限 | 約 14.25 FPS | 約 14.25 FPS | 同相機、同 engine；瓶頸基本相同 |
| 傳輸量 | **38.55 Mb/s** | **1.14 Mb/s** | WebRTC 約少 97.0% |
| Server CPU | **64.6%** | 203.9% | 100% 代表一個 CPU core；WebRTC 軟體編碼明顯較重 |
| Server RSS | **1254.6 MiB** | 1451.2 MiB | WebRTC 約多 196.6 MiB |
| RTP 丟包（localhost） | 不適用 | 0 / 1089 packets | 只代表本機回環，不代表 Wi-Fi/Internet |
| WebRTC offer 至首幀 | 不適用 | 10.29 秒 | 本機仍出現兩端 ICE gathering 等待，需優化 |
| 系統輸入功耗 | 約 6.3～6.5 W | 無 client 約 6.3 W；本機收流約 8.3～8.5 W | WebRTC 收流值包含同機 client 解碼，不能視為純 server 功耗 |

因此，WebRTC 的主要收益是頻寬和網路傳輸能力；代價是 CPU、記憶體、協商複雜度和目前偏長的首幀時間。兩者目前都沒有提升「新 YOLO 結果」的產生速率。

## 測試環境

### 硬體與系統

- NVIDIA Jetson Orin NX Engineering Reference Developer Kit
- Linux `5.15.185-tegra`
- 可用 CUDA 裝置：`Orin`，1 個
- RAM：7607 MiB
- 測試時只有 4 個 CPU core online，另 2 個顯示 `off`
- webcam：`GENERAL WEBCAM`，序號 `JH0319_20210712_v101`
- webcam USB 路徑：`usb-3610000.usb-2.1`

### Python／影像套件

- Python 3.10.12
- Ultralytics 8.4.87（`requirements.txt` 寫 8.4.108，實際環境與鎖定版本不一致）
- OpenCV 5.0.0
- aiortc 1.15.0
- PyAV 17.1.0
- aiohttp 3.14.3
- Flask 3.1.3
- NumPy 1.26.1（`requirements.txt` 寫 2.2.6，實際環境與鎖定版本不一致）
- PyTorch 2.8.0，CUDA 12.6

版本不一致會降低重現性；正式比較前應先固定 `.venv` 與 `requirements.txt` 的同一組版本。

### webcam 實際能力

相機在 1920×1080 @ 30 FPS 只提供 MJPEG；YUYV 最高只到 640×480 @ 30 FPS。因此這次兩支程式的 OpenCV backend 都是：

```text
webcam MJPEG → USB → OpenCV/libjpeg 解碼成 BGR → YOLO TensorRT
```

MJPEG server 還會再執行一次：

```text
BGR 標註影像 → cv2.imencode JPEG → HTTP multipart
```

WebRTC server 則會執行：

```text
BGR 標註影像 → PyAV/aiortc 視訊編碼 → RTP/UDP
```

aiortc 此環境宣告 VP8 與 H.264；測試 client 使用預設 codec 順序，VP8 排在最前。正式部署應在 SDP/`getStats()` 明確記錄實際協商 codec，不要只依賴預設順序。

## 測試方法

1. 直接執行原始 `mjpeg_yolo_minimal.py` 或 `webrtc_yolo_minimal.py`，沒有修改其串流或模型邏輯。
2. 使用同一台 Jetson 的 localhost client，避免外部網路抖動混入 server 比較。
3. MJPEG 暖機 60 幀，再統計 300 幀。
4. WebRTC client 真正完成 SDP、ICE、RTP、編碼與解碼，第一輪暖機 60 幀，再統計 300 幀。
5. CPU 與 RSS 用 `psutil` 讀 server process；CPU 100% 表示一個 core。
6. 網路流量以 MJPEG JPEG payload 合計，WebRTC 以 loopback interface byte counter 計算，後者包含 RTP、RTCP、ICE/DTLS 等協定開銷。
7. Jetson RAM、CPU、GPU、溫度及功耗以 `tegrastats` 每秒取樣。
8. 另用 120 個暖機後影格分解取像、推論、繪圖、JPEG 編碼耗時。

這是單次工程診斷基準，不是具信賴區間的實驗。場景內容會影響 JPEG 大小與視訊 codec bitrate；正式驗收建議每個案例至少跑 3～5 次、每次 5～10 分鐘，報告平均值、標準差與 P95/P99。

## 詳細結果

### MJPEG 端到端

量測 300 幀、21.765 秒：

| 指標 | 結果 |
|---|---:|
| 收到 FPS | 13.738 |
| 幀間隔平均 | 72.793 ms |
| 幀間隔 P95 | 76.190 ms |
| 單張 JPEG 平均 | 341.405 KiB |
| 單張 JPEG P95 | 349.622 KiB |
| payload 流量 | 38.550 Mb/s |
| server CPU 平均 | 64.589% |
| server CPU P95 | 82.8% |
| server RSS 平均 | 1254.627 MiB |

MJPEG 的每個 client 會各自呼叫 `gen_frames()`，也就各自讀相機、跑 YOLO、畫圖和 JPEG 編碼。多 client 不只是頻寬線性增加，還可能同時爭用同一相機與同一 TensorRT model；目前架構不適合直接擴充到多 viewer。

### WebRTC 端到端

第一輪量測 300 幀、7.897 秒（排除前 60 幀，但仍處於追趕行為）：

| 指標 | 結果 |
|---|---:|
| offer 開始至 client 首幀 | 10294 ms |
| client 收到 FPS | 37.863 |
| 幀間隔平均 | 26.411 ms |
| 幀間隔 P95 | 30.862 ms |
| server CPU 平均 | 203.876% |
| server CPU P95 | 251.3% |
| server RSS 平均 | 1451.204 MiB |
| RTP packets received/lost | 1089 / 0 |

第二輪 360 幀：

| 指標 | 結果 |
|---|---:|
| client 收到 FPS | 38.142 |
| loopback RX | 1.140 Mb/s |
| loopback TX | 1.140 Mb/s |
| loopback RX packets | 1173 |

38 FPS 高於程式指定的 30 FPS，原因是 `CameraVideoTrack.started_at` 在 track 建立時開始，而協商與編碼啟動較晚；`recv()` 發現 `target_time` 已落後便不 sleep，直到追上時鐘。這個數字不可作為真正穩態 FPS。

WebRTC 的 `YoloCamera` 在 server 啟動後就持續取像和推論，即使沒有 viewer 也會耗用約 6.3 W；MJPEG 則只有 `/video_feed` 有 client 時才開始取像與推論。若設備常常無人觀看，這是重要的待機功耗差異。

每個 WebRTC viewer 會建立獨立 `CameraVideoTrack` 與獨立視訊 encoder，但共用同一份最新 YOLO frame。因此 viewer 增加時不會重跑 YOLO，卻仍會增加編碼 CPU 與傳出流量。相較之下，這個多 client 架構仍比目前 MJPEG 安全，但最好改成共享 encoder／SFU 或限制 viewer 數量。

### 共用 pipeline 分解

120 個暖機後影格：

| 階段 | 平均 | P50 | P95 |
|---|---:|---:|---:|
| webcam `read()`（含 MJPEG 解碼） | 12.819 ms | 12.808 ms | 13.071 ms |
| YOLO `model(...)` | 37.324 ms | 40.898 ms | 41.962 ms |
| `results[0].plot()` | 2.482 ms | 2.711 ms | 2.943 ms |
| `cv2.imencode('.jpg')` | 17.570 ms | 17.611 ms | 17.800 ms |
| 串行合計 | 70.196 ms | — | — |
| 串行理論 FPS | 14.246 FPS | — | — |

最後一幀 Ultralytics 內部分解為 preprocess 4.754 ms、TensorRT inference 30.501 ms、postprocess 4.773 ms。MJPEG 實測 13.74 FPS 很接近 14.25 FPS 理論值。

### 系統功耗與溫度

- 無工作基線約 4.64 W。
- MJPEG 收流期間約 6.23～6.51 W，GPU 取樣呈脈衝式 0～99%，最高 junction 約 50.1°C。
- WebRTC server 即使沒有 client，因背景 YOLO 持續工作約 6.23～6.51 W。
- WebRTC 本機 client 真正開始編碼／解碼後，整機多數樣本約 8.27～8.46 W，junction 約 52.1～52.9°C。

WebRTC 的 8 W 數字同時包含 server 軟體編碼與同機 client 軟體解碼，不能拿來當遠端瀏覽器情境的純 Jetson server 功耗。純 server 功耗應用另一台實體 client 重測。

## 延遲、品質與可靠性

### 延遲

本次沒有 LED、螢幕時間碼或高速相機，因此無法嚴謹量測 glass-to-glass latency。僅量到 WebRTC offer 至首幀 10.29 秒。可能由 client 與 server 的 ICE gathering 等待各約數秒疊加而成，應以瀏覽器 DevTools 與 aiortc timestamp 再驗證。

一般預期 WebRTC 在網路壅塞下會主動調整 bitrate、丟棄過時畫面，互動延遲通常優於無回饋控制的 MJPEG；但這是協定特性推論，不是本次 glass-to-glass 實測結果。

### 影像品質

- MJPEG 每一張都是獨立 JPEG，移動物體不會有長 GOP 擴散，但本次平均高達 341 KiB/幀。
- WebRTC 約 1.14 Mb/s，利用幀間壓縮大幅降頻寬；快速移動、螺旋槳振動、細小遠距目標或大量樹葉可能產生 block/artifact。
- YOLO 在 server 編碼前已完成，因此瀏覽器端壓縮 artifact 不會反過來影響這兩支程式的 YOLO 偵測結果。
- 若未來改成相機端或遠端壓縮後才做 YOLO，必須另外測 mAP／precision／recall，不可沿用本次結論。

### webcam 可靠性問題

兩支程式及分解測試都持續出現：

```text
Corrupt JPEG data: ... extraneous bytes before marker 0xd9
```

警告來自 webcam MJPEG 解碼路徑，兩個傳輸方案都有，不是 MJPEG HTTP protocol 專屬問題。可能原因包含 webcam firmware、UVC payload、USB 傳輸或 JPEG decoder 容忍度。應進行至少 30 分鐘壓力測試並統計：

- 警告次數
- `camera.read()` 失敗次數
- 畫面破損／綠屏次數
- USB reset、`dmesg` UVC 錯誤
- frame timestamp 是否倒退或長時間停住

## 程式架構差異與風險

| 項目 | MJPEG | WebRTC |
|---|---|---|
| YOLO 執行時機 | 有 `/video_feed` client 才跑 | server 啟動即持續跑 |
| 推論／client | 每個 client 各跑一次 | 所有 client 共用最新 YOLO frame |
| 編碼／client | 每個 client 各 JPEG 編碼 | 每個 peer 各視訊編碼 |
| 沒有 client 時功耗 | 低，但相機已開啟 | 高，仍持續取像與 YOLO |
| 壅塞控制 | 無 | 有 WebRTC feedback／bitrate control |
| NAT／Internet | HTTP 容易穿透，但頻寬大 | 需 ICE/STUN/TURN，適合互動串流 |
| 單幀擷取 | 容易 | 需解碼視訊 |
| 安全性 | 現況 HTTP 明文 | media 有 DTLS-SRTP，但 signaling 頁面仍應使用 HTTPS |

另外，兩支程式的 YOLO 參數不完全相同：WebRTC 明確使用 `conf=0.4`，MJPEG 使用 Ultralytics 預設 confidence。這可能改變後處理與標註內容；嚴格 A/B test 應統一 confidence、IoU、imgsz 和 max_det。

## 換工業相機後，哪些結果可以沿用

可以大致沿用：

- WebRTC 比逐幀 JPEG 更省網路頻寬的方向性結論。
- YOLO engine 本身的推論時間量級（前提是解析度、preprocess、engine、Jetson power mode 都不變）。
- WebRTC 每 client 額外編碼、MJPEG 現況每 client 額外整條 pipeline 的架構差異。

不能直接沿用：

- `camera.read()` 的 12.82 ms。
- JPEG 大小、MJPEG 的 38.55 Mb/s。
- 實際新鮮畫面 FPS、端到端延遲、掉幀率。
- USB 頻寬、CPU 色彩轉換成本、警告和可靠性。
- 曝光時間造成的 sensor latency、rolling/global shutter 差異。

## 工業相機重測計畫

### 先固定工業相機條件

記錄以下資訊，否則前後結果不可比較：

- 廠牌、型號、serial、firmware、driver/tiscamera 版本
- USB3／GigE／MIPI CSI 介面與實際 link speed
- pixel format：Bayer、BGRx、YUY2、Mono8、MJPEG 等
- 實際協商 width、height、FPS，不只記 requested value
- exposure、gain、auto exposure、white balance
- trigger mode：free-run／software／hardware trigger
- sensor timestamp、host arrival timestamp、是否 PTP
- rolling shutter／global shutter、曝光時間
- Jetson `nvpmodel` 模式與 `jetson_clocks` 狀態
- WebRTC 實際 codec、profile、bitrate、keyframe interval

若使用目前 tiscamera 軟體路徑：

```text
tcambin → BGRx → videoconvert → BGR → NumPy
```

需特別量 `videoconvert` CPU。若相機輸出 YUY2，另比較專案中的 VIC `nvvidconv` HW 版本。若相機是 Bayer，應比較相機 ISP、CPU debayer、CUDA/VPI debayer；它們可能比串流協定差異更大。

### 建議測試矩陣

每個組合至少 3 次、每次 5～10 分鐘：

| 維度 | 建議值 |
|---|---|
| 解析度／FPS | 1920×1080@30；工業相機目標模式；最高模式 |
| 相機 backend | OpenCV；tiscamera；可用時 VIC/HW pipeline |
| 傳輸 | MJPEG；WebRTC VP8；WebRTC H.264 |
| client 數 | 0、1、2、4 |
| 網路 | localhost；有線 LAN；實際 Wi-Fi；需要時 Internet/TURN |
| 場景 | 靜態；人車緩動；高速移動；低光高 gain；大量細節 |
| 運行時間 | 5～10 分鐘效能；30～60 分鐘 soak test |

### 每次必收指標

- sensor／capture／YOLO complete／encode／client render timestamp
- 新鮮幀 FPS，而不是只算傳送或解碼 FPS
- capture drop、inference drop、encode drop、RTP packet loss
- 平均、P50、P95、P99 latency 與 jitter
- CPU 每 core、GPU、VIC／NVENC 使用率
- process RSS、系統 RAM、swap
- `VDD_IN` 平均／P95／峰值、GPU/CPU 溫度、是否降頻
- 實際 bitrate、frame size、keyframe size
- YOLO precision／recall 或至少固定影片的 detection 一致性
- 斷線重連、拔插相機、格式切換、曝光切換後恢復時間

### 嚴謹端到端延遲量法

推薦使用 Arduino／GPIO 控制 LED，讓 LED 與 frame ID／時間碼同步，另一台高速相機同時拍攝實體 LED與 client 螢幕。分別測：

```text
曝光開始 → host capture → YOLO 完成 → encoder → 網路 → decoder → browser render
```

只有 server timestamp 無法包含 sensor exposure、browser queue 與螢幕 refresh latency。

## 優先改善建議

1. **先定義「有效 FPS」**：在相機 frame 進入時加遞增 `frame_id` 和 timestamps，傳到標註或 metadata；client 統計 unique frame ID，避免把重複幀當效能。
2. **修正 WebRTC 追趕**：在第一次 `recv()` 或 peer connected 時設定 `started_at`，若落後就重設時基，不要 burst catch-up。
3. **統一 YOLO 參數**：兩支都明確設定相同 `conf`、`iou`、`imgsz`、`max_det`。
4. **MJPEG 改共享 producer**：相機＋YOLO＋JPEG 只跑一份，client 只訂閱最新 JPEG；避免每 client 重跑推論。
5. **WebRTC viewer-aware**：無 viewer 時暫停 YOLO，或保留低頻預覽，降低約 1.7 W 的待機增量。
6. **明確選 codec**：Jetson 上比較 VP8 軟編碼、H.264 軟編碼與可整合的硬體 H.264 encoder；目前 Python aiortc/PyAV 路徑不應假設已使用 Jetson NVENC。
7. **縮短 ICE 首幀**：記錄 client offer、server answer、ICE connected、首 RTP、首 decode 時間；LAN-only 可使用 non-trickle ICE 的合理 timeout，正式跨網則配置 STUN/TURN 與 trickle ICE。
8. **處理 webcam JPEG 警告**：換 USB port/cable、看 `dmesg`、用 GStreamer/v4l2 單獨 soak test，確認換工業相機後是否消失。
9. **固定效能模式**：所有正式數據都記錄 `nvpmodel`、online cores、clock 與散熱；本次只有 4 cores online，換模式會明顯改變 WebRTC 軟編碼結果。

## 最終選型

- **單一 LAN viewer、重視簡單與逐幀 JPEG**：MJPEG 可用，但 1080p 約 38.6 Mb/s，而且目前只有約 13.7 FPS。
- **Wi-Fi／多 viewer／遠端操作／重視頻寬與低延遲**：選 WebRTC；本次約 1.14 Mb/s，但應先修正追趕、首幀等待和無 viewer 仍推論問題。
- **工業相機正式部署**：傾向 WebRTC + 共享 YOLO producer + Jetson 硬體 H.264 編碼；相機端優先選能避免 CPU `videoconvert`／debayer 的 pipeline。這是下一階段建議架構，仍須用實際工業相機、實際 pixel format 和遠端 client 驗證。

本次最關鍵的判斷是：**傳輸方面 WebRTC 明顯勝出；目前有效 YOLO 更新率方面兩者沒有本質差異，約受限在 14 FPS；WebRTC 顯示的高 FPS 主要是重複最新結果及排程追趕。**
