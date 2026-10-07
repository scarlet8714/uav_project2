# RTSP／YOLO／GPS + GCP TURN 現況

更新：2026-10-07（Asia/Taipei）。此版本完整複製自同日的
`rtsp_yolo_direct`，加入 GCP TURN。**下面保留的舊同步／耐久測試屬於原版，
不是 GCP TURN 版本的長時間實測結果。**

## 目前進度：準備設定 GCP WireGuard＋反向代理

截至本次更新，**GCP TURN 已接入程式；WireGuard、Nginx 與公網 HTTPS／WSS
仍在設定準備階段，尚未部署或驗證。**網頁與框／GPS 目前仍走 Tailscale。

已完成的程式調整：

- GCP 版以 TURN relay 傳送影片，保留 RTSP H.264 封包直傳、YOLO／GPS 與 PTS 對齊。
- metadata WebSocket 已獨立重連；首張畫面／播放停格逾時的強制重連已移除。
- 送出緩衝預設提高至 **300 ms**；使用者回報觀看起來可以，尚未新增量化比較。
- 截圖按鈕、API 與背景存圖功能已移除，頁面版本為 **`20261007.3`**。
  最近一次前端 26 項與 Python TURN／metadata 15 項測試全部通過。

### 已決定的下一階段架構

使用者選擇先走 **WireGuard＋GCP 反向代理**，沿用目前的框／GPS WebSocket；
WebRTC DataChannel 僅完成優缺點討論，尚未實作。

```text
網頁／signaling／健康檢查／框／GPS：
瀏覽器 ↔ GCP Nginx（HTTPS／WSS）↔ WireGuard ↔ Jetson:8081

影片：
瀏覽器 ↔ 現有 GCP TURN ↔ Jetson
```

目標是讓觀看端直接開 GCP 的 HTTPS 網址，無需安裝 Tailscale 或 WireGuard。
WireGuard 只建立 Jetson ↔ GCP 的隧道，由 Nginx 代理目前網頁服務；
影片繼續使用現有 TURN，不因加入網頁代理而改走 WireGuard。
需保留原有 PTS 配對、metadata 獨立重連與 300 ms 緩衝行為。

中繼位置固定為指定的 GCP 主機，不自動改走 Tailscale DERP；實際延遲、
丟包與頻寬仍需實測。WireGuard 使用 UDP，沒有內建 DERP 備援。
參考：[WireGuard 架構](https://www.wireguard.com/)、
[Nginx WebSocket 代理](https://nginx.org/en/docs/http/websocket.html)。

### GCP 已知資訊與尚待確認事項

- 預計沿用現有 TURN 主機，公網 IP **`104.155.197.179`**。
- 使用者尚不確定 GCP VM 的作業系統，且目前**沒有網域**。
- 已確認可使用 Let's Encrypt 公網 IP 憑證，規劃入口為
  `https://104.155.197.179/`；尚未申請憑證或啟用 HTTPS。
  IP 憑證有效期約六天，需設定自動續期與 Nginx 載入新憑證，涵蓋預計一週的使用期間。
  Certbot 的 webroot IP 憑證流程需 **5.4 以上版本**。
  參考：[Let's Encrypt IP 憑證與 Certbot 說明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。
- 尚未收到 VM 作業系統、監聽連接埠、主機防火牆或 WireGuard 安裝狀態的輸出。
  也尚未確認 `104.155.197.179` 是否為靜態 IP，或 `80`／`443` 是否被既有服務占用。
- 已提供保留現有公網 IP、增加 VM 網路標記 `uav-web-relay`、新增 VPC 防火牆規則的步驟；
  **尚未收到使用者完成這些設定的確認**。
  規劃放行 `51820/UDP`（WireGuard）、`80/TCP`（憑證驗證）、
  `443/TCP`（HTTPS／WSS），目標限定帶此標記的 VM；原 TURN 與 SSH 規則保留。
  參考：[GCP 靜態 IP](https://docs.cloud.google.com/compute/docs/ip-addresses/configure-static-external-ip-address)、
  [VPC 防火牆規則](https://docs.cloud.google.com/firewall/docs/using-firewalls)。

### 下次繼續的位置

先由使用者在 GCP Console → Compute Engine → VM 執行個體，
開啟 `104.155.197.179` 所屬主機的 SSH，執行並提供：

```bash
cat /etc/os-release
sudo ss -lntup
```

取得輸出後，依實際作業系統與連接埠占用情況完成以下工作：

1. 安裝／設定 GCP 與 Jetson 兩端的 WireGuard，交換公鑰；私鑰各自保留於主機。
2. 確認隧道 handshake，並從 GCP 存取 `http://<Jetson 隧道 IP>:8081/api/health`。
3. 設定 Nginx 代理網頁、`/offer`、`/api/health` 與 `/events/<peerId>`，支援 WebSocket 升級。
4. 申請 IP HTTPS 憑證，設定自動續期及 Nginx reload。
5. 用實際觀看端確認 GCP 網址、框／GPS、PTS 對齊、TURN relay 路徑與斷線恢復。

本次僅記錄進度；未安裝或修改任何主機的 WireGuard／Nginx，未更改 GCP VM、
防火牆、路由、憑證或 Tailscale 設定，也未重新啟動現行串流。

## 目前可用的設定

- TURN 公網 IP：`104.155.197.179`，帳號：`uav`。
- 使用者於 2026-10-07 確認：目前 TURN 帳號與密碼不會到期，無需定期更新憑證。
- 已測通 `3478/UDP`、`3478/TCP`；預設 URL 為
  `turn:104.155.197.179:3478?transport=udp`。
- 密碼僅寫在本機 `.turn.env`，權限 `600`，Git 排除；未寫入原始碼、
  文件、`/api/health` 或結構化事件。搬移此資料夾時需另帶設定檔。
- 瀏覽器與 Jetson 均強制使用 TURN relay；沒有 relay 候選時明確失敗，
  不會退回 Google STUN 或直連。連線成功再檢查實際候選 pair 是 `relay/relay`。
- 網頁、signaling、YOLO 框／GPS 的 WebSocket 維持用 Jetson 的 Tailscale 位址；
  影像的 TURN 連線目的地是 GCP 公網 IP。是否透過 exit node 仍由系統路由決定。
- 新版網頁預設 `8081`，事件紀錄 `diagnostics/gcp_turn_<時間>/`，
  模型共用根目錄的 `test2.engine`。截圖功能已移除。
- RTSP 封包分流、300 ms pacing、YOLO 隔幀推論／容量 1 佇列、legacy／ByteTrack、
  GPS 歷史配對、Canvas class／經緯度標籤、單一觀看連線、健康監控均保留。
- 首張畫面等 10 秒／停格 5 秒的前端強制重連維持移除；其他 WebRTC failed／closed、
  RTSP 中斷與影像建立連線錯誤的整體重連保留。metadata WebSocket 已改為獨立重連。

## 2026-10-07：移除截圖功能

依使用者要求，只從 `rtsp_yolo_direct_with_gcp` 移除截圖功能：

- 移除「立即儲存 5 張」按鈕、截圖訊息區與前端請求。
- 移除 `/api/capture`、推論端截圖請求、圖片複製／註記與背景寫檔執行緒，
  並刪除不再使用的 `capture.py`。
- 原版 `rtsp_yolo_direct` 與先前已儲存的圖片保留；影片、YOLO／GPS、
  Canvas 對齊、300 ms 緩衝與重連設定維持原有行為。

頁面版本更新為 `20261007.3`。套用需重新啟動 GCP 版，並重新整理觀看頁面；
瀏覽器仍顯示舊按鈕時可使用 Ctrl+F5。未替使用者重新啟動現行串流。

驗證：前端模擬測試 **26 項**、Python TURN／metadata 測試 **15 項**全部通過。
另確認截圖 API 回傳 404、影片與資料路由仍可解析，並以模擬模型檢查
推論初始化、產生含 PTS 的辨識結果與關閉流程；Python 語法及執行時 HTML 檢查通過。
本次未啟動正式相機或進行瀏覽器實機播放測試。

## 2026-10-07：送出緩衝提高至 300 ms

依使用者要求，只將 GCP 版 `--playout-delay-ms` 的預設值由 150 ms 改為 300 ms，
增加吸收雲台到 Jetson 送流空檔的餘裕。此項是 Jetson 依來源 PTS 送出 WebRTC
封包的 pacing buffer；沒有更改雲台內部設定、RTSP `max_delay`、TURN 或疊圖對齊條件。
相較舊設定增加 150 ms 的設定緩衝延遲，實際流暢度改善仍待觀看比較。
參數載入確認預設為 300 ms，且明確指定 150／0 ms 仍可覆蓋；未重新啟動現行串流。
套用需重新啟動 GCP 版，並移除或改掉啟動命令中可能已有的 `--playout-delay-ms 150`。
下方原版歷史紀錄中的 150 ms 保留為當時量測與設定紀錄。

## 2026-10-07：框／GPS 資料通道獨立重連

依使用者要求，先只修改 `rtsp_yolo_direct_with_gcp`，修正原版重連缺點的第一點：
**WebSocket 斷線不再連影片一起關掉。**

- 框／GPS WebSocket 以獨立的 1／2／4／8 秒退避重接同一個 peer；
  不呼叫整體 `reconnect()`，不重新 `/offer`，不重建 WebRTC。
- 保留 RTP origin、generation、影片 PTS 與最近 180 筆辨識歷史。
  中斷時沿用來源 PTS 差距小於 1 秒的疊圖規則，資料過舊便不顯示框／座標；
  資料恢復且與影片對齊後繼續顯示，不額外補播斷線期間的辨識資料。
- 資料連線建立超過 10 秒未完成時只重試 WebSocket；成功開啟後重設資料退避。
  頁面新增獨立「框／GPS」連線狀態，影片的連線狀態與 RTP 統計持續運作。
- 後端重送原有 RTP origin；新 socket 取代舊佇列時結束舊資料通道，
  舊連線清理不會清掉新佇列。新增 receive 迴圈以處理 pong／close 與閒置斷線。
- 忽略舊 socket 的延遲訊息／事件與舊影像 peer 的健康結果；整體重連及離開頁面時
  取消資料重試與建立逾時，避免留下重複連線。
- WebRTC failed／closed、RTSP 中斷與影像建立失敗仍走原本整體重連。
  若成功取得 `/api/health` 且確認目前 peer 已不存在，也重建影片以恢復後端重啟後的會話；
  健康請求失敗或沒有 peers 欄位本身不觸發此條件。

驗證：新版前端模擬測試 **26 項**、新版 Python TURN／metadata 測試 **15 項**全數通過，
涵蓋影像保持、對齊恢復、過舊框隱藏、資料退避／逾時、舊事件、頁面離開、後端 peer 消失、
重送 origin、資料佇列替換及閒置斷線。Python／執行時 HTML 的 JavaScript 語法檢查通過。
本次未啟動正式串流或重新進行遠端實機斷網測試；套用需重新啟動 GCP 版並重整網頁。

## 2026-10-07 12:03–12:05：使用者回報仍出現 metadata connection closed

檢查 [`diagnostics/gcp_turn_20261007_120343/events.jsonl`](../diagnostics/gcp_turn_20261007_120343/events.jsonl)：
9 次 `peer_closing` 的原因都是 `superseded_by_new_offer`，最後 1 次為使用者停止服務時的
`server_shutdown`。12:04:05、12:04:25、12:04:45、12:05:05 被替換的 peer 當時仍為
WebRTC `connected`、ICE `completed`、`relay_verified: true`，metadata 仍連線，
最後 RTP 送出距離關閉只有 0.013–0.017 秒。RTSP 在這段期間保持連線。

這份紀錄確認影片是被後續的新 `/offer` 取代；尚無法僅憑事件紀錄判定新 offer
來自哪一個分頁。`metadata connection closed` 字串已不在目前 GCP 前端程式中，
仍存在於原版前端；舊頁面、另一個仍重試的分頁或觀看到不同版本是待排查方向。
後端重啟不會更新已經載入的瀏覽器 JavaScript。排查時先關閉所有舊觀看分頁，
重新啟動 GCP 版後只開一個 `http://<jetson-tailscale-ip>:8081/`，必要時強制重新載入。
新版頁面應有獨立的「框／GPS」連線狀態。若使用 `--port` 指定其他 port，請開該 port。

本次查詢時 Jetson 的 8080／8081 均未監聽，最近一次 GCP 程式已於 12:05:17 停止，
因此沒有直接取得當時瀏覽器實際載入的 HTML，也未確認上述排查後的結果。
使用者後續確認觀看的是 8081；不能只憑 port 確認頁面已載入最新 JavaScript。

已補上頁面版本 `GCP · 資料獨立重連 · 20261007.2`、
`/api/health.settings.frontend_revision` 與 `X-Frontend-Revision` 回應標頭。
新版 offer 會提供前端版本與重連原因，後端寫入 `peer_created.client_revision`、
`client_reconnect_reason`；未提供的舊頁面標記為 `unknown`。
另記錄 metadata 連上／斷開事件，協助分辨單純資料重接與影片被新 offer 取代。
尚未改動單一觀看取代政策，也沒有證實此次新 offer 的前端來源。

## 本次已完成驗證

測試由此 Jetson 對實際 GCP TURN 執行；兩個測試端均在此 Jetson。

| 項目 | UDP 3478 | TCP 3478 |
| --- | --- | --- |
| 帳密驗證與兩個 relay allocations | 通過 | 通過 |
| ICE 實際選中 relay/relay | 通過 | 通過 |
| 五次小型雙向資料往返 | 通過，71.00–90.17 ms | 通過，66.60–176.65 ms |
| WebRTC ICE／DTLS／H.264 RTP | 通過 | 通過 |
| 接收解碼合成 160×120 H.264 影格 | 5 張 | 5 張 |

H.264 測試使用此版真正的 `EncodedTrack` 接收預先壓縮的合成封包；
只有診斷程式產生測試影像，正式串流仍不重新編碼。測試指令：

```bash
python -m rtsp_yolo_direct_with_gcp.check_turn --both
python -m rtsp_yolo_direct_with_gcp.check_turn --both --webrtc
```

新增 TURN Python 測試 **10 項**、原版 backend／GPS 回歸 **16 項**全部通過。
首次整合時新版前端 **16 項**、原版前端 **14 項**全部通過；
資料通道獨立重連後的新測試數與結果見上方 2026-10-07 章節。
啟動參數與 JavaScript 語法檢查通過；密碼 Git 排除與原功能檔案一致性另做檢查。
未啟動正式相機程式，未占用相機／GPS，未更改 GCP VM、GCP 防火牆或 Tailscale 設定。

## 尚待驗證事項

就現有 TURN 接入而言，IP、帳號、密碼已足夠，port／傳輸方式也已實測，不需要提供
GCP 專案 ID、VM zone 或 SSH 金鑰才能使用目前的 TURN 版本。
帳密目前不會到期，TURN 接入沒有尚缺的必要連線資訊。
新增 WireGuard／反向代理所需的確認事項與下一步，見上方「目前進度」章節。

- 待用實際觀看端網路／瀏覽器測真實相機、YOLO／GPS 對齊與斷線恢復。
  合成影格短測不代表相機碼率下的一週穩定性，也未逐一確認整個 relay UDP port 範圍。
- 目前一次使用一個 TURN URL；UDP 失敗不會自動切 TCP，可用 `--turn-url` 手動選擇。
  尚未設定 TLS；若需要 `turns:`，再提供 TLS port 與可驗證憑證對應的網域。
- TURN 無法修復相機停止送 RTP，也不會保留重建前的 peer、metadata 或 PTS 原點。
  網頁／metadata 仍依賴 Tailscale；單獨 metadata 斷線已不再觸發影片重連。
  真正整體重建影片時，原 peer、metadata 歷史與 PTS 原點仍會重設。
- aiortc **1.15.0**／aioice **0.10.2** 已測通。後端 relay policy 透過
  aioice `_transport_policy` 設定；套件升級後需重跑 TURN／WebRTC 檢查。
  aiortc 目前不產生 `disconnected` 狀態，舊的 disconnected 逾時分支不能當作
  所有斷線狀況都會在五秒內重建的保證。

啟動與設定說明見 [README.md](README.md)。先停止原版，再從專案根目錄執行：

```bash
python -m rtsp_yolo_direct_with_gcp
```

瀏覽器開啟 `http://<jetson-tailscale-ip>:8081/`。

---

## 原版歷史紀錄（完整保留）

更新：2026-10-07（Asia/Taipei）。相機為使用者確認的亞拓 **G3P V2 4K**
三軸雲台；亞拓官方產品型號為 `RGG308XW`。RTSP 位址為
`rtsp://192.168.144.135/live`。先前 SDP 中的
`Ambarella streaming 2012.03.12` 是串流軟體標識，不能單靠它辨認
雲台品牌或韌體版本。

## 已完成的同步測試

`rtsp_yolo_direct` 由同一條 RTSP 連線分流壓縮 H.264 給 WebRTC，並將
影格送往 Jetson 解碼／YOLO。瀏覽器以 RTP timestamp 還原來源 PTS，
逐秒比較播放影格與所選 YOLO 結果。下表的「差距」是兩者在**來源
時間軸**上相差多少，不是相機曝光到螢幕的端到端延遲。

| 測試 | 電源模式 | 有效配對 | PTS 差距中位數／P95 | 來源結果 |
| --- | --- | ---: | ---: | --- |
| [2026-09-23 20 分鐘](../diagnostics/direct_sync_20260923_093817/report.md) | MAXN（使用者確認） | 1,067 筆 | 33.38／100.11 ms | 約 17 分 43 秒後停影像，未恢復 |
| [2026-09-24 第一次短測](../diagnostics/direct_sync_20260924_134257/summary.json) | 15W，mode ID 2 | 84 筆 | 33.38／66.74 ms | 約 79 秒後停影像 |
| [2026-09-24 第二次短測](../diagnostics/direct_sync_20260924_135152/summary.json) | 15W，mode ID 2 | 236 筆 | 33.38／66.74 ms | 約 231 秒後停影像 |
| [2026-09-24 20 分鐘與封包擷取](../diagnostics/direct_sync_20260924_140633/report.md) | 15W，mode ID 2 | 1,127 筆 | 33.38／100.11 ms | 約 18 分 42 秒後停影像，未恢復 |
| [2026-09-24 5 分鐘複測](../diagnostics/direct_sync_20260924_145022/report.md) | 15W，mode ID 2 | 301 筆 | 33.38／166.84 ms | 全程正常、重連 0 次 |

MAXN 與 15W 的長測中位數和 P95 相同；YOLO 推論耗時中位數約為
40.4 與 39.2 ms。現有資料支持「15W 足以運行目前負載，未見明顯
同步退化」，但兩次不是固定場景的受控 A/B 測試，不能證明低瓦數
完全沒有影響。5 分鐘複測不能排除約 18 分鐘後的停流問題。

## RTSP 中斷的協定證據

- [2026-09-17 GStreamer 診斷](../diagnostics/DIAGNOSIS.md)曾在約
  49–50 秒看到相機先送 RTCP `BYE`，再結束該次 RTSP 串流。
- 2026-09-24 長測使用 PyAV／UDP，並在 `eth1` 擷取封包：14:25:51
  前仍持續有相機 RTP；之後影像封包停止，**停流前沒有看到 BYE**。
  14:26:01.999 是 Jetson 客戶端先送 `TEARDOWN` 清理逾時連線，
  相機於 14:26:02.001 才回 `BYE`。後續重連時相機對 RTSP
  `OPTIONS`／`DESCRIBE`／`SETUP`／`PLAY` 回 `200 OK`，卻沒有恢復 RTP。
  原始封包在 [`diagnostics/direct_sync_20260924_packet_capture/`](../diagnostics/direct_sync_20260924_packet_capture/)。
- 5 分鐘複測直到結束都正常；其 `BYE` 同樣是在測試客戶端正常
  `TEARDOWN` 之後才出現。原始封包在
  [`diagnostics/direct_sync_20260924_5min_packet_capture/`](../diagnostics/direct_sync_20260924_5min_packet_capture/)。
- 長測的封包擷取計數為 231,734、介面／擷取器丟包 0。停流後 RTSP
  控制連線仍能往返，較不像整條網路線直接斷開；但不能排除只影響
  媒體的鏈路問題、供電接觸問題或相機內部編碼／送流故障。

亞拓公開產品頁可確認 G3P V2 4K 型號；目前未找到同型號約 18 分鐘
停流的公開公告。若詢問亞拓，應提供上述「RTP 先停止、客戶端
TEARDOWN 後才有 BYE、重連 PLAY 200 但無 RTP」時間線，並請其核對
雲台韌體版本及長時間 RTSP 預覽是否有已知問題。

## GPS 與下一步

2026-10-01 已將 GPSReader 設為每次開啟串口時向 SAM-M8Q 傳送
5 Hz（200 ms）設定；9600 baud 下僅保留 RMC／VTG，以限制訊息量。
依使用者指定，`rtsp_yolo_direct` 預設 GPS 路徑改為 `/dev/ttyUSB4`；
當天 GPS 的穩定路徑為 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`。
`/dev/ttyUSB0` 為 FTDI，不能當作 GPS。
尚未傳送 CFG-CFG 保存設定，也尚未驗證斷電後設定保留。

[五分鐘實機測試](../diagnostics/GPS_5HZ_20261001.md)持續 300.1 秒，
RMC／VTG 各收到 1499 筆；RMC 平均 5.000 Hz，中位間隔 200.0 ms、
最長 201.5 ms，解析／checksum 錯誤 0 筆。所有 RMC 均無有效 fix；
本次獨立串口監測不能視為影片／YOLO／GPS 的端到端定位測試。

目前 RTSP／YOLO 測試中的 GPS 狀態為 `invalid_fix`，**尚未驗證目標
經緯度**。室內可測影像同步、GPS 訊息接收與無效定位狀態；要驗證
有效 GPS 與影格配對、目標座標及精度，需在室外開闊天空取得穩定 fix。
`gps_age_ms` 使用 Jetson 收到影格與 GPS 訊息的 monotonic 時間，並非
相機曝光與 GPS 測量的硬體時間差。

若要定位停流原因，下一輪可先固定線材與供電，讓另一個 RTSP
客戶端**單獨**接收超過 20 分鐘，並同時記錄 RTP、RTCP、RTSP
與相機韌體版本。避免同時換線、換傳輸模式和換接收程式，否則難以
判斷哪項改動影響結果。

## 2026-09-25 畫面卡頓排查與處理

- **現象與對照：**卡頓時整張影片、辨識框和畫面 PTS 一起停住。
  PC 上 PotPlayer 直連 RTSP 較順，但延遲較高；單純 RTSP→WebRTC
  轉送也會卡，改用 TCP 仍有卡頓和順移。因此 YOLO 或框的 PTS
  對齊不足以解釋整張影片停頓。純轉送測試程式移除無緩衝
  `MediaRelay` 後改善很多，但它與 `rtsp_yolo_direct` 是獨立程式，
  這項改善不能直接當作本程式已修復的證據。
- **直接線索：**Jetson 直接讀相機時，來源 PTS 每張固定增加
  33.37 ms；PyAV 約每秒在關鍵影格處出現 80–135 ms 輸出空檔。
  同步封包擷取顯示，該關鍵影格的 RTP 封包在 `eth1` 上橫跨約
  126–132 ms。週期性空檔已存在於網路介面收到的封包，直接把 PTS
  改成 Jetson 接收時間並不能消除它。詳見
  [量測紀錄](../diagnostics/rtsp_pts_arrival_20260925.md)。
- **做法與結果：**`rtsp_yolo_direct` 現以預設 150 ms 緩衝依來源
  PTS 均勻送出 WebRTC 影片，可用 `--playout-delay-ms 0` 關閉比較；
  YOLO 改為每 2 個解碼影格推論 1 次，中間影格沿用最近可用的框。
  使用者試播後表示目前結果「算不錯」，但尚無逐幀顯示間隔與
  端到端延遲的客觀量測；緩衝會增加播放延遲。

## 待辦：GPS 與影格時間配對

2026-10-01 工作目錄另有 RTSP 接收緩衝調整：`source.py` 向 FFmpeg
設定 `max_delay=600000`（微秒）；獨立 `rtsp_direct_stream.py` 設為
500000。這與預設 150 ms 的 WebRTC 送出緩衝是不同設定；目前
使用者實際試播後確認：**接收 buffer 調成 600 ms 後，延遲已大幅改善**。
此為使用者觀察，尚未量測端到端延遲與改善幅度；也尚未完成新的
完整耐久測試，長時間停流問題仍待驗證。

依 [TEMP_CONVERSATION 的接續步驟](../TEMP_CONVERSATION.md#下次接續步驟)
及本次討論，保留來源 PTS 作為影片／YOLO 框的對齊基準，另外使用
Jetson monotonic 時間配對 GPS；**不把影片 PTS 改成 Jetson 收包時間**。

- **已有基礎：**影格有 `pts90k`、`receive_mono_ns`，GPS RMC 位置更新
  有 `last_position_update`；2026-10-06 已改為從歷史選取影格接收時間
  之前最近的 GPS 狀態，計算 `gps_age_ms`，並檢查 fix 與資料是否過期。這些時間是抵達 Jetson 的
  時間，不等於相機曝光與 GPS 實際測量的時間。
- **先做地面驗證：**在可見天空處讓 SAM-M8Q 取得穩定 fix，確認
  RMC/VTG 的位置、速度、COG、UTC/date 與實際更新率；目前未輸出 GGA，測試輸出
  避免顯示座標。無人機不需起飛即可驗證接收、時間紀錄、歷史查找和
  stale 防護。靜止時 COG 可能不可用，且無法從不變的座標估出影像與
  GPS 的固定時間偏移。
- **改進配對：**保存每筆有效 GPS 位置與其 monotonic 接收時間、
  GNSS 時間和狀態，建立有界歷史佇列；加入可設定的延遲校正值，以
  「影格接收時間 − 校正延遲」查找對應 GPS。先選該時刻之前最近
  的有效資料，處理歷史不足、未來資料、RTSP 重連與過期情況；
  比較 `gps_age_ms` 及配對結果。2026-10-06 已完成有界狀態歷史及
  按影格接收時間查找；GNSS 時間保存與可設定延遲校正尚待加入。
- **後續提高時間解析度：**5 Hz 輸出已實測，先維持 5 Hz 並完成有效
  定位與歷史配對；若移動測試顯示 200 ms 更新週期形成瓶頸，再評估
  10 Hz、UBX-NAV-PVT 與串列 baud rate／訊息量。若能接受等待下一筆
  GPS 的延遲，可比較前後兩筆插值。用實際移動紀錄校準固定延遲、量測誤差，並調整
  1.5／2 秒過期門檻。固定延遲只能補償平均偏移，不能消除每張影格
  不同的傳送延遲。
- **更高精度與座標驗證：**若要求精準 UTC 同步，可評估把 SAM-M8Q
  PPS 接到 Jetson GPIO；但沒有相機曝光時間戳，PPS 仍不能單獨得知
  每張影格的曝光時刻。目標座標精度另需在正下視時校正 FOV、AGL、
  yaw offset 與鏡頭畸變；若相機改成 45°，需改用完整的視線與地面
  求交模型。試飛時再確認 M490TOP 的位置 S-Curve、機頭 yaw／COG
  行為，以及可取得時的 `WP_YAW_BEHAVIOR` 設定。

## 備案：經 Tailscale 轉送飛控遙測

2026-10-01 討論列為備案；2026-10-03 已完成地面站經 Tailscale 到
Jetson 的單向 MAVLink 收包與解碼實驗。尚未整合到 RTSP／YOLO 程式，
也尚未完成遙測延遲測試。
目前飛控無法直接連到 Jetson；使用者已確認「地面站 → Tailscale →
筆電 QGroundControl」可用。最新討論的備案改為先送到 Jetson，
再由 Jetson 分流給定位程式與筆電：

```text
飛控 → 地面站 → Tailscale → Jetson
                            ├→ 遙測解析、影像配對與目標定位
                            ├→ Tailscale → 筆電 QGC（原始 MAVLink 遙測）
                            └→ Tailscale → 筆電瀏覽器（WebRTC／辨識結果）
```

- **現有條件：**地面站經 Tailscale 可將遙測送到筆電 QGC（14550），
  筆電與 Jetson 已透過
  Tailscale 連線，使用者表示目前 WebRTC 播放不卡頓。這尚不能證明
  遙測延遲足夠低；2026-10-03 已另行確認 Jetson UDP 14550 能收包。
- **用途：**保留 Jetson 本地 SparkFun GPS 的 5 Hz 位置／速度資料，
  評估接收地面站轉送的飛控 yaw／pitch／roll，
  補足 COG 無法代表機身朝向的限制。飛控姿態不等於相機姿態，仍需
  雲台角度與安裝方向；飛控相對高度也不直接等於離地高度。
- **連線已初步驗證，分流待實作：**本次實測來源為
  `100.100.219.4:14550`，目的為 Jetson `100.70.8.54:14550`（UDP），
  已確認收到的 MAVLink 訊息種類與短測平均更新率，詳見下節。
  後續使用 MAVLink router 或轉送程式分流，定位程式使用
  獨立 endpoint，原始遙測另送筆電 Tailscale IP 與 QGC 監聽 port，
  避免多個程序爭用同一接收 port 或形成轉送迴圈。
  同時確認 Tailscale 是直接連線或中繼；不以 WebRTC 流暢度判定
  遙測延遲。已用獨立程式驗證接收與解析；正式接收服務、轉送與定位
  整合仍待實作。
- **延遲測試：**WebRTC 照常播放時同步記錄 5～10 分鐘。若能在
  地面站端記錄轉送時間，先校準其與 Jetson 的時鐘並記錄校準誤差，
  再量測轉送段延遲中位數、P95、最大值；若無法記錄，先量測可取得
  的鏈路往返與接收間隔，不能當作完整單向延遲。
  另記姿態更新率、最長空檔、
  堆積後集中到達與飛控時間戳相對接收時間的延遲變化。
- **測量限制：**目前不假設轉送鏈路能與飛控雙向通訊，也不把飛控
  TIMESYNC 當作測試前提。單向資料若沒有可用的共同時間基準，
  無法準確量出飛控到 Jetson 的整段絕對延遲；飛控 `time_boot_ms`
  不能直接減 Jetson 時間。Tailscale ping 僅涵蓋被測兩端的網路
  往返，不包含飛控到地面站的遙測鏈路。Jetson 到筆電的顯示延遲
  不會增加 Jetson 計算時的遙測年齡。
- **雙向限制：**本備案先處理單向遙測接收與顯示。若筆電 QGC 還需
  發送控制指令，必須另行確認 Jetson、地面站至飛控的雙向路由；
  單向轉送不能視為控制鏈路已可用。
- **原備案保留：**若地面站無法把目的地設為 Jetson，仍可評估
  「地面站 → 筆電 QGC → Tailscale → Jetson」，由 QGC forwarding
  轉送；此時需另外測量筆電到 Jetson 的轉送延遲。
- **採用條件：**取得實測後，再依延遲變動、更新率與動作速度判斷
  能否和影格配對。先保存姿態歷史與時間戳，避免直接拿收到的最新
  姿態套到較舊影格；穩定延遲的校正值仍需實測。

參考：[QGC 遙測轉送](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/telemetry.html)、
[Tailscale 連線類型](https://tailscale.com/docs/reference/connection-types)、
[MAVLink 時間同步](https://mavlink.io/en/services/timesync.html)。

## 2026-10-03 備案實測：Tailscale／MAVLink UDP 14550

本次以獨立接收程式綁定 `0.0.0.0:14550`，只接收與解碼，沒有向飛控
傳送 MAVLink 指令。發送端 Tailscale IP 為 `100.100.219.4`（Android，
Tailscale 裝置名稱 `bengal-for-arm64`），Jetson 為 `100.70.8.54`。

- **收包結果：**接收程式結束時間為 **08:00:37.979 +08:00**，測試長度 **60.010 秒**，
  因此開始時間約 **07:59:37.970**。收到 **6,464 個 UDP datagram**，
  成功解碼 **6,464 個 MAVLink 訊息、36 種類型**，全部來源為
  `100.100.219.4:14550`。封包 magic 為 `0xFD`（MAVLink 2），
  system ID／component ID 都為 `1`，沒有解析成 `BAD_DATA` 的訊息。
- **介面證據：**同步以 dumpcap 在 `any` 介面擷取 60 秒，過濾
  `host 100.100.219.4 or port 14550`。擷取 **6,486 個封包**，擷取器
  回報 dropped **0**；其中 **6,485 個 IPv4 UDP 封包**的四元組為
  `100.100.219.4:14550 → 100.70.8.54:14550`。擷取與應用接收的起止
  時刻略有差異，數量差不能當成鏈路丟包率；本次未按 MAVLink sequence
  評估網路丟包。
- **先前未收包：**07:54:47 與 07:58:25 結束的兩次 60 秒監聽皆為
  0 個 UDP 封包；使用者確認發送設定後，本輪收到資料。期間沒有修改
  Jetson 防火牆或 Tailscale 設定，不能據此判定先前未收包的原因。
- **Tailscale 連通：**對發送端三次 ping 經 `DERP(hkg)`，回應為
  105、143、117 ms，當時未建立直接連線。此為網路往返時間，不能視為
  MAVLink 單向延遲。Tailscale health check 另回報 `iptables connmark`
  規則設定錯誤；本輪仍成功收包，尚未確認該錯誤的影響。

### 收到的訊息與主要屬性

下列頻率是 60 秒訊息總數除以觀察時間的平均值，不代表接收間隔均勻。

| 類型／用途 | 平均更新率 | 主要欄位／實測值 |
| --- | ---: | --- |
| `ATTITUDE`：機身姿態 | 約 10 Hz | roll／pitch／yaw、三軸角速度；最後姿態約 1.48°／0.76°／−131.60° |
| `GLOBAL_POSITION_INT`：位置與航向 | 約 3 Hz | lat／lon、alt／relative_alt、vx／vy／vz、hdg；經緯度皆 0，relative_alt = −3.557 m，hdg = 228.40° |
| `GPS_RAW_INT`：GPS 狀態 | 約 2 Hz | fix_type = 1、satellites_visible = 0、經緯度皆 0；無有效定位 |
| `SYS_STATUS`／`BATTERY_STATUS` | 約 2／3 Hz | 感測器狀態位元、負載、電壓／電流／剩餘電量；最後 24.74 V、0.30 A、95% |
| `VFR_HUD` | 約 10 Hz | airspeed／groundspeed／heading／throttle／alt／climb；最後 heading = 228°、throttle = 0 |
| `RANGEFINDER` | 約 3 Hz | distance／voltage；最後 distance 約 0.194 m |
| `DISTANCE_SENSOR` | 合計約 6 Hz | 收到 ID 1 與 10，每個約 3 Hz；擷取樣本分別為 19 cm（orientation 25）、37 cm（orientation 0） |
| `GIMBAL_DEVICE_ATTITUDE_STATUS` | 約 3 Hz | 四元數 q、flags、gimbal_device_id = 1、failure_flags = 0；角速度與 delta_yaw 為 NaN |
| `GIMBAL_MANAGER_STATUS` | 約 0.2 Hz | flags、雲台 ID、primary／secondary control sysid／compid |
| `RC_CHANNELS`／`SERVO_OUTPUT_RAW` | 各約 2 Hz | 16 個 RC 通道、RSSI 欄位及各路伺服 PWM |
| `SCALED_IMU`／`AHRS2` | 各約 10 Hz | 三軸加速度／角速度／磁場／溫度；另一組姿態與位置 |
| `RAW_IMU`／`SCALED_IMU2`／`SCALED_PRESSURE` | 各約 2 Hz | IMU、氣壓、溫度 |
| `HEARTBEAT`／`EXTENDED_SYS_STATE` | 各約 1 Hz | 心跳 type = 2、autopilot = 3、base_mode = 89、custom_mode = 5；延伸系統狀態 |

其餘類型包含 `SYSTEM_TIME`、`AHRS`、`TERRAIN_REPORT`、
`EKF_STATUS_REPORT`、`VIBRATION`、`ESC_TELEMETRY_1_TO_4`、
`ESC_TELEMETRY_5_TO_8`、`COMMAND_ACK`、`POWER_STATUS`、`MEMINFO`、
`NAV_CONTROLLER_OUTPUT`、`MISSION_CURRENT`、`FENCE_STATUS`、`MCU_STATUS`、
`PARAM_VALUE`、`STATUSTEXT`、`TIMESYNC`。完整 36 種訊息的數量、平均
頻率與每種類型最後解碼欄位見下列附件；同類型中的不同感測器 ID 會覆寫
該類型的最後樣本，逐筆資料應以原始 pcap 為準。

飛控 `STATUSTEXT` 實際收到兩種文字：`PreArm: GPS 1: Bad fix`、
`PreArm: Motors Emergency Stopped`。GPS 沒有 fix，本次位置與高度數值
只記為封包樣本，不能作為已驗證的定位結果。測距能否作為 AGL、雲台
四元數的座標系與安裝方向，也仍需另外確認。

### 保存的實驗資料與待辦

資料保存於 [`diagnostics/mavlink_tailscale_20261003_080037/`](../diagnostics/mavlink_tailscale_20261003_080037/)：

- [實際欄位與訊息頻率](../diagnostics/mavlink_tailscale_20261003_080037/decoded_fields.md)
- [接收統計、最後欄位與數值範圍 JSON](../diagnostics/mavlink_tailscale_20261003_080037/capture_summary.json)
- [原始 pcap](../diagnostics/mavlink_tailscale_20261003_080037/capture.pcap)
- [本次獨立監聽程式](../diagnostics/mavlink_tailscale_20261003_080037/monitor_mavlink_14550.py)：使用 pymavlink 2.4.50／ardupilotmega dialect；本次依賴臨時放在 `/tmp/mavlink-monitor-deps`，重跑時需準備依賴並調整路徑。

已驗證範圍為「指定 Tailscale 來源 → Jetson UDP 14550 → MAVLink 解碼」。
尚未實作 Jetson 到筆電 QGC 的分流、RTSP／YOLO 姿態整合或影格配對，
也未測量單向遙測延遲、最長接收空檔、重連恢復或長時間穩定性。
下一輪仍需保存逐筆接收時間與飛控時間戳，建立姿態歷史，並在 WebRTC
同時播放下做 5～10 分鐘更新率／間隔測試；有效 GPS 與目標定位需另驗證。

欄位與單位參考：[MAVLink common](https://mavlink.io/en/messages/common.html)、
[ArduPilotMega dialect](https://mavlink.io/en/messages/ardupilotmega.html)。

## 2026-10-06：GPS 歷史配對與暫停速度門檻

`GPSReader` 保存最近 1024 筆導航狀態變更（RMC 位置／fix、VTG
方向及串口連線狀態），使用 Jetson monotonic 時間查找影格接收時刻
之前最近的一筆。YOLO 不再使用較影格新的位置或方向；沒有可用歷史
時回報 `no_history`。無效 fix／斷線事件也會保存，位置超過 2 秒
仍禁止投影；VTG 更新不會刷新位置時間。

依使用者要求，`MIN_SPEED_FOR_COG_MPS` 暫設 `None`，RMC／VTG
有有限的方向數值便保存，無需達到 1 m/s，速度缺值也可接受。
方向缺值時保留之前收到的方向；從未收到方向則仍是 `no_course`。
靜止 COG 不等於機身 yaw，實際定位精度仍待驗證。

`python -m unittest diagnostics.test_direct_gps_history -v` 的 8 項
測試通過：歷史配對、未來資料排除、無效 fix／斷線、過期、低速與
缺速度方向、VTG 時間隔離、歷史上限與副本，以及恢復速度門檻。
本次未接實機 GPS／RTSP，尚未驗證瀏覽器框旁座標的端到端顯示。

## 2026-10-06：前端無畫面逾時恢復（2026-10-07 已移除）

以下保留當日的實作與測試紀錄；目前行為以次節 2026-10-07 的調整為準。

新增每秒一次的影片看門狗：WebRTC connected 後 10 秒未出第一張
畫面，或播放中 5 秒未出新影格，便關閉目前 peer 並排程重連。
使用 `requestVideoFrameCallback` 的實際影格進度；不支援時採
`framesDecoded` 增量。檢查在 `getStats()` 前執行，統計請求失敗或
卡住也不會停用逾時判斷。隱藏分頁不觸發此逾時，回前景時重設等待
時間；持續黑屏時重連退避為 1／2／4／8 秒，收到影格才恢復為 1 秒。
依使用者要求，未修改多頁面互踢、後端單一觀看連線政策。

`node diagnostics/test_direct_video_timeout.cjs` 的 11 項模擬測試
通過：首張逾時、持續收包／解碼卻停止顯示、正常影片、背景暫停與
回前景、解碼統計替代判斷、統計失敗／卡住、單次重連排程、退避、
收到影格後恢復退避，以及舊連線統計結果隔離。實機 RTSP／瀏覽器
端到端恢復仍待驗證。

## 2026-10-07：移除前端無畫面逾時重連

依使用者要求，移除前端「WebRTC connected 後 10 秒未出第一張
畫面」及「播放中 5 秒未出新影格」的強制重連。沒有其他斷線事件時，
前端保留目前 peer、來源時間基準與辨識歷史，等待影格恢復；持續
沒有畫面時，可由使用者手動重整網頁。不再設定前景／背景的影片
等待期限，`getStats()` 失敗或未完成也不會因無畫面觸發重連。

WebRTC `failed`／`closed`、框／座標 WebSocket 關閉、RTSP 健康
狀態顯示中斷，以及連線建立錯誤仍會觸發自動重連。保留 1／2／4／8 秒
退避，實際顯示新影格時重設為 1 秒；不支援影格 callback 時，仍以
`framesDecoded` 增量重設退避。每秒 RTP 統計、Canvas 時間配對及
後端單一觀看連線政策保留，未調整接收／送出 buffer 或跨重連補播。

後端原有 ICE `disconnected` 超過 5 秒關閉連線的規則未修改；另確認
本機 aiortc 1.15.0 的狀態實作不回報 `disconnected`，因此目前版本
不會由該狀態觸發這條規則。瀏覽器端仍可能出現 `disconnected`。

`node diagnostics/test_direct_video_timeout.cjs` 的 14 項模擬測試
通過，涵蓋首張等待超過 10 秒、停格超過 5 秒後沿用原連線恢復、
正常影片、背景與回前景、解碼停滯、統計失敗／卡住、WebRTC
失敗／關閉、WebSocket 關閉、RTSP 中斷、單次重連排程、退避及
影格／解碼進度重設退避、舊連線統計隔離。README 已同步更新。
本次未重新啟動實機串流，也未驗證遠端網路中斷後的實際恢復。

## 2026-10-06：Canvas 精簡與 class 配色

Canvas 保留偵測框，文字只畫 class 與目標經緯度兩行；座標缺值時
為 `--, --`。移除 Canvas 上的信心值、確認累計、PTS、gap、FPS、
GPS 診斷面板及每幀 DOM 診斷字串更新。連線狀態改由連線事件更新，
原 RTP 統計仍每秒更新於影片下方，影片／框時間配對與逾時恢復保留。

依 `test2.engine` metadata 的五種 class 固定配色：car 綠、
light_tactical 青、medium_tactical 黃、cm34 藍、
amphibious_armored_vehicle 紫。其他 class 自動配置非紅色色相。
粗體字級至少 24 CSS px，隨顯示寬度放大；標籤加暗底並限制在畫面
範圍內，不再以 confirmed 狀態變換 class 顏色。

已用實際前端腳本模擬確認五色、只有 class／座標文字、缺值處理、
標籤邊界與窄視窗字級；原 11 項影片逾時測試亦全部通過。
本次未做實機瀏覽器視覺驗證。

## 2026-10-06：啟動終端機的即時診斷

依使用者澄清，新增資訊顯示於啟動 `python -m rtsp_yolo_direct` 的
終端機，不增加 Canvas 診斷面板或瀏覽器回報端點。啟動事件印出
模型、tracker、傳輸方式、600 ms 接收 max_delay、送出緩衝與記錄
路徑；看門狗每 5 秒印一行 RTSP 收包、解碼進度、YOLO FPS／耗時／
佇列丟幀、GPS 狀態與每條 WebRTC 的送出進度、佇列及關鍵影格等待。
非 `health_sample` 事件立即印出，包含關閉原因、重連與錯誤。

`/api/health` 增加 source／decoder／YOLO thread 存活與解碼進度、
推論耗時及 skipped／dropped 計數、peer 的 track／metadata 佇列、
送出錯誤、設定，以及最近 16 次 peer 關閉時快照。每秒的
`health_sample` 現在也記錄 peers；修正 `_send_rtp` 同時承載 RTCP
造成的統計混淆，只有 RTP 影片會更新 `sent_packets`／`sent_bytes`／
`last_rtp_at`，RTCP 另計 `sent_rtcp_packets`。影片轉送及單一觀看
連線政策維持原流程。`ice_closed` 仍不能單靠後端判定瀏覽器關閉的
具體原因，前端重連 reason 與解碼／顯示統計尚未回報。

8 項後端測試通過，涵蓋終端輸出、5 秒週期、完整取樣、推論跳過／
替換計數、解碼例外、RTP／RTCP 區分、關閉快照與送出錯誤；既有
8 項 GPS 測試亦通過。此次未重新啟動實機串流。

## 2026-10-06：遠端觀看的兩種連線備案（待實作）

目標是提高遠端觀看穩定性，使用者可以接受較高延遲。保留現行
Tailscale 方案，另外規劃 Cloudflare TURN 與公網 VPS／WireGuard
兩種模式；目前尚未實作、部署或完成穩定性比較。
正式顯示內容為影片、辨識框／class 與目標經緯度。

### 方案一：Cloudflare TURN＋DataChannel

後續討論補充：初版可先保留現有 WebSocket，經 Cloudflare Tunnel
傳送框／座標，降低整合範圍；以下 DataChannel 架構可後續再做，
不是避開 Tailscale／DERP 的必要前提。測試方向與容錯問題見下節。

- **影片與框／座標：**WebRTC 傳送 H.264 影片，DataChannel 傳送
  辨識框、class、目標經緯度及配對所需的來源 PTS／generation。
  使用固定 relay 策略，確保媒體與 DataChannel 經 Cloudflare TURN；
  DataChannel 不會自動與影片逐幀同步，仍需按來源時間戳配對。
- **網頁與信令：**在 Jetson 執行 `cloudflared`，以 Cloudflare Tunnel
  提供 HTTPS 網頁、`/offer` 及必要 HTTP API。Tunnel 負責 HTTP，
  影片與 DataChannel 由 TURN 中繼；此模式的觀看流程不依賴 Tailscale。
- **連線維護：**自動取得及更新有期限的 TURN 憑證，處理過期與
  中斷後的重連。比較 TURN／UDP 與 TURN／TLS（TCP 443）的實際
  穩定性及延遲；傳輸切換與重連仍可能造成播放中斷。

參考：[Cloudflare TURN](https://developers.cloudflare.com/realtime/turn/)、
[TURN FAQ](https://developers.cloudflare.com/realtime/turn/faq/)、
[Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)。

### 方案二：公網 VPS＋WireGuard

- **路徑：**Jetson 與觀看端分別主動連線到具有固定公網 IP 的 VPS，
  經 WireGuard 隧道與 VPS 轉送。VPS 需開放指定 UDP port 並設定
  轉送路由，避免依賴兩端直接 NAT 打洞與 Tailscale DERP。
- **程式整合：**可沿用 WebRTC 影片與 WebSocket 框／座標傳輸，
  讓網頁、信令、影片與框／座標都經 WireGuard 路徑。需限制或驗證
  ICE 選路，確保媒體實際經 VPS，而非仍選到其他介面的直連候選。
- **限制：**WireGuard 仍依賴 UDP；公網固定端點能減少打洞的條件，
  不能保證 UDP 永不中斷。依需要設定 NAT keepalive 與中斷恢復。

參考：[WireGuard 設定與 NAT keepalive](https://www.wireguard.com/quickstart/)。

### 三種模式共存與驗證

- 保留原版及各模式的獨立設定／啟動入口，一次只啟動一個串流服務，
  避免共用 port、相機、GPU 與 GPS 的資源衝突。
- WireGuard 使用不重疊的獨立網段與指定路由，避免接管整台主機的
  預設路由／DNS；啟動入口自動管理隧道，非 VPS 模式時關閉該隧道。
  Cloudflare 的 TURN 設定只套用到對應模式，HTTP Tunnel 另行管理。
- 完成初次設定後，日常操作以選擇啟動入口切換，不需每次手動修改
  網路設定。各模式需實測媒體路徑、播放穩定性、中斷恢復及框／座標
  對齊；目前不宣稱任一方案已解決所有卡頓或斷線。

## 2026-10-06：應用 UDP、TURN 測試與對齊容錯的討論紀錄

本節整理從「UDP 送包過於集中」推測開始的後續討論。
使用者可以接受較高延遲與暫時卡頓，希望避免影片直接中斷、反覆
重連，或在有辨識結果時持續沒有框／座標。以下區分假設、目前
程式行為與待實作方向；本次僅更新紀錄，未修改程式或部署連線方案。

### 應用程式 UDP 影響 DERP 的假設（尚未證實）

- 待驗證的因果鏈為：**應用程式 UDP 送包過於集中 → 排隊、掉包
  → 直連探測收不到回應 → 使用 DERP**。一次短暫掉包不等於一定
  切換；目前沒有證據證明這就是實際斷線的原因。
- Tailscale 選路依據是直連路徑是否仍有效，沒有「內層是 UDP 就
  改走 DERP」的規則。不過應用程式的速率、送包尖峰及流量控制
  可能間接影響路徑；不能用「TCP／UDP 在 Tailscale 直連時外層
  都是 UDP」來排除應用程式送包方式的影響。
- 目前程式轉送已壓縮 H.264，以來源 PTS 控制送幀時刻；安裝的
  aiortc 將同一幀的 RTP 分片接連送出。這條轉送路徑沒有重新編碼
  來降低相機碼率，平均流量低也不能單憑此排除短時間尖峰。
  以上是程式行為，尚未證明尖峰造成直連探測失敗。
- 使用者觀察到以前 MJPEG／TCP 經 Tailscale 時較少黑畫面與反覆
  重連，支持比較送包方式與容錯反應；確切舊版尚未確認，也不是
  固定條件的 A/B 測試，不能單憑這個觀察判定根因。

### 換掉 Tailscale 能改善哪些環節

- 固定走 Cloudflare TURN，或公網 VPS／WireGuard，兩個方案都能
  讓整個觀看流程避開 Tailscale。移除 Tailscale 後，便沒有其
  direct／DERP 選路與切換這一層；固定公網中繼也改變了原先兩端
  直接打洞的條件。若主要問題在這些環節，有機會改善穩定性。
- 若排隊／掉包的瓶頸在 Jetson、路由器或 4G 接入鏈路，換成
  TURN／UDP 或 WireGuard 仍可能遇到。網路掉包與連線恢復機制
  可以共同影響結果，不能把原因簡化為只屬於 Tailscale 或網路。
- TURN／TLS 使用 TCP 的壅塞控制與重傳，可能改善部分 UDP 路徑
  問題，但可能增加等待與卡頓，也不會增加原本的網路容量。
  固定 TURN 仍保留 WebRTC 的 ICE／consent 檢查，長時間無回應
  一樣可能中斷；不保證永不斷線。

### 目前傾向與測試方向（待實作）

- 長期方案的推薦順序仍為 **Cloudflare TURN 優先，公網
  VPS／WireGuard 次之**。使用者傾向直接先測 Cloudflare，省去
  為偵錯另外架設 coturn 的步驟，也先移除 DERP 這個變因。
- Cloudflare TURN 同時支援 UDP 與 TLS／TCP 443。先前提議固定
  TLS 是為了接續「先測 TCP」的想法，不代表 Cloudflare 只能用
  TLS；可在同一個 TURN 服務下分別測 UDP、TLS。兩種模式都需
  固定 relay 並確認實際媒體路徑，僅加入 TURN 設定不代表必經 TURN。
- 最小整合方向：H.264 影片經 TURN；網頁、`/offer`、API 及現有
  框／座標 WebSocket 經 Cloudflare Tunnel。現有前端已按網頁
  協定選擇 `ws`／`wss`；DataChannel 可後續整合。只有影片移出去、
  網頁或 WebSocket 仍經 Tailscale，不算整個觀看流程已避開它。
- 目前安裝的 aiortc／aioice 沒有可直接切換媒體直連 TCP 的開關，
  可透過 TURN 使用 TCP／TLS。現有 `--transport tcp` 控制的是
  **相機 → Jetson 的 RTSP**，不是 Jetson → 瀏覽器的 WebRTC。
- coturn＋Tailscale 的 UDP／TCP 對照是額外偵錯思路，用來保留
  Tailscale 路徑比較內層傳輸，並非兩個正式方案的必要步驟。
  Cloudflare 同時更換傳輸路徑；即使變穩，也不能單憑這項結果
  證明原本是應用程式 UDP 觸發 DERP。
- 「優先 UDP、失敗改 TLS」需實作回退與重連，不能當成無縫自動
  切換。驗證應記錄實際傳輸路徑、影格進度、停格／重連、資料到達
  間隔及影片／辨識 PTS 差距，而不只看 `/api/health` 的 healthy。

### 已確認：目前程式可能放大不穩定連線的影響

| 條件 | 目前行為與可能結果 |
| --- | --- |
| 框／座標 WebSocket 關閉 | 原版會呼叫整體 `reconnect()` 並關掉 WebRTC；**GCP 版於 2026-10-07 已改成資料通道獨立重連**，詳見本文頂部。 |
| 播放中約 5 秒沒有新影格，或 connected 後 10 秒沒有首張畫面 | **2026-10-07 已移除此強制重連條件**；沒有其他斷線事件時保留目前連線等待恢復，持續無畫面可手動重整網頁。 |
| 找不到可用的影片／辨識配對 | 每個顯示影格先清空 Canvas，無配對便沒有框與座標；配對失敗本身不會關閉影片。 |

對齊使用同一來源 generation 的結果，選擇
`ptsSeconds <= videoPts + 0.005` 的最近一筆，並要求
`videoPts - ptsSeconds < 1`。這個 **1 秒是來源 PTS 的差距**，
不是網路延遲超過 1 秒就停止顯示。辨識資料持續落後影片達 1 秒，
或影片落後太多而對應資料已被淘汰出最近 **180 筆**歷史，便可能
持續沒有疊圖；180 是結果筆數，能涵蓋多久取決於實際 YOLO 更新率。

首張／停格逾時重連已於 2026-10-07 移除；待調整方向為資料通道
獨立恢復，以及依兩路延遲差調整對齊緩衝的保留範圍。加大影片 buffer 並非單獨的
完整解法；也需確保對應辨識資料仍保留。換 Cloudflare 或改用
DataChannel 不會自動修正上述容錯與配對條件，仍需分開驗證。

程式依據：[前端對齊／重連](web.py)、[送幀與關鍵影格等待](source.py)、
[後端連線檢查](server.py)。協定參考：
[Tailscale 連線機制](https://tailscale.com/docs/reference/connection-types)、
[UDP 傳輸建議](https://www.rfc-editor.org/rfc/rfc8085.html)、
[WebRTC consent 檢查](https://www.rfc-editor.org/rfc/rfc7675.html)、
[Cloudflare TURN](https://developers.cloudflare.com/realtime/turn/)、
[Cloudflare WebSocket 支援](https://developers.cloudflare.com/network/websockets/)。

## 待辦：目標確認規則

2026-10-03 已新增啟動參數 `--tracker legacy|bytetrack`，預設 `legacy`，
保留原本 `TargetTracker` 與 conf=0.3 的流程。修改前完整模組已保存於
[`diagnostics/rtsp_yolo_direct_before_bytetrack_20261003.zip`](../diagnostics/rtsp_yolo_direct_before_bytetrack_20261003.zip)。
ByteTrack 模式使用 conf=0.1 取得低信心偵測，高信心配對／新軌跡門檻
均為 0.3；低信心配對只延續 ID，不增加確認累計。確認仍需累計兩次
至少 0.3 的有效配對，並且僅輸出有當次偵測配對的框。
`--bytetrack-buffer` 預設 5，按 YOLO 更新次數計算；來源重連或 PTS
間隔超過 1 秒／倒退／重複時重置 ByteTrack。詳見 [使用方式](README.md)。
合成偵測已驗證 ID 延續、低信心配對、漏檢後恢復、空偵測不輸出框、
來源重置與預設開關；兩種模式的結果管線、信心門檻、確認與 GPS 防護
均通過檢查，原 TargetTracker 與備份內容一致。實際 RTSP 的追蹤品質、
  推論耗時與延遲仍待 A/B 實測。

- 隔幀推論已啟用；若要比較前後效果，需記錄影片顯示流暢度、
  YOLO 更新率、PTS 差距、推論耗時與 Jetson 負載。
- 重新討論目標確認規則：目前 `TargetTracker` 以偵測框中心距離
  **60 px 內**配對，每次配對累加 `count`，達 **2 次**即確認；YOLO
  信心度門檻為 **0.3**。中間
  漏檢不會清零，連續缺席超過 **5 次 YOLO 更新**才移除候選。
  因此「連續 2 次」並不精確，且目前配對沒有要求偵測類別相同。
  隔幀推論後需一起決定確認次數／時間窗、漏檢容忍度、
  距離門檻與是否限制同類別，並檢查確認速度和誤配率。
