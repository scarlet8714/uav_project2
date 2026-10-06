# 10/5 Tailscale 與播放測試

本機播放：以 Jetson 自己的 Tailscale IP 100.70.8.54:18085 開啟頁面，300 秒、301 筆樣本全數 healthy 且 connected。RTSP 重連 0，RTP 掉包 0，沒有取樣到影格停滯。此路徑沒有經過遠端筆電／DERP，不能稱為遠端播放測試。

遠端路徑：探測先前瀏覽器裝置 100.83.253.28，監測 345.33 秒，302 筆狀態樣本。34 次診斷 ping 全成功，全部經 140.123.103.43:41641 直連，未觀察到 DERP 回覆。延遲 min/median/max = 25.0/42.5/436.0 ms。每 10 秒主動探測可能促進直連維持；這不是被動影片負載測試，也不是一般 ICMP 掉包率測量。每秒狀態取樣不能排除取樣間短暫切換。

歷史異常：10:06:43–44 遠端 peer [S8fqG] 出現 via=derp 接觸；10:06:45 NetInfo udp=false；10:06:46 恢復使用直連端點；10:06:48 瀏覽器 ice_closed。同一時段 RTSP/YOLO 正常。10:09:25 也出現 udp=false，約一秒後瀏覽器關閉。這是網路／路徑波動的相關證據，不足以證明所有斷線根因，via=derp 接觸也不代表整段影像都經 DERP。

Tailscale 狀態有 connmark iptables 模組不可用警告，目前不能確認與斷線相關。netcheck UDP=true，MappingVariesByDestIP=false，沒有 captive portal。Nearest DERP=hkg／Relay 欄位或 active derp connection 不能單獨證明資料流走 DERP。

結論：現在直連可用但延遲有尖峰；歷史上確實有 DERP 接觸與 UDP 探測異常。沒有重現斷線。完整遠端影片測試仍需要在遠端筆電實際開啟頁面，並同步保存 WebSocket 關閉原因與瀏覽器統計。
