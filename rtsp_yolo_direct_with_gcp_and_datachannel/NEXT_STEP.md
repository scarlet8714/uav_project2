# DataChannel 版接續步驟

更新：2026-10-08，Asia/Taipei。程式複製、DataChannel 改寫及合成 TURN 測試已完成。
接下來是正式相機與公網瀏覽器驗證；本次尚未啟動正式串流。

## 1. 啟動新模組

沿用已設好的 GCP Nginx、WireGuard 與 TURN，不需重跑安裝或重建金鑰。
先確認來源版沒有佔用 8081；若仍執行，從其原終端結束後再啟動本版。
在 `/home/jetson/Desktop/uav_project2` 執行並保留完整終端輸出與退出碼：

```bash
python3 -u -m rtsp_yolo_direct_with_gcp_and_datachannel \
  --host 0.0.0.0 --port 8081 --model-path test2.engine --playout-delay-ms 300
```

模型、相機、GPS、追蹤參數與來源版相同，其他選項見 [README.md](README.md)。
事件紀錄改為 `diagnostics/gcp_datachannel_<時間>/events.jsonl`。

## 2. 公網觀看與通道核對

關閉舊版觀看分頁，再開 `https://104.155.197.179/`，沿用既有網頁登入。
頁面版本必須是 `20261008.dc1`，框／GPS 應顯示「DataChannel 已連線」。
確認影片、辨識框與 PTS 對齊；有效 GPS 座標仍需要接收器取得有效 fix。

按需要單次查核 `/api/health`：確認 `metadata_transport=webrtc-datachannel`、
`bundle_policy=max-bundle`、peer connected、relay／relay 與 `metadata.state=open`。
開發工具應沒有 `/events/…` WebSocket 請求；HTTP signaling 與 health 請求仍正常保留。

## 3. 獨立資料通道恢復與持續運作

可在瀏覽器開發工具 Console 執行 `metadataChannel.close()` 測試資料通道恢復。
應看到資料通道重建、相同 RTP origin 恢復，而影片繼續播放、peerId 保持相同，
Network 沒有新增 `/offer`。此測試只適用於本版的頁面。

接著觀察較長時間的影片、lost、RTSP reconnect、YOLO 年齡及 DC 待送量。
底層 ICE／DTLS 斷線會依既有邏輯重建整條 peer；資料通道改寫無法保證消除網路卡頓。
若服務再次消失，先保留退出碼、終端輸出及最後事件，核對是否仍有 8081 listener，
不要只依最後一筆健康快照判定程序目前正常。

合成檢查可獨立執行：

```bash
python3 -m rtsp_yolo_direct_with_gcp_and_datachannel.check_datachannel
```

此檢查不啟動相機或正式服務。已通過的結果與限制見 [CURRENT_STATUS.md](CURRENT_STATUS.md)。
需要查 WireGuard／GCP 原安裝資訊時，參考 [WEBSOCKET_BASELINE_NEXT_STEP.md](WEBSOCKET_BASELINE_NEXT_STEP.md)，
其中舊 WebSocket 驗收與舊模組啟動命令不適用於本版。
