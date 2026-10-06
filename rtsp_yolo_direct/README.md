# RTSP 直傳 + YOLO/GPS

從專案根目錄啟動：

```bash
python -m rtsp_yolo_direct \
  --rtsp-url rtsp://192.168.144.135/live \
  --model-path test2.engine
```

預設模型為 `test2.engine`，可省略 `--model-path`，或用該參數指定其他模型。
開啟 `http://<jetson-ip>:8080/`。測試時可用 `--port` 改變連接埠；
若 GPS 尚未接上，可加 `--no-gps`。GPS 預設使用固定裝置路徑 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`，
可用 `--gps-port` 指定其他路徑。來源預設使用 UDP，亦可指定
`--transport tcp`。健康狀態在 `/api/health`，每次執行的事件紀錄位於
`diagnostics/direct_<時間>/events.jsonl`，五張截圖位於同目錄的
`captures/`。影片預設用 150 ms 的送出緩衝依來源 PTS 均勻送出，
以吸收每秒關鍵影格造成的接收空檔；可用 `--playout-delay-ms 0`
關閉，或指定其他毫秒數進行比較。

前端每秒檢查影片進度：WebRTC 連線成功後 10 秒仍沒有第一張畫面，
或播放中連續 5 秒沒有新畫面，就關閉該連線並自動重連。支援
`requestVideoFrameCallback` 的瀏覽器以實際顯示影格判斷；不支援時
以 `framesDecoded` 的增量判斷。背景分頁暫停此檢查，返回前景後
重新給予 10 秒等待第一張畫面，避免瀏覽器節流造成誤判。
重連等待按 1、2、4、8 秒遞增，收到新畫面後才重設為 1 秒。
此檢查不依賴 YOLO 或 GPS 結果，且維持原本的單一觀看連線行為。
逾時值位於 `web.py` 的 `FIRST_FRAME_TIMEOUT_MS`／`VIDEO_STALL_TIMEOUT_MS`。

啟動串流的終端機現在會印出模型、傳輸方式、緩衝設定與事件紀錄路徑，
之後每 5 秒印一行 `STATUS`：

- `RTSP`：連線、接收封包數、距最後收包的秒數及重連次數。
- `decode`：Jetson 解碼影格數與距最後解碼的秒數。
- `YOLO`：推論 FPS、最近一次處理耗時、結果年齡、待處理佇列與丟幀數。
  `dropped` 是佇列被新影格替換的數量；隔兩幀推論的跳過數另存在
  `/api/health` 的 `skipped_frames`，這些都不是網路丟包數。
- `GPS`：配對結果，例如 `valid`、`invalid_fix`、`no_course`。
- `WebRTC`：觀看連線數、每條連線的 connection／ICE 狀態、RTP
  送出數、距最後送出的秒數、影片佇列，以及是否等待關鍵影格。

連線建立／關閉、來源重連、影片佇列溢位、解碼／推論／送出錯誤與
伺服器關閉會立即印出事件和原因，例如
`peer_closing reason=superseded_by_new_offer`。每秒的完整取樣仍寫入
`events.jsonl`，不逐秒刷終端機。`/api/health` 同步增加上述狀態、
thread 存活、目前設定及最近 16 次連線關閉時的快照；`health_sample`
也會保存每條 peer 的資料。RTP 影片與 RTCP 控制封包分開計數，
RTCP 不會刷新影片送出時間。

追蹤模式預設為 `--tracker legacy`，保留原本的中心距離配對與累計兩次
確認規則。啟用 ByteTrack 時，在原啟動命令加上 `--tracker bytetrack`：

```bash
python -m rtsp_yolo_direct --model-path test2.engine --tracker bytetrack
```

切回原模式時重新啟動並移除該參數，或指定 `--tracker legacy`。
這是啟動參數開關，沒有加入瀏覽器即時切換。
`/api/health` 的 `yolo.tracker` 及 `tracker_selected` 事件會記錄模式。
ByteTrack 模式使用 0.1 的偵測門檻來延續既有軌跡；高信心配對與新軌跡
門檻為 0.3，仍須累計兩次至少 0.3 的有效配對才確認目標。
不輸出只有預測、沒有當次偵測配對的框。
`--bytetrack-buffer 5` 為預設，單位是實際 YOLO 更新次數，並非影片影格
或秒數；隔幀推論與丟棄舊影格會影響其對應的時間。
ByteTrack 在來源 generation 改變、PTS 倒退／重複或兩次處理影格的 PTS
差超過 1 秒時重置 ID 與確認累計。它沒有啟用外觀重識別或相機運動補償，
也不能保證目標交錯時 ID 不變。新軌跡可能需要後續配對才出現在輸出中。
依賴既有 Ultralytics 與 `lap>=0.5.12`（本機已安裝 0.5.13）。

修改前的完整模組備份：
[`diagnostics/rtsp_yolo_direct_before_bytetrack_20261003.zip`](../diagnostics/rtsp_yolo_direct_before_bytetrack_20261003.zip)。

資料路徑：

```text
RTSP H.264 ── source.py ── 壓縮封包 ── WebRTC <video>
                   └────── Jetson NVDEC ── inference.py ── Canvas 框/GPS
```

`source.py` 只建立一條 RTSP 連線，封包依來源 PTS 同時送往 WebRTC 和
Jetson 解碼器。YOLO 每 2 個解碼影格提交 1 個，並使用容量 1 的獨立佇列；
推論慢時只淘汰待處理的舊影格，不會卡住影片傳送。`web.py` 利用瀏覽器
影格的 RTP timestamp 還原來源 PTS，選最近一個不晚於影片影格的 YOLO
結果；未推論的中間影格沿用上一個可用結果的框。

Canvas 保留偵測框，文字只顯示兩行：class 名稱與目標經緯度（小數
7 位）。座標不可用時顯示 `--, --`。文字為粗體，實際顯示字級至少
24 px，並調整標籤位置避免超出畫面；不再繪製信心值、確認次數、
PTS、FPS 或 GPS 接收器診斷面板。影片時間對齊與逾時恢復持續運作。

`test2.engine` 的固定配色如下，框與文字使用相同 class 顏色：

| Class | 顏色 |
| --- | --- |
| `car` | 綠 |
| `light_tactical` | 青 |
| `medium_tactical` | 黃 |
| `cm34` | 藍 |
| `amphibious_armored_vehicle` | 紫 |

新增的其他 class 會自動配置不同色相，限制在黃／綠／青／藍／紫
區間，避開紅色。

模組分工：

| 檔案 | 職責 |
| --- | --- |
| `config.py` | 命令列及相機投影參數 |
| `source.py` | RTSP 接收、封包分流、Jetson 硬體解碼與斷線重連 |
| `codec.py` | 根據來源 SPS 協商 H.264 profile |
| `inference.py` | YOLO、連續影格確認、GPS 配對與截圖 |
| `byte_tracking.py` | 可選 ByteTrack 配對、目標確認與來源重置 |
| `gps.py` | 從根目錄 `gps_geolocation.py` 複製的 GPS 讀取與座標投影 |
| `capture.py` | 非同步五張截圖 |
| `server.py` | WebRTC 訊號、單一觀看連線、看門狗、健康狀態及事件紀錄 |
| `web.py` | 瀏覽器自動重連與 Canvas 顯示 |

GPS 的 `gps_age_ms` 是以影格和 GPS 訊息抵達 Jetson 的 monotonic 時間
計算，不是攝影機曝光與 GPS 測量的硬體時間差。GPS 沒有有效 fix 時仍可
播放與偵測，但不顯示目標經緯度。地理位置的精度仍受固定 AGL、FOV、
COG 與機身 yaw 差異等限制。

GPSReader 保留最近 1024 筆導航狀態變更，YOLO 按影格的
`receive_mono_ns` 選取該時刻之前最近的一筆，位置年齡超過 2 秒、
fix 無效或缺少方向時不產生目標座標。尚無可配對歷史時回報
`no_history`，不使用影格之後的 GPS；無效 fix 和斷線也會記錄，
避免跳過失效事件沿用舊定位。

目前暫時停用 COG 的 1 m/s 速度門檻，RMC／VTG 有方向數值便可保存，
速度為零或未提供也可使用。缺少方向數值時仍維持 `no_course`。
靜止時 COG 不代表機身朝向；要恢復門檻可將 `gps.py` 的
`MIN_SPEED_FOR_COG_MPS` 設回 `1.0`。
