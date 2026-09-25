# 15W 模式 5 分鐘同步複測

2026-09-24（Asia/Taipei），使用 `rtsp_yolo_direct`、本機 Chrome、
`rtsp://192.168.144.135/live`（UDP），並在 `eth1` 同時擷取相機封包。

- 正式取樣 300 秒、301 筆；全部樣本的 RTSP 狀態健康、瀏覽器連線且有
  影片／YOLO 來源 PTS 可配對。RTSP 重連 0 次，影片 PTS 沒有倒退或停格。
- PTS 差距中位數 33.38 ms、P95/P99/最大皆 166.84 ms；45 筆超過
  100 ms，沒有超過 250 ms。
- 測試結束時來源仍持續送影像。14:56:18.409 由測試客戶端送出
  RTSP TEARDOWN，14:56:18.412 相機回 RTCP BYE；這是正常收尾，
  不是測試期間的斷線。
- `dumpcap` 擷取 67,562 個封包，介面與擷取器丟包均為 0。

5 分鐘內未重現停流，但這段長度不足以驗證先前約 18 分鐘後的問題。
逐秒資料及彙總見同目錄的 `samples.jsonl`、`summary.json`；封包在
`../direct_sync_20260924_5min_packet_capture/`。
