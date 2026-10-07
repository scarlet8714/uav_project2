# RTSP + YOLO/GPS + GCP TURN


此資料夾完整複製自 `rtsp_yolo_direct` 於 2026-10-07 的版本，再加入 GCP TURN。
RTSP、H.264 封包直傳、YOLO、兩種追蹤、GPS 歷史配對、Canvas、
健康狀態和事件紀錄全部保留。模型仍使用專案根目錄的 `test2.engine`。
本次沒有修改原版模組，也沒有啟動正式相機串流。

## TURN 設定與使用

已將你提供的帳密寫入本機 `.turn.env`（權限 `600`，由本目錄 `.gitignore` 排除）。
文件及程式碼不包含密碼；要搬到另一台 Jetson 時，需另外帶入該設定檔或設定環境變數。
設定格式見 [`.turn.env.example`](.turn.env.example)。
使用者於 2026-10-07 確認目前 TURN 帳密不會到期，無需定期更新憑證。

目前預設 `turn:104.155.197.179:3478?transport=udp`，已完成實際驗證及 relay 雙向傳輸；
同一台的 `3478/TCP` 也通過相同測試。
瀏覽器設為 `iceTransportPolicy: relay`，Jetson 的 aioice 同樣限制為 relay。
兩端都向這台 TURN 建立 allocation，形成 `Jetson → TURN → TURN → browser` 的候選路徑；
兩個 relay 都在同一台 GCP VM。沒有取得 relay 就回報錯誤並重試，不會退回 Google STUN 或直連。

網頁、`/offer` 訊號、框與 GPS 的 WebSocket 仍從 Jetson 的 Tailscale 位址存取。
影像的 TURN 目的位址使用 GCP 公網 IP；是否被其他 VPN exit node 接管仍取決於系統路由。
請先停止原版，再啟動此版，避免兩個程式同時占用相機、GPS 與 GPU。
預設網頁 port 是 **8081**，與原版的 8080 區分。

若觀看端的網路限制 UDP，可改用 TCP：

```bash
python -m rtsp_yolo_direct_with_gcp --turn-url 'turn:104.155.197.179:3478?transport=tcp'
```

`--transport tcp` 是相機 RTSP 的傳輸設定；TURN 要改用 `--turn-url`。
目前每次啟動使用一個 TURN URL；**沒有 UDP 失敗自動改用 TCP 的邏輯**。
TURN 的 TCP 選項控制客戶端到 TURN 的連線，relay 候選本身仍是 UDP；
因此 TCP 選項也不能省略 coturn relay UDP 範圍的設定。
目前未設定 `turns:`；如果需要 TLS，再提供網域、TLS port 與可驗證憑證資訊。

`/api/health` 會顯示 `settings.turn_url`、`settings.ice_transport_policy`，
以及 peer 的 `ice_pair.local_type/remote_type/relay_verified`。
連線成功時應是 `relay/relay` 和 `true`；終端機會印 `turn_relay_connected`
及 `path=relay/relay`。健康狀態和結構化事件不包含 TURN 密碼。
瀏覽器要取得 TURN 帳密才能連線，因此網頁應維持目前提供給可信任使用者的存取方式。

獨立測試（不開啟相機、GPS、YOLO）：

```bash
python -m rtsp_yolo_direct_with_gcp.check_turn --both
python -m rtsp_yolo_direct_with_gcp.check_turn --both --webrtc
```

第一個測 allocation、ICE 及五次小型雙向資料傳輸；第二個使用此版實際的
`EncodedTrack` 傳送合成 H.264 封包並解碼五張影格，驗證 ICE／DTLS／RTP。
這些測試不能取代遠端瀏覽器、真實相機碼率或長時間斷線恢復測試。

目前使用 aiortc **1.15.0**／aioice **0.10.2**。
aiortc 沒有公開的 relay policy 參數，此版在 ICE gathering 前設定 aioice 的
`_transport_policy`，並檢查取得的候選和實際路徑。升級這兩個套件後需重跑上述測試。
環境變數 `TURN_URL`、`TURN_USERNAME`、`TURN_PASSWORD` 優先於設定檔；
`--turn-url` 再優先於環境變數。

新版程式回歸測試：

```bash
python -m unittest rtsp_yolo_direct_with_gcp.test_turn rtsp_yolo_direct_with_gcp.test_metadata -v
node rtsp_yolo_direct_with_gcp/test_browser.cjs
```

## 啟動與原有功能

從專案根目錄啟動：

```bash
python -m rtsp_yolo_direct_with_gcp \
  --rtsp-url rtsp://192.168.144.135/live \
  --model-path test2.engine
```

預設模型為 `test2.engine`，可省略 `--model-path`，或用該參數指定其他模型。
開啟 `http://<jetson-tailscale-ip>:8081/`。測試時可用 `--port` 改變連接埠；
若 GPS 尚未接上，可加 `--no-gps`。GPS 預設使用固定裝置路徑 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`，
可用 `--gps-port` 指定其他路徑。來源預設使用 UDP，亦可指定
`--transport tcp`。健康狀態在 `/api/health`，每次執行的事件紀錄位於
`diagnostics/gcp_turn_<時間>/events.jsonl`。此版已移除截圖按鈕、
`/api/capture` 與截圖背景寫檔功能；先前已儲存的圖片仍保留。
影片預設用 300 ms 的送出緩衝依來源 PTS 均勻送出，
以吸收每秒關鍵影格造成的接收空檔；可用 `--playout-delay-ms 0`
關閉，或指定其他毫秒數進行比較。
2026-10-07 依使用者要求從 150 ms 提高至 300 ms，增加吸收來源送流空檔的餘裕；
設定緩衝延遲增加 150 ms，實際卡頓改善仍待觀看比較。修改預設值後需重新啟動程式；
若啟動命令已有 `--playout-delay-ms`，該參數會覆蓋預設值。

前端不再因首張畫面等待超過 10 秒，或播放中停格超過 5 秒而強制
重連；只要沒有其他斷線事件，就保留目前連線等待影格恢復。若一直
沒有畫面，可手動重整網頁。WebRTC `failed`／`closed`、RTSP 健康
狀態顯示中斷、後端確認目前 peer 已不存在，以及影像連線建立錯誤仍會
觸發整體重連。重連等待按 1、2、4、8 秒遞增，收到新畫面後才重設
為 1 秒；不支援影格 callback 時，以 `framesDecoded` 增量重設退避。
影片下方的 RTP 統計仍每秒更新，單一觀看連線行為維持原設定。

框／GPS 的 WebSocket 已改成獨立重連：斷線或建立資料連線失敗時，
按自己的 1、2、4、8 秒退避重接同一個 `/events/<peerId>`，不重送
`/offer`、不關閉 WebRTC，也不清除 RTP／PTS 基準或最近 180 筆辨識歷史。
資料連線建立超過 10 秒未完成時，只重試資料通道；連線成功後重設資料退避。
頁面會單獨顯示「框／GPS」狀態。資料仍依原本來源 PTS 差距小於 1 秒的規則
顯示；中斷太久時疊圖暫時消失，收到對齊的新資料後恢復。

後端重接時會重送同一個 RTP origin，替換舊資料佇列並處理 WebSocket 的
pong／close。舊 socket 的延遲訊息、關閉事件及整體重連後的舊健康結果會被忽略，
離開頁面則取消資料重試。Tailscale 仍承載網頁與框／GPS 資料，但資料通道
斷線本身不再重建 TURN 影片。套用此改動需重新啟動 GCP 版並重整觀看頁面。
新版頁面頂部應顯示 `GCP · 資料獨立重連 · 20261007.3`，
`/api/health` 的 `settings.frontend_revision` 也應為 `20261007.3`。
若仍出現 `Reconnecting: metadata connection closed`，先關閉所有舊觀看分頁，
重開目前服務的頁面並確認版本。後端重啟不會替換已開啟頁面的 JavaScript；
原版及舊頁面仍可能持續重送 offer，依單一觀看政策取代其他影片連線。
`peer_created` 現在記錄 `client_revision` 與 `client_reconnect_reason`；
`metadata_connected`／`metadata_disconnected` 另行記錄資料通道重接，供判讀實際觸發原因。

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
python -m rtsp_yolo_direct_with_gcp --model-path test2.engine --tracker bytetrack
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
RTSP H.264 ── source.py ── 壓縮封包 ── WebRTC ── GCP TURN ── <video>
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
| `web.py` | 瀏覽器 relay-only 連線、自動重連與 Canvas 顯示 |
| `turn.py` | 帳密載入、兩端 TURN 設定、relay 限制與候選路徑檢查 |
| `check_turn.py` | 不開相機／GPS的 TURN 與 WebRTC H.264 測試 |

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
