# GCP 近期工作重點整理

整理日期：2026-10-17（UTC）。主要開發與測試紀錄為 2026-10-07～10-13，另參考 10-17 的 MAVLink 本機日誌。

本文件只整理 GCP 相關工作，依現有程式、部署狀態檔及測試紀錄彙整；本次未重新部署、啟停服務或執行遠端驗收。文中的成功結果代表當次測試，不代表目前雲端服務持續正常。

## 1. 目前完成到哪裡

- **GCP 公網觀看入口已部署**：Nginx 提供 HTTPS／WSS，經 WireGuard 連回 Jetson，已有隧道握手、TLS 驗證及實際公網觀看紀錄。
- **TURN 中繼已驗證**：UDP／TCP 3478 均完成認證、雙向傳輸與合成 H.264 播放；正式相機也留下 TURN 觀看紀錄，但長時間穩定性尚未通過。
- **STUN 直連與 TURN 備援已整合**：可讓 ICE 選擇直連或中繼，頁面與 health 顯示實際路徑；合成來源的完整應用測試通過。
- **DataChannel 版本已完成**：將框／GPS 資料與影片放在同一組 WebRTC transport，已驗證經 GCP TURN 傳輸及資料通道獨立重建。
- **GCP STUN＋分類整合版已建立**：保留既有雲端連線架構並加入二階分類，本機回歸測試通過，完整實機流程待驗收。
- **同台 VM 的其他服務**：MAVLink UDP relay 已安裝為 systemd 服務；Tailscale Peer Relay 有本機設定成功紀錄，但管理端授權與實際中繼路徑仍未驗證。

## 2. GCP 架構與入口

| 項目 | 現有設定／部署紀錄 |
| --- | --- |
| VM／區域 | `uavproject`／`asia-east1-a` |
| GCP 專案 | `project-5f8f1817-eb20-4a35-a41` |
| 公網 IP／觀看網址 | `104.155.197.179`／`https://104.155.197.179/` |
| HTTPS／WSS | Nginx TCP 443；TCP 80 用於轉址及憑證驗證 |
| WireGuard | UDP 51820；GCP `10.77.0.1` ↔ Jetson `10.77.0.2` |
| Nginx upstream | `http://10.77.0.2:8081` |
| STUN／TURN | `104.155.197.179:3478`；TURN relay UDP 49160–49200 |

資料路徑分為兩部分：

```text
網頁／signaling／WebSocket 框與 GPS：
瀏覽器 → GCP HTTPS／WSS Nginx → WireGuard → Jetson:8081

影片：
強制 TURN 版：Jetson → GCP TURN → 瀏覽器
STUN 版：    Jetson → 瀏覽器直連，或經 GCP TURN 中繼

DataChannel 版：框／GPS 與影片共用 WebRTC 的 DTLS／ICE transport。
```

影像解碼、YOLO 與分類仍在 Jetson 執行，GCP 負責入口代理及網路中繼。透過公網 HTTPS 入口觀看時，觀看端不需要安裝 WireGuard；Tailscale Peer Relay 則是另一套需要同一 tailnet 的備案。

## 3. 近期完成的主要工作

### 10/07：GCP TURN 與連線恢復

- 新增 `rtsp_yolo_direct_with_gcp`，預設 port 8081，Jetson 與瀏覽器均限制使用 TURN relay。
- 保留 H.264 壓縮封包直傳；框／GPS 使用 WebSocket，依來源 PTS 配對畫面。
- WebSocket 改為獨立重連，採 1／2／4／8 秒退避，資料斷線不再直接重建影片連線。
- 移除單純等待首幀或停格造成的前端強制重連；送出緩衝調整為 300 ms。這是緩衝設定，並非端到端延遲實測值。
- TURN 設定檔排除於 Git；health 與事件增加實際 `relay/relay` 路徑資訊。

### 10/08：公網 HTTPS／WSS、WireGuard 與 DataChannel

- GCP 部署 Nginx、網頁登入保護、正式 IP 憑證、自動續期與 WireGuard；防火牆及 VM 標記讀回成功。
- 修正 Apache2 占用 TCP 80、安裝腳本誤判分開的 TCP 防火牆項目等部署問題。
- Jetson 缺少 WireGuard 核心模組，安裝腳本加入 userspace fallback，並修正 `/usr/bin/wireguard` 的執行檔命名差異；後續取得服務 active／enabled 與 handshake 證據。
- 使用者曾確認公網影片可見，事件同時確認 TURN `relay/relay` 與 metadata 連線。其後 Jetson 串流程序消失、8081 未監聽，退出原因尚未確認。
- 另新增 `rtsp_yolo_direct_with_gcp_and_datachannel`，以可靠、有序的 DataChannel 取代該版本的 WebSocket metadata，保留同 peer 的資料通道重建。

### 10/09：STUN 直連與 TURN 備援

- 確認既有 coturn 可提供 STUN，沿用 UDP 3478 防火牆；該次 GCP 設定檢查無需修改或重啟 coturn。
- 新增 `rtsp_yolo_direct_with_gcp_stun`，預設 port 8082、ICE policy `all`，保留直連候選及 TURN 備援。
- 可用 `--ice-transport-policy relay` 強制中繼；頁面與 health 依實際選中的 ICE pair 判斷直連／TURN。
- 完成實際 GCP STUN 回應、合成 H.264 直連及 TURN 測試；另以本機 RTSP 測試來源驗證硬體解碼、YOLO 與 WebSocket metadata。
- 既有觀看紀錄包含成功連線及 Tailscale 位址直連；這仍不能視為不同電信網路之間的公網 NAT 穿透已全面驗收。

### 10/13：GCP STUN 與分類功能整合

- 新增 `rtsp_yolo_direct_with_gcp_stun_cls`，預設 port 8082，沿用 STUN 版連線及部署工具。
- 整合三類偵測與軍車細分類，保留框／GPS、來源 PTS 對齊及 metadata 獨立重連。
- 78 項 Python、34 項前端回歸測試已有通過紀錄；尚未完成該版本的真實相機、GPU、GPS 與跨網路瀏覽器完整驗收。
- **既有 Nginx 仍代理 Jetson 8081**。新增版本不會自動切換雲端入口；要沿用入口，需先停止舊服務，再以 `--port 8081` 啟動選定版本。

## 4. 已取得的驗證證據

| 項目 | 紀錄中的結果 | 驗證範圍 |
| --- | --- | --- |
| TURN UDP／TCP | 兩種傳輸均取得 relay／relay，完成雙向資料傳輸及 5 幀 160×120 H.264 解碼 | 同台 Jetson 的兩個測試端經實際 GCP TURN；屬短測 |
| HTTPS／WireGuard | 隧道握手、HTTP 200、公網 HTTPS 未登入 401、TLS 驗證成功 | 當時的部署與連通證據，並有使用者公網觀看回報 |
| DataChannel | 經 TURN 解碼 6 幀，核對 2 筆模擬 metadata；重建資料通道後影片保持 connected，全程一次 offer | 同機雙 peer、合成影片，非遠端正式相機驗收 |
| STUN 完整應用 | 原 TURN 版、STUN `all`、STUN `relay` 三種情境，均收到 5 幀 640×360 與 origin／detection metadata | 本機 GStreamer RTSP 來源，未使用 GPS |
| STUN 分類整合版 | Python 78 項、前端 34 項通過 | 本機回歸與模擬整合，非完整實機驗收 |

以上均為既有測試結果，本次整理沒有重新執行；各版本回歸測試有重疊，不加總為獨立測試總量。

## 5. 各 GCP 版本的差異

| 模組 | 預設 port | 影像路徑 | 框／GPS 資料 | 用途 |
| --- | ---: | --- | --- | --- |
| `rtsp_yolo_direct_with_gcp` | 8081 | 強制 TURN | WebSocket | 固定中繼的比較基準 |
| `rtsp_yolo_direct_with_gcp_and_datachannel` | 8081 | 強制 TURN | DataChannel | 驗證影片與資料共用 WebRTC |
| `rtsp_yolo_direct_with_gcp_stun` | 8082 | 直連＋TURN 備援 | WebSocket | 比較直連及中繼路徑 |
| `rtsp_yolo_direct_with_gcp_stun_cls` | 8082 | 直連＋TURN 備援 | WebSocket | STUN 連線加二階分類 |

同 port 的版本不可同時綁定；正式比較時也應避免多份程式同時占用相機、GPU 與 GPS。

## 6. 同台 GCP 的其他相關工作

### MAVLink UDP relay

- 針對舊 TCP relay 在 `sendall()` 阻塞、連帶卡住 UDP 接收與新連線登記的問題，另建非阻塞 UDP 雙向轉發版本。
- 遙控器入口為 UDP 14550，QGC 入口為 UDP 14551；依收到的 QGC 來源 IP／port 回傳，支援變動位址。
- 10/08 的安裝紀錄確認 `mavlink-relay-udp.service` 已啟動並設定開機啟動，UDP 14551 的 GCP 防火牆規則也已讀回驗證成功。
- 10/17 08:50 UTC 的本機日誌仍持續寫入 STATUS，已有歷史雙向轉發計數；該次取樣沒有活躍遙控器／QGC，不能據此認定當時端到端通訊正常。UDP 送出計數也不等於對端實際收到。

### Tailscale Peer Relay

- 準備 GCP UDP 40000 的 Peer Relay，與 WebRTC TURN 分開；用途是在 Tailscale 直連不可用時提供另一條中繼路徑。
- 狀態檔記錄 `local_verified=true`，階段為 `gcp_ready_waiting_for_tailnet_policy_and_client_test`；`tailnet_policy_verified` 與 `end_to_end_verified` 仍為 false。
- 觀看授權已改為同 tailnet 的 `autogroup:member`，不再逐台綁定觀看端 IP；目前仍缺管理端政策發布與實際 `peer-relay` 路徑證據。
- 安裝包 README 開頭仍保留「尚未啟用」的舊描述；本摘要以狀態檔區分「本機設定已確認」及「完整中繼尚未驗證」。

## 7. 尚待完成的 GCP 驗收

1. **選定版本，完成至少 30 分鐘跨網路測試**：確認 HTTPS、影像、框／GPS、實際 ICE pair、重連次數與停格情況。
2. **查明串流程序消失原因**：下次保留 Jetson 終端輸出、退出碼與事件，區分程序退出、相機停流、metadata 中斷及網路路徑問題。
3. **驗證直連／TURN 的不同網路情境**：STUN 不保證打洞成功，TURN 備援也不代表斷線時能無縫切換。
4. **補齊傳輸與維護驗證**：目前一次只設定一個 TURN URL，沒有 UDP 失敗自動改 TCP，也尚未設定 `turns:`；HTTPS 憑證續期的目前結果需另查實際服務紀錄。
5. **完成整合版與備案驗收**：補 STUN 分類版真實完整流程、Peer Relay 授權及使用證據，以及 MAVLink 的 QGC 遙測／任務傳輸驗證。

## 8. 主要參考文件

- [GCP TURN 現況](rtsp_yolo_direct_with_gcp/CURRENT_STATUS.md)與[部署接續文件](rtsp_yolo_direct_with_gcp/NEXT_STEP.md)
- [STUN／TURN 現況](rtsp_yolo_direct_with_gcp_stun/CURRENT_STATUS.md)
- [DataChannel 現況](rtsp_yolo_direct_with_gcp_and_datachannel/CURRENT_STATUS.md)
- [GCP STUN 分類整合版現況](rtsp_yolo_direct_with_gcp_stun_cls/CURRENT_STATUS.md)
- [10/09 實際連線紀錄](diagnostics/connection_usage_20261009_after1500/README.md)
- 專案外的同主機紀錄：[Web relay 安裝包](../gcp_web_relay_setup/README.md)、[STUN 安裝包](../gcp_stun_setup/README.md)、[Peer Relay 狀態檔](../gcp_peer_relay_setup/setup-state.json)、[MAVLink 使用說明](../MAVLINK_RELAY_UDP.md)、[systemd 安裝紀錄](../install_mavlink_udp_service.log)。這些檔案不會隨本專案 Git 一起帶走。
