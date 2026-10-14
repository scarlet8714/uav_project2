# 2026/10/9 下午 3 點之後的連線使用紀錄

時區 Asia/Taipei（UTC+08:00）；起點 2026-10-09T15:00:00+08:00，擷取時間 2026-10-12T13:10:09.500904+08:00。
已掃描 128 份 events.jsonl，另外檢查 /var/log/syslog。期間內串流紀錄最晚到 10/9 18:42:24.921。
有 7 筆無法解析的舊紀錄，所在檔案及可辨識時間均在 10/9 之前；期間內相關紀錄全部可解析。

成功連線以每個 peer 的首次 connected 計一次；定期 health_sample 不重複計次。
路徑使用次數以每個成功 peer 使用過的模式計次；同一 peer 切換模式時，兩種模式各計一次。
STUN 版的 direct 指 ICE 未經 TURN 的路徑；host/prflx 候選不足以證明是經 STUN 公網打洞成功。

| 程式／用途 | 嘗試 | 成功連線 | ICE 直連使用 | TURN 使用 | ICE 路徑未記錄 |
| --- | ---: | ---: | ---: | ---: | ---: |
| rtsp_yolo_direct／實際觀看 | 6 | 4 | 未記錄 | 0 | 4 |
| rtsp_yolo_direct／本機合成來源測試 | 0 | 0 | 0 | 0 | 0 |
| rtsp_yolo_direct_with_gcp／實際觀看 | 0 | 0 | 0 | 0 | 0 |
| rtsp_yolo_direct_with_gcp／本機合成來源測試 | 1 | 1 | 0 | 1 | 0 |
| rtsp_yolo_direct_with_gcp_stun／實際觀看 | 2 | 2 | 2 | 1 | 0 |
| rtsp_yolo_direct_with_gcp_stun／本機合成來源測試 | 2 | 2 | 1 | 1 | 0 |

原 rtsp_yolo_direct_with_gcp 在期間內只有一次成功的本機測試，沒有成功的遠端觀看。
實際有 STUN／TURN 自動選路紀錄的程式名稱是 rtsp_yolo_direct_with_gcp_stun，另列避免混算。
direct 版的四條成功連線均由 Tailscale IP 發起，但應用程式沒有記錄每條連線的 Tailscale direct／peer_relay／DERP 模式。

| Tailscale 系統紀錄 | 筆數 | 計數內容 |
| --- | ---: | --- |
| direct | 35 | disco node now using 的端點選用事件，包含同一裝置切換 IPv4／IPv6 端點 |
| peer_relay | 0 | 未找到明確的 peer relay 關鍵字紀錄；不能據此證明實際使用次數為零 |
| DERP | 3 | derp-N connected 的連線成功事件，包含保活或重連 |

上述是 Jetson 整體系統事件，包含其他流量；不能逐程式歸屬，也不能當成串流觀看次數。
DERP 連線存在不表示影片走 DERP；direct 的端點事件也不等於新建 WebRTC 連線。
direct 事件分布：node [S8fqG] 2 筆、node [3RGir] 23 筆、node [40Udh] 10 筆。
完整 Tailscale 事件時間與來源行號：[tailscale_events.csv](tailscale_events.csv)。

| DERP 成功事件時間 | 紀錄 |
| --- | --- |
| 15:15:01 | derp-7 connected; connGen=1（/var/log/syslog:1861198） |
| 16:03:54 | derp-20 connected; connGen=1（/var/log/syslog:1863633） |
| 17:37:13 | derp-20 connected; connGen=1（/var/log/syslog:1866504） |

| 成功時間（10/9） | 程式 | 用途 | Peer | 路徑紀錄 | 來源 |
| --- | --- | --- | --- | --- | --- |
| 15:39:18.594 | rtsp_yolo_direct_with_gcp | 本機測試 | 7c0b51af60 | TURN | [diagnostics/gcp_stun_synthetic_runtime_20261009/original_relay/gcp_turn_20261009_153913/events.jsonl:16](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_synthetic_runtime_20261009/original_relay/gcp_turn_20261009_153913/events.jsonl:16) |
| 15:39:40.916 | rtsp_yolo_direct_with_gcp_stun | 本機測試 | 52c1e13e37 | ICE direct | [diagnostics/gcp_stun_synthetic_runtime_20261009/new_all/gcp_stun_20261009_153925/events.jsonl:26](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_synthetic_runtime_20261009/new_all/gcp_stun_20261009_153925/events.jsonl:26) |
| 15:39:53.837 | rtsp_yolo_direct_with_gcp_stun | 本機測試 | 40f4114e00 | TURN | [diagnostics/gcp_stun_synthetic_runtime_20261009/new_relay/gcp_stun_20261009_153948/events.jsonl:16](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_synthetic_runtime_20261009/new_relay/gcp_stun_20261009_153948/events.jsonl:16) |
| 15:49:17.348 | rtsp_yolo_direct_with_gcp_stun | 實際觀看 | b1946d2752 | TURN → ICE direct；直連為 100.70.8.54 → 100.70.248.32（Tailscale 位址） | [diagnostics/gcp_stun_20261009_154905/events.jsonl:24](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_20261009_154905/events.jsonl:24) |
| 16:10:15.967 | rtsp_yolo_direct | 實際觀看 | e78c0b7221 | ICE／Tailscale 模式未記錄 | [diagnostics/direct_20261009_160948/events.jsonl:40](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_160948/events.jsonl:40) |
| 16:36:09.671 | rtsp_yolo_direct_with_gcp_stun | 實際觀看 | b29c057ada | ICE direct；IPv6 host/prflx | [diagnostics/gcp_stun_20261009_163553/events.jsonl:29](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_20261009_163553/events.jsonl:29) |
| 18:08:22.696 | rtsp_yolo_direct | 實際觀看 | 1facce5a42 | ICE／Tailscale 模式未記錄 | [diagnostics/direct_20261009_180758/events.jsonl:37](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_180758/events.jsonl:37) |
| 18:31:03.336 | rtsp_yolo_direct | 實際觀看 | d4b84b0bfa | ICE／Tailscale 模式未記錄 | [diagnostics/direct_20261009_183048/events.jsonl:35](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_183048/events.jsonl:35) |
| 18:40:28.524 | rtsp_yolo_direct | 實際觀看 | d638ea8ab6 | ICE／Tailscale 模式未記錄 | [diagnostics/direct_20261009_184009/events.jsonl:39](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_184009/events.jsonl:39) |

10/9 15:49:17.348 的 b1946d2752 首先記錄 host/relay（TURN），15:49:17.779 的第一筆 health_sample 已改為 host/prflx（direct）。
這是一條連線使用過兩種路徑，不能算成兩條成功連線；切換時刻只能定位在兩筆紀錄之間。
[diagnostics/gcp_stun_20261009_154905/events.jsonl:25](/home/jetson/Desktop/uav_project2/diagnostics/gcp_stun_20261009_154905/events.jsonl:25)。

| 未成功的嘗試時間（10/9） | Peer | 原因 |
| --- | --- | --- |
| 18:30:50.948 | bd85b5ce5a | superseded_by_new_offer；送出 0 個 RTP 封包 |
| 18:40:16.138 | d665bb95ae | superseded_by_new_offer；送出 0 個 RTP 封包 |

機器可讀統計、逐連線路徑切換及各次啟動紀錄：[summary.json](summary.json)。
