# 2026-10-05 五分鐘 RTSP／WebRTC 測試

播放觀察時間：10:31:30–10:36:30（Asia/Taipei），300 秒，每秒取樣，301 筆。

使用目前工作目錄程式、11s_car_960.engine、YOLO imgsz=(544, 960)、legacy tracker、預設 GPS 固定裝置路徑。相機來源 rtsp://192.168.144.135/live，UDP。隔離測試伺服器 18085，Jetson 本機無頭 Chrome，127.0.0.1；不涵蓋先前遠端瀏覽器 100.83.253.28 的網路路徑。

- 起始 RTSP 成功連線，無需重開設備。
- 301/301 個樣本 healthy=true，瀏覽器 connected。
- RTSP 重連 0；沒有非預期 peer 關閉或 YOLO 錯誤。
- 瀏覽器 RTP lost=0；沒有取樣到影格停滯或 PTS 倒退。
- 影像／YOLO PTS 差距中位數 33.37 ms，最大 33.38 ms。
- GPS 持續輸出 RMC V，未阻止影像播放。
- 測試結束、關閉 Chrome 時出現 peer_closing reason=ice_closed（10:36:30.538），在最後取樣後 20 ms，屬於測試正常清理。這也說明 ice_closed 本身不能判定網路故障。

結論：這次未重現約 30 秒反覆斷線。現有修改在本機路徑可穩定播放五分鐘；不能據此認定遠端網路為根因。仍須在發生問題的遠端瀏覽器上測試並記錄 WebSocket 關閉碼與前端重連原因。
