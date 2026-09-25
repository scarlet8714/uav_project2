# RTSP 直傳 + YOLO/GPS

從專案根目錄啟動：

```bash
python -m rtsp_yolo_direct \
  --rtsp-url rtsp://192.168.144.135/live \
  --model-path yolo11s.engine
```

開啟 `http://<jetson-ip>:8080/`。測試時可用 `--port` 改變連接埠；
若 GPS 尚未接上，可加 `--no-gps`。來源預設使用 UDP，亦可指定
`--transport tcp`。健康狀態在 `/api/health`，每次執行的事件紀錄位於
`diagnostics/direct_<時間>/events.jsonl`，五張截圖位於同目錄的
`captures/`。影片預設用 150 ms 的送出緩衝依來源 PTS 均勻送出，
以吸收每秒關鍵影格造成的接收空檔；可用 `--playout-delay-ms 0`
關閉，或指定其他毫秒數進行比較。

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

模組分工：

| 檔案 | 職責 |
| --- | --- |
| `config.py` | 命令列及相機投影參數 |
| `source.py` | RTSP 接收、封包分流、Jetson 硬體解碼與斷線重連 |
| `codec.py` | 根據來源 SPS 協商 H.264 profile |
| `inference.py` | YOLO、連續影格確認、GPS 配對與截圖 |
| `gps.py` | 從根目錄 `gps_geolocation.py` 複製的 GPS 讀取與座標投影 |
| `capture.py` | 非同步五張截圖 |
| `server.py` | WebRTC 訊號、單一觀看連線、看門狗、健康狀態及事件紀錄 |
| `web.py` | 瀏覽器自動重連與 Canvas 顯示 |

GPS 的 `gps_age_ms` 是以影格和 GPS 訊息抵達 Jetson 的 monotonic 時間
計算，不是攝影機曝光與 GPS 測量的硬體時間差。GPS 沒有有效 fix 時仍可
播放與偵測，但不顯示目標經緯度。地理位置的精度仍受固定 AGL、FOV、
COG 與機身 yaw 差異等限制。
