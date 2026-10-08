# RTSP + YOLO／GPS + GCP TURN + WebRTC DataChannel

本資料夾複製自 `rtsp_yolo_direct_with_gcp`，將 YOLO 偵測結果、目標 GPS 座標和
RTP origin 改為 WebRTC DataChannel。來源版本保留於原資料夾。
RTSP、H.264 封包直傳、Jetson 解碼／YOLO、追蹤、GPS 配對與 PTS 對齊沿用來源程式。

```text
網頁／POST /offer／GET /api/health
  瀏覽器 → GCP HTTPS Nginx → WireGuard → Jetson :8081

影片與框／GPS
  Jetson ←→ GCP TURN ←→ 瀏覽器
    同一條 WebRTC ICE／DTLS transport
    ├─ H.264 RTP 影片
    └─ SCTP DataChannel：RTP origin、YOLO／GPS JSON
```

網頁和 offer 仍需要現有 HTTPS／WireGuard 路徑。框／GPS 不再使用 WebSocket；
本版沒有 `/events/<peerId>` 路由。現有 Nginx 的 Upgrade 設定可保留，無需為本版新增代理路徑。

## 啟動

在專案根目錄 `/home/jetson/Desktop/uav_project2` 執行：

```bash
python3 -m rtsp_yolo_direct_with_gcp_and_datachannel \
  --host 0.0.0.0 --port 8081 --model-path test2.engine --playout-delay-ms 300
```

本版與來源版預設都使用 8081，請一次只執行一版。保留此埠號即可沿用 GCP Nginx
既有的 `10.77.0.2:8081` upstream，觀看網址為 `https://104.155.197.179/`。
登入仍使用既有 GCP 網頁帳密。關閉舊觀看分頁，再重整網頁；頂部版本應顯示
`GCP · WebRTC DataChannel · 20261008.dc1`。單一觀看政策仍會讓新 offer 取代舊 peer。

相機預設 `rtsp://192.168.144.135/live`、RTSP UDP、追蹤 `legacy`，模型使用根目錄
`test2.engine`。可加上 `--tracker bytetrack`、`--transport tcp` 或 `--no-gps`；
其餘參數見 `python3 -m rtsp_yolo_direct_with_gcp_and_datachannel --help`。

本機 `.turn.env` 已從來源版複製，權限為 600，並由 `.gitignore` 排除。
移機需另行提供設定或環境變數，格式見 [.turn.env.example](.turn.env.example)。
預設 TURN 為 `turn:104.155.197.179:3478?transport=udp`；瀏覽器與 Jetson 均強制 relay。
`--turn-url` 可覆蓋 URL；帳密沿用設定檔。

## 資料通道行為

瀏覽器在建立 offer 前建立 `metadata` 通道，protocol 為 `uav-metadata-v1`，使用
可靠、有序傳送。雙端採 `max-bundle`，後端會拒絕缺少 SCTP 或未與影片共用 transport
的 offer，避免資料另走不同 ICE 路徑。

通道開啟或重建後，後端重送同一個 RTP origin，再傳送辨識結果。辨識 JSON 保留來源
generation、PTS、影像尺寸、boxes 與 GPS 欄位。前端保留最近 180 筆資料，依來源 PTS
選擇不晚於目前影片影格的結果，差距達 1 秒時不顯示舊框。

後端只保留一筆尚未送出的最新辨識結果；送入 DataChannel 的待送資料限制為 64 KiB，
單筆 JSON 限制為 60 KiB。通道塞住時更新最新結果，排空後繼續送，避免無限累積。
已交給可靠 SCTP 的資料仍會按序重傳，嚴重丟包時可能延遲。

單獨關閉／錯誤的 DataChannel 會以 1、2、4、8 秒退避，在同一個 peer 上建立新通道，
不重送 offer、不清除影片的 RTP／PTS 基準與辨識歷史。建立通道超過 10 秒也會重試。
底層 ICE／DTLS 故障、RTSP 重連或伺服器已移除 peer，仍依既有邏輯重建整條連線。
單純等待首張畫面或停格不會觸發強制重連。

## 健康狀態與紀錄

`/api/health` 可核對：

- `settings.frontend_revision = "20261008.dc1"`。
- `settings.metadata_transport = "webrtc-datachannel"`、`bundle_policy = "max-bundle"`。
- `peers[].ice_pair.relay_verified = true`，且兩端 candidate type 都為 `relay`。
- `peers[].metadata`：通道 state、connected、buffered_amount、pending_results、
  sent_messages、dropped_detections 與 last_error。

`healthy` 仍表示來源與推論健康；觀看資料通道狀態請另看 `peers[].metadata`。
終端每 5 秒印出既有 RTSP／YOLO／GPS／WebRTC 狀態，並增加 `DC`、`DC-buffer`、
`DC-pending`、`DC-dropped`。`DC-dropped` 為應用程式淘汰／超限結果數，並非網路 lost。
事件存於 `diagnostics/gcp_datachannel_<時間>/events.jsonl`。

## 驗證

```bash
python3 -m unittest rtsp_yolo_direct_with_gcp_and_datachannel.test_metadata \
  rtsp_yolo_direct_with_gcp_and_datachannel.test_turn -v
node rtsp_yolo_direct_with_gcp_and_datachannel/test_browser.cjs
python3 -m rtsp_yolo_direct_with_gcp_and_datachannel.check_datachannel
```

已通過 26 項 Python 測試與 29 項前端測試。最後一個命令需要 TURN 網路權限，使用
合成 H.264 與模擬辨識／GPS；不開相機、GPS 裝置、YOLO 推論或正式 HTTP 服務。
2026-10-08 的實際 GCP TURN UDP 測試確認 relay／relay、影片與 SCTP 共用 transport、
通道重建重送 origin、辨識／GPS JSON 一致，且只用一次 offer、影片持續接收。
結果見 [turn_datachannel_udp.json](../diagnostics/gcp_datachannel_validation_20261008/turn_datachannel_udp.json)。

尚未進行本版實際相機＋遠端瀏覽器及長時間測試。改用 DataChannel 不代表先前網路
lost、卡頓或來源版程序消失問題已解決；實機接續步驟見 [NEXT_STEP.md](NEXT_STEP.md)。

來源版的詳細追蹤／GPS／安裝說明保留在 [WEBSOCKET_BASELINE_README.md](WEBSOCKET_BASELINE_README.md)，
其中舊模組命令與 WebSocket 段落僅供歷史參考。
DataChannel API 參考：[aiortc](https://aiortc.readthedocs.io/en/latest/api.html#data-channels)、
[WebRTC 標準](https://www.w3.org/TR/webrtc/#rtcdatachannel)。
