# 20 分鐘 RTSP + YOLO + Chromium WebRTC 壓力測試

測試時間：2026-09-17 10:35:56–10:55:56（Asia/Taipei）  
測試長度：1200.7 秒  
瀏覽器：真實 headless Chromium  
刷新週期：45 秒

## 結論

成功重現長時間故障，而且故障點是攝影機 RTSP 輸入，不是 NVENC、WebRTC 或 Orin 算力。

前約 15 分鐘內，攝影機每約 50 秒送出 EOS，後端都能在約 1–2 秒內重連。累計第 19 次 EOS 附近，攝影機開始長時間不再提供新 RTP/H.264 影格。最後一張有效 YOLO 影格約在測試第 953 秒產生；測試結束時已連續 246.7 秒沒有新影格。

故障期間：

- RTSP frame counter 停在 27156。
- YOLO processed counter 停在 19256。
- WebRTC connection 仍為 `connected`。
- Chromium `<video>` 仍為 `readyState=4`。
- NVENC 仍持續成功編碼並傳送最後一張舊畫面。
- 所以瀏覽器播放時鐘持續增加，但畫面內容實際已凍結。

這與先前「重開網頁仍沒有正常畫面、但看起來 YOLO/WebRTC 某些部分還活著」的現象一致。重開網頁只重建 RTC/NVENC，無法修復已停止送 RTP 的攝影機 RTSP server。

## WebRTC / NVENC 壓測結果

- Chromium 主動刷新：26 次。
- server 建立 peer：27 次；關閉 peer：27 次。
- NVENC 建立：27 次；關閉：27 次。
- 任一時刻最大 peer 數：1。
- NVENC error：0。
- Python server 未崩潰。
- Chromium 未崩潰。
- 每次刷新後都能重新建立 H.264 WebRTC 並播放 960×544。

這表示新增的「先關閉舊 peer/encoder，再接受新 offer」策略有效，沒有觀察到 peer 或 NVENC session 累積。

## 攝影機／RTSP 結果

- 記錄到 RTSP EOS：19 次。
- 約第 932 秒首次出現超過 5 秒無新 YOLO 影格。
- 中間曾短暫多出一張有效影格。
- 約第 953 秒後完全停止更新，直到 20 分鐘測試結束仍未恢復。
- 最終 RTSP 狀態：`pipeline reached end of stream; reconnecting in 1 second`。

因此反覆 session 並非正常負載瓶頸，而是觸發／暴露攝影機 RTSP server 的 session 或串流資源清理問題。

## Orin 資源峰值

- 最高溫度：64°C。
- RAM 最大使用：約 2615/7607 MB。
- 最高輸入功耗：約 8.95 W（15W 模式）。
- GR3D 最高 99%，來自 YOLO TensorRT 推論；溫度、RAM 和功耗仍安全。

沒有熱節流、記憶體不足或功耗上限造成停止的證據。

## Log

- `summary.json`：測試器摘要
- `stress_events.jsonl`：每秒後端健康狀態與瀏覽器播放狀態
- `server_console.log`：RTSP EOS、NVDEC/NVENC 與 server console
- `server_diagnostics/resilient_20260917_103600/events.jsonl`：peer、encoder 與 watchdog 結構化事件
- `tegrastats.log`：Orin 溫度、RAM、GPU 與功耗
- `chromium.log`：Chromium console

注意：原始 `summary.json` 的 `observed_errors=[]` 只代表測試器當時沒有偵測到 browser/NVENC 錯誤；舊畫面仍被正常編碼，使瀏覽器播放時鐘繼續前進。測試器現已補上 RTSP/YOLO input-stall 判定，未來會把此情況直接列為錯誤。
