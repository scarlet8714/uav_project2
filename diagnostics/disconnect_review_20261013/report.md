# 2026-10-13 09:00 後斷線調查（台灣時間）

## 判讀

已確認相機端 eth1 發生實體鏈路中斷，Tailscale 因介面位址變動重新綁定。09:36 的 RTSP 停流早於 09:37 的鏈路中斷／Tailscale 重綁；不能把該次停流歸因於 Tailscale。觀看端另外發生短暫 DERP 路徑切換。最後 09:39:25 是服務關閉。

## 時間對照

| 時間 | 證據 | 判讀 |
| --- | --- | --- |
| 09:12:42 | kernel: r8168 eth1 link down | 相機 LAN 實體鏈路掉線 |
| 09:12:48 | NetworkManager carrier-changed；Tailscale 移除 eth1 位址並 Rebind，defaultRoute 仍為 eth0，DERP ping okay | Tailscale 對相機介面掉線作出反應；不是 Tailscale 登出 |
| 09:16:09–17 | eth1 link up，14 秒再次 down，17 秒 up | 約 3 分 27 秒後恢復且短暫抖動 |
| 約 09:36:13.416 | 09:36:17.112 的 RTSP last_packet_age_s=3.696 | 相機 RTP 首次停止供應；YOLO／分類無錯誤 |
| 09:36:22.121 | input_recovered；只多收到一個封包 | 短暫恢復 |
| 約 09:36:21.437–09:37:46 | 最後封包時間可由 packet age 推算；RTSP 8 次重試，含 No route to host | 相機來源長時間中斷，約 85 秒後重連 |
| 09:36:30.019 | Cannot send encrypted RTP, not connected；ice_closed | WebRTC 關閉發生在相機停流之後；沒有同時段 Tailscale 重綁證據 |
| 09:37:19 | eth1 link down | 相機實體鏈路中斷，晚於停流開始約一分鐘 |
| 09:37:25 | Tailscale eth1 位址消失、Rebind；DERP ping okay；觀看端 node R0XYP 09:37:26 via=direct | 網卡中斷觸發重綁；觀看端直連重新建立 |
| 09:37:35–42 | eth1 up、39 秒 down、42 秒 up；09:37:36 Tailscale Rebind | 相機網路再次抖動 |
| 09:37:46.388–57.724 | RTSP generation=2，input_recovered；觀看端重新連線，原因 RTSP source is reconnecting | 來源恢復後前端自動重新連線 |
| 09:38:59–09:39:04 | 觀看端 node R0XYP 由 via=derp 回到 via=direct | Tailscale 路徑短暫切換；應用 ICE 顯示 direct 不代表底層 Tailscale 必定直連 |
| 09:39:11.263–18.065 | metadata WebSocket 斷線後重連；同期間 WebRTC connected，持續送 RTP | 獨立 metadata 通道中斷；缺觀看端日誌，不能確認是否由先前 Tailscale 切換造成 |
| 09:39:25.054–317 | peer_closing reason=server_shutdown，server_stopped | 服務關閉造成最後斷線；紀錄沒有指出關閉者或收到的訊號 |

## 即時確認（約 09:42–09:45）

- Tailscale BackendState=Running，本機與觀看端 100.98.228.71 均 online。
- 觀看端 CurAddr=140.123.103.43:1025；tailscale ping 直連 39 ms。
- netcheck: UDP=true、MappingVariesByDestIP=false、CaptivePortal=false；Hong Kong DERP 66.3 ms。
- 相機 192.168.144.135 路由走 eth1；預設外網路由走 eth0。
- eth1 已恢復 100 Mb/s Full Duplex；目前累計 RX/TX errors=0。這不排除歷史鏈路中斷。
- Tailscale Health 有 iptables connmark 模組缺失警告，目前沒有證據能將其與上述斷線時間對應。
- 主機程序列表當時未找到 rtsp_yolo_direct_cls 執行程序。

## 限制及後續方向

direct_cls 的事件檔在 08:46:44 停止後，下一份從 09:33:34 開始；09:00–09:33 缺該服务事件紀錄，因此 09:12 只能確認主機相機網路中斷，不能完整重建當時頁面的行為。09:36 的最初停流可能涉及相機／上游供電、網路設備或 UDP 傳輸，現有證據無法細分。eth1 link down 可確認 carrier 消失，但不能僅憑紀錄斷言是網路線、相機電源或驅動。

優先檢查 eth1 網路線、接頭、相機／交換器供電與設備日誌；再補觀看端 Tailscale 及瀏覽器日誌，判斷 DERP 切換及 metadata 中斷。未修改程式、網路設定或啟停服務。

## 原始證據

- `../direct_cls_20261013_093334/events.jsonl`（關鍵事件行 177、193–198、250–284、378–398）。
- 本資料夾 `kernel.log`、`tailscaled.log`，為 journalctl 09:00–09:43 的快照。
