# RTSP 直傳 + YOLO/GPS

從專案根目錄啟動：

```bash
python -m rtsp_yolo_direct \
  --rtsp-url rtsp://192.168.144.135/live \
  --model-path test2.engine
```

預設模型為 `test2.engine`，可省略 `--model-path`，或用該參數指定其他模型。

WebRTC 已加入與 `rtsp_yolo_direct_with_gcp_stun` 相同的 STUN／TURN 路徑：
STUN `stun:104.155.197.179:3478`，TURN `turn:104.155.197.179:3478?transport=udp`。
預設 ICE 策略為 `all`，允許 Tailscale／其他直連候選與 TURN 備援；不保證斷線時無縫切換。
兩端皆使用模組內 `.turn.env` 的設定，帳密檔已排除版本控制、權限為 `600`。
網頁、offer 與框／GPS WebSocket 仍走訪問網頁的位址，TURN 只提供影片的中繼路徑。
UDP TURN 失敗時不會自動切換 TCP，可用 `--turn-url` 明確覆寫。
頁面顯示影像直連／TURN 路徑，`/api/health` 的 `peers[].ice_pair` 及事件日誌也會記錄。

可用 `--turn-config`、`--turn-url`、`--stun-url` 覆寫設定；
`--ice-transport-policy relay` 可強制 TURN 進行比較，預設維持 `all`。
不開相機與模型的 TURN 診斷：`python -m rtsp_yolo_direct.check_turn --webrtc`。

目標 GPS 使用固定姿態與平坦地面的近似投影。預設參數已更新為：

| 參數 | 預設值 |
| --- | ---: |
| `--altitude-agl-m` | 110 m（相機到地面的垂直高度） |
| `--camera-pitch-deg` | -50°（0° 水平，-90° 垂直向下） |
| `--camera-yaw-offset-deg` | 0°（畫面上方為正前方） |
| `--hfov-deg` | 49.4° |
| `--vfov-deg` | 29.7° |

投影按針孔相機近似建立視線，再依固定 pitch 旋轉並與平坦地面求交點。
以預設設定計算，畫面中心約在前方 92.3 m，上緣約 156.2 m，下緣約 51.6 m。
方位仍用 GPS COG 近似機頭方向，roll 假設為零；尚未接入即時飛控／雲台
姿態或鏡頭畸變校正。視線朝天空或地平線時保留偵測框，但不產生目標 GPS。
參數可在啟動時覆寫；已在執行的程式需重新啟動生效。

開啟 `http://<jetson-ip>:8080/`。測試時可用 `--port` 改變連接埠；
若 GPS 尚未接上，可加 `--no-gps`。GPS 預設使用固定裝置路徑 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`，
可用 `--gps-port` 指定其他路徑。來源預設使用 UDP，亦可指定
`--transport tcp`。健康狀態在 `/api/health`，每次執行的事件紀錄位於
`diagnostics/direct_<時間>/events.jsonl`。截圖按鈕、API 與背景截圖處理
已移除，既有截圖檔案保留。影片預設用 300 ms 的送出緩衝依來源 PTS 均勻送出，
以吸收每秒關鍵影格造成的接收空檔；可用 `--playout-delay-ms 0`
關閉，或指定其他毫秒數進行比較。

前端不再因首張畫面等待超過 10 秒，或播放中停格超過 5 秒而強制
重連；只要沒有其他斷線事件，就保留目前連線等待影格恢復。若一直
沒有畫面，可手動重整網頁。WebRTC `failed`／`closed`、RTSP 健康
狀態顯示中斷、伺服器確認觀看連線已不存在，以及影片連線建立錯誤
仍會觸發影片自動重連。重連等待按 1、2、4、8 秒遞增，收到新畫面後才重設
為 1 秒；不支援影格 callback 時，以 `framesDecoded` 增量重設退避。
影片下方的 RTP 統計仍每秒更新，單一觀看連線行為維持原設定。

RTSP 開啟／讀取逾時預設為 8 秒，可用 `--rtsp-timeout` 覆寫。
後端在 ICE `disconnected` 持續超過 8 秒後關閉觀看連線；監測每秒執行一次。
已執行的服務需重新啟動生效，啟動時明確指定的 RTSP 逾時仍優先使用。

框／GPS WebSocket 使用獨立的 1、2、4、8 秒重試，建立連線超過
10 秒也只重試資料通道；成功開啟後重設資料通道的退避時間。
資料斷線保留原 WebRTC、RTP origin、來源 generation 與偵測歷史，
超過 1 秒的舊框仍按原規則隱藏，不會為了框消失而重建影片。
伺服器在資料重接時重送同一個 RTP origin，舊資料連線的訊息與清理
不會干擾新連線。頁面另顯示框／GPS 連線狀態。

本次同步版本為 `20261013.turn.1`，可在頁面與 `/api/health` 的
`settings.frontend_revision` 核對。更新後需重新啟動程式並重整觀看頁面。
影片緩衝預設為 300 ms；直連設定、預設 8080 連接埠與 YOLO／GPS 對齊邏輯維持原設定。

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
7 位）。座標不可用時顯示 `--, --`。文字為粗體，實際顯示字級固定
20 px，文字不加黑底，並調整標籤位置避免超出畫面；不再繪製信心值、確認次數、
PTS、FPS 或 GPS 接收器診斷面板。影片時間對齊持續運作。

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
| `inference.py` | YOLO、連續影格確認與 GPS 配對 |
| `byte_tracking.py` | 可選 ByteTrack 配對、目標確認與來源重置 |
| `gps.py` | 從根目錄 `gps_geolocation.py` 複製的 GPS 讀取與座標投影 |
| `server.py` | WebRTC 訊號、單一觀看連線、看門狗、健康狀態及事件紀錄 |
| `web.py` | 影片與資料各自重連、Canvas 顯示與時間對齊 |

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

不啟動攝影機與模型的回歸測試：

```bash
node diagnostics/test_direct_video_timeout.cjs
python3 -m unittest rtsp_yolo_direct.test_metadata diagnostics.test_direct_backend_status diagnostics.test_direct_gps_history -v
```
