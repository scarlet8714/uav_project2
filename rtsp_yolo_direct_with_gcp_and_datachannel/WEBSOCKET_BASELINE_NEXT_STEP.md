# 複製時的 WebSocket 版本接續文件（歷史參考）

以下保留來源版本的安裝、網路與串流查核步驟；目前 DataChannel 版本請讀
[NEXT_STEP.md](NEXT_STEP.md)。不要把下方舊模組啟動命令當成本版命令。

# Jetson 接續：WireGuard + GCP HTTPS／WebSocket

更新：2026-10-08（UTC）。此文件供下一位在 **Jetson** 操作的人／代理接續。
本次使用者已授權此方案；**GCP 安裝已完成，現在從 Jetson 前置核對開始。**

最新接續點（2026-10-08 05:40 UTC）：單次查詢 health 為 Connection refused，主機
8081 未監聽且串流程序已不在；此次僅查核，尚未重啟。事件紀錄最後更新為台灣 13:35:58，
當時 RTSP／YOLO／TURN relay/relay／metadata 正常，GPS invalid_fix，程序退出原因未確定。
請參考第 4 節重新啟動命令，保留終端輸出及退出碼供後續診斷。

先前已完成：GCP 已登記 Jetson peer，使用者回傳近期 handshake 成功。
Jetson wg-uav 為 active／enabled，使用 `/usr/bin/wireguard`；公網 GCP 路由維持 eth0。
**串流已於 05:26:55 UTC 啟動，本機與 WireGuard 位址的 8081 health 均為 healthy=true**。
該次串流後來由使用者確認公網畫面可見，事件確認 TURN relay/relay 與 metadata 連線。
第 1～3 節保留供查核及重新設定，18 項安裝腳本測試通過。
GPS 有收到資料但沒有有效 fix；觀看卡頓、斷線、疊圖與耐久仍待完整驗收。

## GCP 已完成與確認的部分

2026-10-08 **04:45:27 UTC** 安裝成功，狀態為 `gcp_ready_waiting_for_jetson`。
本次核對了 GCP 安裝包中的 `setup-state.json`、`relay-info.json`、
`firewall-readback.json`、`setup.log`，以及實際部署的 Nginx／systemd 設定與啟動連結。

- GCP 防火牆 `uav-web-relay-ingress` 與 VM 標記讀回成功，兩個判定皆為 true。
  僅帶 `uav-web-relay` 標記的 VM 放行 TCP 80／443、UDP 51820；原 MAVLink／TURN 標記保留。
- 安裝完成前已檢查 `wg-quick@wg-uav.service`、`nginx.service`、
  `uav-web-relay-cert-renew.timer` 皆 active／enabled；本次也確認其開機啟動連結存在。
- Nginx 已部署 HTTPS 與 WebSocket 代理，upstream 是 `http://10.77.0.2:8081`，
  綁定 GCP 隧道來源 `10.77.0.1`，有 Upgrade／Connection 標頭，代理緩衝關閉。
- 安裝時 **VM 本機 HTTPS 驗證通過，未登入回應 401**；使用受信任的正式 IP 憑證，
  檢查沒有略過 TLS 驗證。HTTP 的 ACME 路徑保留，其餘請求轉 HTTPS。
- 憑證 SAN 為 `104.155.197.179`；此次記錄的到期時間是
  **2026-10-14 19:46:42 UTC**（台灣時間 2026-10-15 03:46:42），續期後會改變。
- 憑證續期 dry-run 已通過；timer 每天 UTC 00:00／12:00 檢查，隨機延後最多 30 分鐘。
  成功換證後執行 `nginx -t` 再 reload。保留 TCP 80 供後續續期。
- 網頁帳號 `uav`，隨機密碼保留在 GCP 的 `web-login.txt`（600）；
  Nginx 帳密檔為 640、WireGuard 設定目錄為 700。本文件不含密碼或私鑰。

**仍待實機驗證：** Jetson 公鑰登記、WireGuard handshake、GCP → Jetson 8081、
觀看端公網 HTTPS／WSS、TURN 影片、框／GPS 與耐久測試。
`end_to_end_verified` 仍為 false。工具環境不能管理真正 VM 的服務；此次從工具嘗試
直連公網 443 沒有取得 HTTP 回應，因此不能把上述本機 HTTPS 成功視為觀看端連通已驗證。

GCP 安裝包位於 `/home/scarlet8714/gcp_web_relay_setup/`。
**不需要重跑 GCP 安裝、重新產生 GCP 私鑰，或再次處理 Apache2。**
此前的 Apache2 80 埠衝突與防火牆讀回誤判均已越過；Nginx 已接手，
Apache2 的開機啟動連結已不存在。防火牆修正的 21 項離線測試通過，實際雲端讀回也已成功。

若要從 GCP 再核對本次安裝紀錄，可讀取以下不含私鑰的檔案：

```bash
cat /home/scarlet8714/gcp_web_relay_setup/setup-state.json
cat /home/scarlet8714/gcp_web_relay_setup/relay-info.json
cat /home/scarlet8714/gcp_web_relay_setup/firewall-readback.json
```

這些是安裝當下的紀錄；後續即時狀態仍以 `wg show`、systemctl、curl 與瀏覽器實測為準。
尚未連上 Jetson 時，HTTPS 未登入為 401；輸入正確帳密後 upstream 仍不可達，
出現 502／504 是此階段可能的結果，不需要重裝憑證或把 8081 開到公網。

## 固定架構與設定

```text
瀏覽器 HTTPS／WSS
  → GCP 104.155.197.179:443 Nginx（登入保護）
  → WireGuard 10.77.0.1 → 10.77.0.2:8081 Jetson
  → 現有網頁、POST /offer、/events/<peerId>、/api/health

影片 WebRTC
  → 沿用現有 GCP TURN 3478、UDP relay 49160–49200
```

| 項目 | 值 |
| --- | --- |
| GCP 專案／VM／zone | `project-5f8f1817-eb20-4a35-a41`／`uavproject`／`asia-east1-a` |
| GCP 已保留的公網 IP | `104.155.197.179`，位址名稱 `uavproject-ip`（使用者提供的實際輸出） |
| WireGuard 介面／入口 | `wg-uav`／`104.155.197.179:51820` UDP |
| GCP／Jetson 隧道 IP | `10.77.0.1/32`／`10.77.0.2/32` |
| MTU／Jetson keepalive | `1280`／`25` 秒 |
| Jetson 服務 | TCP `8081`，不開放 GCP 公網 8081 |
| 觀看網址 | `https://104.155.197.179/` |
| 網頁帳密 | 帳號 `uav`；密碼在 GCP 安裝包的 `web-login.txt`，權限 600 |

只有 Jetson ↔ GCP 安裝 WireGuard，觀看電腦不需要 VPN，也不需要固定 IP。
本次繼續使用框／GPS WebSocket，沒有改用 DataChannel。
Nginx 只代理網頁與資料，影片仍走 TURN；不要把 TURN URL 改成 WireGuard IP。

## 1. Jetson 前置核對

先讀取本資料夾的 README、CURRENT_STATUS 與實際啟動方式。原版 `rtsp_yolo_direct`
保留，不要為了接 WireGuard 重寫既有 RTSP／H.264／YOLO／GPS／PTS 程式。

在 Jetson 的普通終端執行：

```bash
cat /etc/os-release
uname -r
ip -4 route get 104.155.197.179
ip -4 route show table all
ip rule show
tailscale status
sudo ss -lntup
```

確認：

- GCP 公網 IP 走實體上網介面（例如 eth0／wlan0／行動網路介面），不是 tailscale0
  或另一個 VPN。若正在使用 exit node，先查明路由；安裝腳本會拒絕透過該 VPN 建隧道，
  不會替你關閉 exit node 或更動 Tailscale。
- `10.77.0.1`、`10.77.0.2` 不與相機、區網、VPC 或其他 VPN 路由衝突。
  不要加入 `0.0.0.0/0`、`::/0`，不指定 WireGuard DNS。
- 有原本可執行本程式的 Python／GPU 環境、根目錄 `test2.engine` 與此版 `.turn.env`。
  GCP 的檔案副本不包含模型與 TURN 密碼，不能假設複製資料夾就自動帶齊。
  保留既有 TURN 帳密，不要把它寫進此文件。
- 記下目前串流啟動命令、GPS 裝置與 tracker 等參數，後續接入沿用。
  先設定隧道，等準備切換串流時再停止舊程式，避免兩份程式占用相機／GPU／GPS。

## 2. 安裝 Jetson WireGuard

Jetson 安裝所需的兩個檔案已複製到本資料夾的 `jetson_setup/`，會隨專案一起帶到 Jetson：

- [jetson_setup/setup_jetson_wireguard.py](jetson_setup/setup_jetson_wireguard.py)
- [jetson_setup/relay_config.py](jetson_setup/relay_config.py)

不需再另外複製專案外的 `~/gcp_web_relay_setup/`。兩個檔案應保留在同一個資料夾，
安裝腳本會從旁邊的 `relay_config.py` 載入設定；GCP 安裝包的原檔仍保留。

目前 GCP 的真實 WireGuard 公鑰如下，來源是安裝成功後的 `relay-info.json`：

```text
OWLiMFkAHHr3Mx58Bodkcs0FBAG/0M5Q4UJBBbBlDRc=
```

公鑰可以交換並記錄；如日後主動輪替 GCP 金鑰，需改用最新 `gcp_public_key`。
不要複製 `web-login.txt`、任何 `/etc/wireguard/*.key` 或整份含私鑰的設定。

在 Jetson 普通終端執行，以下為目前實際專案路徑：

```bash
cd /home/jetson/Desktop/uav_project2
GCP_PUBLIC_KEY='OWLiMFkAHHr3Mx58Bodkcs0FBAG/0M5Q4UJBBbBlDRc='
sudo python3 rtsp_yolo_direct_with_gcp/jetson_setup/setup_jetson_wireguard.py --gcp-public-key "$GCP_PUBLIC_KEY"
```

腳本適用 Ubuntu／Debian + systemd、Python 3.8 以上，會安裝 `wireguard-tools` 與
`wireguard-go`（`--no-install-recommends`），在 Jetson 本機產生私鑰，
建立 `/etc/wireguard/wg-uav.conf`（600），並啟用開機啟動。
Jetson 的 `AllowedIPs` 只有 `10.77.0.1/32`，不接管相機、一般上網或 Tailscale 路由。
若 UFW 已開啟，僅增加「wg-uav 上，來自 10.77.0.1，目的 10.77.0.2:8081 TCP」規則。
沒有設定其他防火牆時先依連通性查核，不要清空既有規則。

最後會印出 `JETSON_PUBLIC_KEY=...`。這是下一步要交給 GCP 的公鑰；
私鑰只留在 Jetson，**不需把私鑰貼回來**。
重跑相同設定會沿用原私鑰；遇到不同的既有設定會停止，避免覆寫。

此 Jetson 的 `5.15.136-tegra` 核心未啟用 `CONFIG_WIREGUARD`，但有 TUN 支援與
`/dev/net/tun`。原腳本只安裝 `wireguard`；本機副本已修正為上述兩個套件。
Ubuntu 套件提供的執行檔是 `/usr/bin/wireguard`；腳本會偵測 `wireguard-go` 或 `wireguard`，
在 `/etc/systemd/system/wg-quick@wg-uav.service.d/10-uav-userspace.conf` 設定
`WG_QUICK_USERSPACE_IMPLEMENTATION` 並執行 daemon-reload，讓 wg-quick 原生介面建立失敗後
找到正確的 userspace 備援。此設定僅承載網頁／資料，
影片仍走 TURN，沒有升級 JetPack 或核心。
若看到核心介面建立失敗及 userspace fallback 訊息，仍以後續服務、介面、路由檢查為準；
若 service 最後失敗，收集 `uname -r`、`ls -l /dev/net/tun` 與
`sudo journalctl -u wg-quick@wg-uav -n 50 --no-pager`，不要把套件安裝成功當成隧道成功。
依據：[wg-quick 的 userspace fallback](https://git.zx2c4.com/wireguard-tools/plain/src/wg-quick/linux.bash?h=v1.0.20210914)、
[wireguard-go 使用方式](https://git.zx2c4.com/wireguard-go/about/)。

本機腳本離線測試（不安裝套件、不建立介面、不接觸相機）：

```bash
python3 -m unittest discover -s rtsp_yolo_direct_with_gcp/jetson_setup -p 'test_*.py' -v
```

## 3. 在 GCP 登記 Jetson 公鑰

在 **GCP 普通 SSH 終端**執行：

```bash
sudo python3 /usr/local/lib/uav-web-relay/manage.py add-peer 'eVzlMTWyULFmOJgRwxEteKOc+crsKkgaZtz2JH4fbFw='
```

以上是本次 Jetson 安裝成功後回傳的公鑰；若日後主動輪替 Jetson 金鑰，需改用新公鑰。
會把 peer 存入 GCP 的設定並即時套用；GCP 的 AllowedIPs 只有 `10.77.0.2/32`。
同一公鑰可重跑，已有不同 Jetson 則停止。不要重啟 TURN 或 MAVLink。

兩端確認：

```bash
sudo wg show wg-uav
sudo systemctl is-active wg-quick@wg-uav
```

看到近期 `latest handshake`，傳輸 bytes 持續增加，才算隧道接通。
Jetson keepalive 是 25 秒，剛登記便查詢時可能還沒有 handshake；約 30 秒後再查一次。
Jetson 再確認 `ip -4 route get 10.77.0.1` 為 wg-uav，
`ip -4 route get 104.155.197.179` 仍為實體上網介面。
沒有 handshake 就先查公鑰、GCP UDP 51820、防火牆與現場網路 UDP，不要先修改串流程式。

## 4. 接入現有 Jetson 程式

本次已執行下方啟動命令（實際專案位於 `/home/jetson/Desktop/uav_project2`），
使用系統 Python 3.10 與既有使用者套件、`legacy` tracker、預設 GPS 裝置。
事件紀錄在 `diagnostics/gcp_turn_20261008_132655/`；本機 127.0.0.1 與
10.77.0.2 的 health 曾通過。05:40 UTC 查核時該程序已不在，8081 未監聽；
目前需依下方命令重啟後再做 GCP 確認，並保留終端輸出與退出碼。

準備好切換時，先記錄並停止舊串流，只啟動本資料夾的版本；使用原本 Python 環境。
以下是基本命令，原本 GPS／tracker／相機參數不同時應保留實際值：

```bash
cd /home/jetson/Desktop/uav_project2
python -m rtsp_yolo_direct_with_gcp \
  --rtsp-url rtsp://192.168.144.135/live \
  --model-path test2.engine \
  --host 0.0.0.0 --port 8081 \
  --playout-delay-ms 300
```

專案不在 `~/uav_project2` 時使用實際路徑。若 GPS 尚未接上，可用既有 `--no-gps`
做階段性驗證並記錄；不要宣稱 GPS 已通過。`--host 0.0.0.0` 保留原本的
Tailscale 入口，也讓 WireGuard IP 可以存取；不要只綁 localhost 或 Tailscale IP。
原版與新版可以保留在硬碟，實測時只跑一份、只開一個觀看分頁。

Jetson 本機確認：

```bash
curl --noproxy '*' --fail --max-time 5 http://127.0.0.1:8081/api/health
```

GCP 確認：

```bash
curl --noproxy '*' --fail --max-time 5 http://10.77.0.2:8081/api/health
```

兩者都應有 JSON；檢查前端版本 `20261007.3`、RTSP／YOLO／GPS 及 TURN 設定。
之後才用觀看端開 `https://104.155.197.179/`，輸入 GCP `web-login.txt` 的帳密。
網頁登入密碼與 TURN 密碼是兩組不同用途的帳密。
HTTPS 憑證應受信任，**不要用略過憑證錯誤或 curl -k 作為驗收**。

## 5. 實際驗收與紀錄

以下全部依實際結果紀錄，不要只以 health API 有回應判定完成：

1. GCP／Jetson 有近期 WireGuard handshake；觀看端關掉 VPN 後，GCP 網址仍可開啟。
2. HTTPS 網頁、`POST /offer` 和 `/api/health` 成功。瀏覽器 Network 中
   `wss://104.155.197.179/events/<peerId>` 為 **101**，持續收到 metadata。
3. 影片成功播放；`/api/health` 的 `peers` 顯示已連線，`ice_pair` 為
   `local_type=relay`、`remote_type=relay`、`relay_verified=true`。
   WireGuard 不會替代 TURN 驗證，TURN 的 UDP 路徑仍需可用。
4. YOLO 框／GPS 正常，沿用來源 PTS 對齊與 300 ms pacing；GPS 沒有有效 fix 時分開記錄。
5. 保留只中斷 metadata 就獨立重連的行為，不加回首張畫面／停格強制重連。
   有條件時短暫中斷 **Jetson WireGuard** 測試 WSS 恢復；影片是否持續播放也記錄實況。
   只停用 wg-uav，不關閉實體網路；重新啟用後隧道／資料應恢復。
6. 觀察至少 30 分鐘，記下卡頓、重連時間、`peer_closing` 原因與當時 WG／TURN 狀態。
   `wg show` bytes 是流量，不是丟包統計；需丟包資訊時另看 WebRTC 接收統計。
7. GCP 續期 timer 啟用，安裝時續期 dry-run 通過。IP 憑證約六天，不能略過續期。
   WireGuard／Nginx／續期已設定開機啟動；本次沒有替 Jetson 相機程式新增 systemd service。

驗證完成後，在本資料夾的 CURRENT_STATUS 補上實際兩端設定日期、路由、版本、
handshake、WSS 101、TURN relay/relay、GPS、耐久測試與續期結果；此文件也更新為
已完成或列出未完成項目。不要覆蓋原本歷史量測，也不要把密碼／私鑰寫進紀錄。

## 故障時先看哪裡

| 現象 | 優先查核 |
| --- | --- |
| 公網 HTTPS 逾時 | GCP TCP 443 規則、VM 標記、主機防火牆、Nginx 監聽 |
| HTTPS 401 | 尚未登入或帳密錯誤；用網頁帳密，不是 TURN 帳密 |
| 登入後 502 | WG peer／handshake、GCP → 10.77.0.2 路由、Jetson 程式／8081／防火牆 |
| HTTPS 可開但 WSS 不通 | `/events/*` 的 101、Upgrade 標頭、登入、Nginx 錯誤日誌 |
| 網頁與 metadata 正常但沒有影片 | TURN 3478、relay UDP 49160–49200、帳密與 relay/relay；另查相機來源 |
| 後續 HTTPS 憑證過期 | 續期 timer／service 日誌、TCP 80 ACME 路徑與部署 reload hook |
| 又一直被其他連線取代 | 關閉舊頁面，查 `superseded_by_new_offer`，保留單一觀看分頁 |

GCP 常用查核：

```bash
sudo tail -n 50 /var/log/nginx/uav-web-relay-error.log
sudo journalctl -u wg-quick@wg-uav -n 40 --no-pager
sudo journalctl -u uav-web-relay-cert-renew.service -n 40 --no-pager
sudo systemctl list-timers uav-web-relay-cert-renew.timer --all
```

若要恢復原 Tailscale 方案，先停止本次串流，再按原先啟動命令跑原版；
不需要移除 Tailscale 或把路由改成 VPN 全流量。隧道不使用 DERP，也沒有 UDP 封鎖時
自動改走其他中繼的機制，穩定程度仍以此環境實測為準。

設定依據：[WireGuard keepalive](https://www.wireguard.com/quickstart/)、
[Nginx WSS 代理](https://nginx.org/en/docs/http/websocket.html)、
[IP 憑證與續期要求](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。
