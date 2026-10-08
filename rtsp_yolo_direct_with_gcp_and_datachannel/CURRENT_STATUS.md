# GCP TURN + DataChannel 現況

更新：2026-10-08，Asia/Taipei。

已按要求新增本資料夾，完整複製來源 `rtsp_yolo_direct_with_gcp`，並將 RTP origin、
YOLO／GPS 結果由 WebSocket 改為可靠、有序的 WebRTC DataChannel。此工作未修改來源版本。
新模組位於實際專案 `/home/jetson/Desktop/uav_project2`。

## 已完成

- 瀏覽器建立 offer 前加入 metadata DataChannel；雙端 `max-bundle`，沿用 relay-only TURN。
- 後端移除 `/events/<peerId>`，透過 DataChannel 傳送原 JSON 欄位與 RTP origin。
- 保留最新待送結果，限制待送大小；資料通道可在同一 peer 上獨立重建。
- 保留 H.264 封包直傳、解碼／YOLO／GPS、追蹤與來源 PTS 對齊。
- 前端版本 `20261008.dc1`；health 和終端提供 DataChannel 狀態與待送資訊。
- 複製本機 TURN 設定，權限 600，仍排除於 Git。未變更 GCP／WireGuard 設定。

## 已取得的驗證證據

- Python：26 項通過，涵蓋 metadata 生命週期、RTP origin、待送限制、來源 generation、
  relay、未 bundle 的 SDP 拒絕與舊 WebSocket 路由移除。
- JavaScript：29 項通過，涵蓋建立通道順序、獨立重試、舊事件隔離、PTS 歷史與畫面等待。
- 真實 GCP TURN UDP 合成測試通過：兩個 aiortc peer 在本台 Jetson 經 GCP relay／relay，
  解碼 6 張 160×120 H.264 影格，核對 2 筆模擬 YOLO／GPS JSON。
  SCTP 和影片共用 DTLS／ICE transport；關閉第一條通道、建立第二條後重送相同 origin，
  影片連線保持 connected 且 RTP 計數繼續增加，全程只有一次 offer。

測試結果：[turn_datachannel_udp.json](../diagnostics/gcp_datachannel_validation_20261008/turn_datachannel_udp.json)。
此證據是合成影片及同機雙 peer，尚非遠端瀏覽器觀看正式相機的驗收。

## 尚未完成的實機驗收

本次沒有啟動正式 RTSP／YOLO／GPS 服務，沒有重新部署 GCP，也沒有連續查詢正式 health。
新版本的公網瀏覽器播放／疊圖、有效 GPS 與長時間運作仍待測試。
來源版本先前曾出現公網畫面卡頓與程序消失，退出原因未確定；這次傳輸方式改動沒有
證據可宣稱已排除該問題。`end_to_end_verified` 仍為 false。

啟動及驗收方式見 [NEXT_STEP.md](NEXT_STEP.md)。複製時的來源狀態另存於
[WEBSOCKET_BASELINE_STATUS.md](WEBSOCKET_BASELINE_STATUS.md)，不代表本版的即時狀態。
