# UAV 專案近兩週成果總結

整理日期：2026-10-15（Asia/Taipei）

涵蓋期間：2026-10-01～2026-10-15，至少近兩週。

本文件依專案程式、Git 近期變更、各版本現況文件與 `diagnostics/` 實測紀錄整理，包含尚未提交的工作目錄變更。可確認的最新主要開發與實測紀錄集中在 10/13；未將缺少紀錄的 10/14～10/15 寫成已完成的新成果。以下測試數據均來自既有紀錄，本次整理未重新執行相機、GPS、GPU 或雲端驗收。

## 一、這兩週完成了什麼

專案在既有 Jetson RTSP／YOLO 架構上，完成 GPS 更新與歷史配對、串流及資料通道的重連調整、GCP 遠端觀看部署、STUN／TURN 選路，以及三類偵測加軍車細分類。另建立分類與追蹤實測工具，透過日誌、系統鏈路事件及同影格對照，區分相機停流、觀看端連線與模型／追蹤問題。

主要成果如下：

1. **影片與辨識分流持續完善**：同一條 RTSP 接收來源，壓縮 H.264 封包直接轉送 WebRTC；Jetson 另行硬體解碼供 YOLO，每兩個來源影格推論一次。瀏覽器依來源 RTP timestamp／PTS 配對偵測框。
2. **GPS 資料使用更完整**：SAM-M8Q 已實測 5 Hz；加入最多 1024 筆導航狀態歷史，依影格抵達 Jetson 的時間選取之前最近的 GPS 狀態，避免拿較新的位置套用到較舊影格。
3. **遠端連線有多種可比較版本**：完成強制 GCP TURN、STUN 直連搭配 TURN 備援，以及 WebRTC DataChannel metadata 版本；GCP HTTPS／WSS 反向代理與 Jetson WireGuard 隧道已取得部署及連通證據。
4. **新增軍車二階分類**：`test3.engine` 先偵測三類，只有 `military_car` 送入 `classifier_fp16.engine`，再分為 CM34、輕型戰術車、中型戰術車。
5. **追蹤與顯示更明確**：分類版內部保留漏檢 ID 0.5 秒，僅輸出實際偵測框；不再以預測補框顯示目標。細分類以同 ID 最近數次結果多數決，減少瞬間類別跳動。
6. **留下可追查的實測證據**：GPS、MAVLink、五分鐘本機播放、TURN／DataChannel、分類跳動、ByteTrack 同影格比較及 10/13 斷線調查，皆有報告或原始紀錄。

目前已完成多版本實作與分項驗證；有效 GPS 目標座標精度、跨網路完整流程與長時間耐久仍有待驗收項目。

## 二、工作時間線

| 日期 | 主要工作 | 成果與驗證範圍 |
| --- | --- | --- |
| 10/01 | GPS 5 Hz、RTSP 接收緩衝調整 | GPS 五分鐘串口監測通過；FFmpeg 接收 `max_delay` 設為 600 ms。使用者回報播放延遲改善，尚無改善幅度的量測。 |
| 10/03 | MAVLink 接收、ByteTrack 選項 | Tailscale → Jetson UDP 14550 收包及解碼成功；新增 `legacy／bytetrack` 切換。 |
| 10/05 | 本機串流同步與遠端路徑檢查 | 本機 Chromium 連續播放五分鐘正常；另記錄遠端 Tailscale direct／DERP 切換。 |
| 10/06 | GPS 歷史配對、Canvas 精簡、診斷擴充 | 加入歷史查找及 GPS 過期防護；框上僅顯示類別與座標；終端、health 與事件增加來源、推論、佇列及 peer 資訊。 |
| 10/07 | GCP TURN 版本、重連行為調整 | 雙端 relay-only TURN；metadata WebSocket 獨立重連；GCP 版送出緩衝改為 300 ms；移除截圖及單純無畫面逾時造成的強制重連。 |
| 10/08 | GCP HTTPS／WSS、WireGuard、DataChannel | 雲端反向代理與隧道完成部署／handshake；另建 DataChannel 版本，實際 GCP TURN 合成影片與資料測試成功。 |
| 10/09 | STUN／TURN 自動選路、原版同步更新 | 新增 STUN 版；直連與 relay 合成完整應用測試通過。原版加入 metadata 獨立重接、移除截圖，送出緩衝改為 300 ms。 |
| 10/12 | 固定斜拍 GPS 投影、上傳測速工具 | 直傳與 STUN 版改用 AGL 110 m、pitch -50° 的地面投影；新增 HTTP 上傳測速腳本。 |
| 10/13 | 原版 TURN 備援、8 秒門檻、分類與追蹤整合 | 原版補入 STUN／TURN；建立兩個分類版本；完成分類 GPU 檢查、短測、追蹤比較及相機 LAN 斷線調查。 |

## 三、串流、前端與診斷成果

### 3.1 影片／辨識時間配對

沿用 H.264 封包直傳，避免為瀏覽器疊框再把整段影片解碼、畫框、重編碼。YOLO 結果透過獨立 metadata 傳輸，Canvas 再對到正在播放的來源影格。

接收與送出緩衝分開設定：RTSP 接收端 `max_delay=600000` 微秒；直傳版 WebRTC 送出緩衝於 10/09 由 150 ms 改為 300 ms，讓辨識結果有更多時間抵達。300 ms 是設定值，不能視為整體端到端延遲。

10/05 本機五分鐘測試取得 301 筆樣本：全部 `healthy=true`、瀏覽器 connected；RTSP 重連 0 次、RTP lost 0、未取樣到影格停滯或 PTS 倒退。影片與 YOLO 的來源 PTS 差距中位數 33.37 ms、最大 33.38 ms。這個差距衡量來源時間配對，並非相機曝光到螢幕顯示的延遲，也不代表遠端路徑或長時間耐久已通過。

依據：[本機五分鐘報告](diagnostics/direct_sync_20261005_103047/report.md)、[直傳版現況](rtsp_yolo_direct/CURRENT_STATUS.md)。

### 3.2 重連與頁面調整

- 移除「connected 後 10 秒無首幀」及「播放中 5 秒無新影格」的前端強制重連；單純等不到畫面時保留 peer 與來源時間基準。
- WebSocket metadata 可獨立重連，退避為 1／2／4／8 秒，建立連線逾時 10 秒。資料中斷保留影片、RTP origin 與偵測歷史；舊框超過有效期會清除。
- 隔離舊連線事件及較晚回來的 health／統計結果，避免干擾新連線。
- 直傳版於 10/13 將 RTSP timeout 與 ICE disconnected 等待門檻設為 8 秒；WebRTC failed／closed、來源重建等事件仍有重連處理。
- Canvas 精簡為類別與經緯度兩行，缺座標顯示 `--, --`；五類使用固定配色，標籤有暗底、邊界限制與隨視窗調整的字級。
- 移除近期直傳／GCP 路徑的截圖按鈕、API 及背景存圖處理，保留既有截圖檔案。

### 3.3 診斷工具與可觀測性

啟動終端每 5 秒顯示 RTSP 收包、解碼、YOLO 更新率與耗時、跳過／丟棄影格、GPS 狀態及 peer 送出進度。`/api/health` 與每秒 `health_sample` 增加執行緒存活、佇列、錯誤、設定及最近 peer 關閉快照；RTP 與 RTCP 分開計數。較新版本還記錄 ICE 所選候選 pair，辨別直連與 TURN。

新增 [upload_speed_test.py](upload_speed_test.py)，可設定資料量、次數、IPv4／IPv6 並輸出 JSON，測量單條 HTTP 連線的有效上傳吞吐量；目前沒有可在本報告列為成果的上傳速度數值。此工具的結果也不能直接代表 TURN／Tailscale 的影片吞吐量。

分類版另有 [stop_rtsp_yolo_direct_cls.py](stop_rtsp_yolo_direct_cls.py)，辨識指定模組程序、送出 SIGTERM 並等待正常關閉，必要時可明確指定強制停止。

## 四、GPS 與飛控遙測成果

### 4.1 SAM-M8Q 5 Hz 與歷史配對

GPS 每次開啟串口時設定 200 ms 更新週期，9600 baud 下保留 RMC／VTG。10/01 實測 300.1 秒，兩種訊息各收到 1499 筆；RMC 平均 5.000 Hz，中位間隔 200.0 ms、最長 201.5 ms，NMEA 解析／checksum 錯誤 0 筆。

10/06 加入有界導航狀態歷史，將位置、fix、方向與串口連線變化一併保存。影格使用 `receive_mono_ns` 查找當時之前最近的狀態；無歷史、無效 fix、斷線、未收到方向或位置超過 2 秒，均不輸出目標座標。VTG 更新不會刷新位置時間。依需求暫停 COG 的最低速度門檻，低速或缺速度但有有限方向值時仍可保存。

目前較新版本預設 GPS 路徑為 `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`；10/01 的 `/dev/ttyUSB4` 是當天枚舉結果。GPS 歷史配對的 8 項離線測試已有通過紀錄。

所有上述五分鐘 GPS RMC 都是無效定位；已驗證的是頻率、接收與配對邏輯，尚未驗證有效 fix、目標經緯度或精度。配對時間是抵達 Jetson 的 monotonic 時間；尚未加入可設定的固定延遲校正或驗證斷電後的設定保存。

依據：[GPS 實測](diagnostics/GPS_5HZ_20261001.md)、[GPS 歷史測試](diagnostics/test_direct_gps_history.py)、[目前 GPS 設定與投影](rtsp_yolo_direct/gps.py)。

### 4.2 固定斜拍地面投影

10/12 將直傳版與 STUN 版更新為針孔視線旋轉後與平坦地面求交點，預設 AGL 110 m、pitch -50°、HFOV 49.4°、VFOV 29.7°、相機方向偏移 0°，畫面上方視為正前方。新增 `--camera-pitch-deg`，分類版本沿用此設定。

依這組幾何條件，畫面中心投影約在前方 92.3 m，上／下緣約 156.2／51.6 m。無地面交點時仍保留偵測框，省略目標座標。投影、GPS 歷史及相關模組共 57 項離線回歸測試已有通過紀錄。

模型仍假設平坦地面、roll 為零、pitch 固定，使用 GPS COG 近似機頭方向，尚未做鏡頭畸變校正或接入即時飛控／雲台姿態，因此不能把幾何測試視為實際定位精度驗收。

依據：[投影測試](diagnostics/test_direct_gps_projection.py)、[直傳版現況](rtsp_yolo_direct/CURRENT_STATUS.md)。

### 4.3 Tailscale／MAVLink 接收備案

10/03 完成地面站經 Tailscale 到 Jetson UDP 14550 的獨立接收與解碼。60.010 秒收到 6464 個 datagram，解碼 6464 筆 MAVLink 2 訊息、36 種類型，沒有 `BAD_DATA`；同步封包擷取器回報 dropped 0。

收到機身 `ATTITUDE` 約 10 Hz、雲台 `GIMBAL_DEVICE_ATTITUDE_STATUS` 約 3 Hz，以及位置、速度、GPS、測距等資料。當次飛控 GPS 無有效定位；已確認能收到姿態資料，尚未接入 YOLO 目標投影，也未實作 Jetson 到筆電 QGC 的分流或量測單向遙測延遲。

依據：[MAVLink 欄位與頻率](diagnostics/mavlink_tailscale_20261003_080037/decoded_fields.md)。

## 五、GCP、TURN、STUN 與 DataChannel 成果

### 5.1 GCP 公網觀看架構

10/07～10/08 完成 GCP TURN 程式版本，以及 WireGuard＋Nginx 的 HTTPS／WSS 觀看入口。網頁、signaling、health 與 WebSocket metadata 由 GCP Nginx 經隧道代理 Jetson:8081；影片使用 WebRTC TURN。觀看端的設計目標是直接開 HTTPS 頁面。

部署紀錄確認 Nginx、WireGuard、登入保護、WebSocket Upgrade、IP 憑證及自動續期設定。Jetson 核心缺少 WireGuard 模組，安裝腳本補上 userspace fallback，並修正 Ubuntu 套件實際執行檔 `/usr/bin/wireguard` 的命名差異。後續取得 service active／enabled、GCP handshake、隧道 HTTP 200，以及公網 HTTPS 401／TLS 驗證成功的證據。

10/08 實際觀看紀錄曾顯示 relay／relay、metadata connected、YOLO 約 13.4 FPS；使用者也回報看到公網影片。其後 8081 停止監聽，沒有足夠退出資訊可確定原因。這些是當時的部署與觀看證據；本次沒有重新查驗目前雲端服務或憑證狀態，30 分鐘耐久與有效 GPS 驗收仍未通過。

依據：[GCP 現況](rtsp_yolo_direct_with_gcp/CURRENT_STATUS.md)、[部署與驗收接續文件](rtsp_yolo_direct_with_gcp/NEXT_STEP.md)。

### 5.2 STUN 直連與 TURN 備援

10/09 新增 `rtsp_yolo_direct_with_gcp_stun`，雙端 ICE policy 預設 `all`，提供 STUN、直連候選及 TURN 備援；可用 `--ice-transport-policy relay` 強制中繼。頁面與 health 以實際 nominated pair 判讀路徑，包含只有一端 relay 的情形。10/13 將相同選路功能加入原直傳版。

實際 GCP STUN／TURN 分項測試取得公網映射，並以合成 H.264 驗證 host／host 直連與 relay／relay。另以本機 GStreamer RTSP 測試來源，完成 H.264 直傳、Jetson 硬體解碼、`test2.engine` 推論與 WebSocket origin／detection metadata；原 GCP 版、新版 `all` 及新版 `relay` 三種情境均接收 5 幀 640×360，程序正常退出。

10/09 下午的既有使用紀錄另確認 STUN 版有兩條成功的實際觀看連線，包含一條先用 TURN、後選到 Tailscale 位址直連。這不等於不靠 Tailscale 的公網打洞已全面驗收，也不代表網路中斷時能無縫切換。

依據：[STUN 版現況](rtsp_yolo_direct_with_gcp_stun/CURRENT_STATUS.md)、[連線使用紀錄](diagnostics/connection_usage_20261009_after1500/README.md)。

### 5.3 WebRTC DataChannel metadata 版本

10/08 新增 `rtsp_yolo_direct_with_gcp_and_datachannel`，以可靠、有序的 DataChannel 傳送 RTP origin 與 YOLO／GPS JSON，移除這個版本的 `/events/<peerId>` WebSocket 路由。影片與資料共用 DTLS／ICE transport，保留待送大小限制與同 peer 的資料通道重建。

同機雙 aiortc peer 經實際 GCP TURN UDP 的測試，解碼 6 張 160×120 H.264 影格並核對 2 筆模擬 metadata。關閉第一條資料通道後，第二條通道重新送出相同 origin；影片保持 connected、RTP 計數持續增加，全程只有一次 offer。Python 26 項、前端 29 項測試已有通過紀錄；正式相機、遠端瀏覽器與有效 GPS 完整流程仍待驗收。

依據：[DataChannel 現況](rtsp_yolo_direct_with_gcp_and_datachannel/CURRENT_STATUS.md)。

## 六、三類偵測、軍車細分類與追蹤

### 6.1 二階模型整合

10/13 新增 `rtsp_yolo_direct_cls`，完整保留串流、GPS、ICE、WebSocket 與診斷，再加入三類偵測及軍車細分類：

| 第一階偵測結果 | 第二階處理 | 最終顯示 |
| --- | --- | --- |
| `car` | 直接使用偵測結果 | `car` |
| `military_car` | 裁切實際偵測框，送入分類器 | `cm34`／`light_tactical`／`medium_tactical` |
| `amphibious_armored_vehicle` | 直接使用偵測結果 | `amphibious_armored_vehicle` |

分類器使用原生 TensorRT execution context。`classifier_fp16.engine` 已在 Jetson GPU 載入並推論，實際輸入 FP32 `[1,3,224,224]`、輸出 FP32 `[1,3]`；三組合成影像的最高類別與 ONNX 一致，機率最大差約 0.0169，原 0.01 嚴格數值門檻未通過並已有紀錄。

分類模型未就緒或失敗時，三類偵測與串流繼續運作，軍車顯示 `military_car`，並定期重試載入。分類前處理目前為 RGB、直接縮放 224×224、ImageNet 正規化；`preprocessing_verified` 仍為 false，類別索引與前處理需向訓練端核對。

### 6.2 投票、ID 保留與實際框顯示

目前分類版預設每個 ID 最近 **7 次**實際分類做等權重多數決，第一次就能顯示分類；平票優先保留目前並列最高票的類別。分類紀錄不影響 car／兩棲車的第一階結果。

漏檢期間內部保留 ID 與分類紀錄 0.5 秒，位置／尺寸預測只供重新配對。後端不輸出預測補框，前端也忽略 `observed: false` 並依最後實際偵測期限清框；漏檢時不重新分類或更新 GPS。來源 generation 變更、PTS 倒退／重複或影格間隔過大時重置歷史。ByteTrack 為可選模式，預設仍為 legacy。

### 6.3 分類跳動實測

10/13 另以同一場景做 5 秒及 30 秒獨立 RTSP／GPU 短測，沒有啟動 HTTP／WebRTC／GPS；當時明確使用**最近 5 次**投票，與目前預設 7 次分開解讀。

- **5 秒目標短測**：72 次推論，目標沒有漏檢或換 ID；原始及顯示分類都是 CM34，切換 0 次。
- **30 秒目標短測**：423 次推論，目標沒有漏檢或換 ID；原始分類切換 24 次，投票後切換 2 次。顯示 CM34 420 次、輕型 3 次，輕型顯示約 0.239 秒。
- **同影格固定裁切對照**：上述 423 個影格全部判為 CM34、切換 0 次；同一張裁切重跑五次機率差為 0，支持這次偵測框裁切範圍浮動是分類跳動的重要因素。
- 另有中央偏下的實際 YOLO 重疊框，可能是前景設備／電線附近的誤檢；已與選定目標分開統計。這些框不是追蹤補出的預測框。

投票能減少瞬間跳動，也會帶來少量恢復延遲；投票比例 100% 不等於單次模型機率 100%。以上是特定場景的穩定性觀察，沒有足夠標註資料可宣稱整體分類準確率。

依據：[分類版說明](rtsp_yolo_direct_cls/README.md)、[5 秒報告](diagnostics/cls_live_20261013_085814/report.md)、[30 秒報告](diagnostics/cls_live_20261013_090523/report.md)。

### 6.4 ByteTrack 與 legacy 同影格比較

10/13 保存 30 秒、390 次推論的同一批 YOLO 候選，比較 ByteTrack 實際輸出與 legacy 回放。兩者都只輸出實際匹配框、保留 ID 0.5 秒；legacy 使用 >=0.3 的候選，ByteTrack 可延續 >=0.1 的低信心候選。

| 指標 | legacy 回放 | ByteTrack 實際輸出 |
| --- | ---: | ---: |
| 有框更新 | 314／390 | 359／390 |
| 有框比例 | 80.51% | 92.05% |
| 出現／消失切換 | 53 次 | 10 次 |
| ID 變更 | 4 次 | 2 次 |

ByteTrack 回傳 48 次低於 0.3 的匹配框，對這個目標能減少閃爍並延續 ID；但仍有配對失敗、無候選及最長消失約 0.757 秒。這是同場景、包含候選門檻策略差異的對照，不能直接推廣為所有場景的追蹤品質；正式預設模式未因此改為 ByteTrack。

依據：[同影格追蹤比較](diagnostics/cls_live_20261013_092738/tracking_report.md)。

### 6.5 GCP STUN 與分類整合版本

同日新增 `rtsp_yolo_direct_with_gcp_stun_cls`，結合 STUN 版連線／部署工具及分類版的偵測、追蹤、GPS、Canvas。預設 port 8082，保留 ICE 路徑資訊並增加分類器狀態。78 項 Python 與 34 項前端回歸測試已有通過紀錄；該整合版本尚未完成相機／GPS／GPU／遠端瀏覽器完整實測。

依據：[整合版現況](rtsp_yolo_direct_with_gcp_stun_cls/CURRENT_STATUS.md)。

## 七、斷線與停流調查的結論

10/06 的歷史檢查分析 34 份執行紀錄、12654 筆 health，約 3.51 小時取樣；確認部分遠端測試有 direct／DERP 反覆切換，且 ICE 關閉時來源／YOLO 仍正常。另有持續直連及來源停流時段，不能把所有卡頓歸因於 DERP。

10/13 最近一週檢查分析原直傳版 29 份紀錄、15353 筆 health，約 4.26 小時取樣；10/09 有四段來源停流，其中一次約 7 分 49 秒才恢復，其他在該次服務結束前未見恢復。沒有 `disconnected_timeout`，因此沒有證據支持原 5 秒 ICE 等待門檻是主要重連原因。錯誤重試次數、`ice_closed` 次數與獨立故障次數必須分開解讀；上述兩份統計有時間重疊，也不是連續兩週監控。

10/13 上午分類版斷線調查，確認相機介面 **eth1 有實體 link down／up**；Tailscale 隨介面位址消失而重新綁定。09:36 的 RTSP 停流早於 09:37 的鏈路中斷，不能把最初停流歸因於 Tailscale；後續亦觀察到 metadata 重連時影片仍 connected。最後 09:39:25 有 `server_shutdown／server_stopped`，屬服務關閉。

現有資料可區分來源停流、實體鏈路、Tailscale 路徑與 metadata 中斷，但不足以斷言每次根因是線材、供電、相機韌體、驅動或觀看端網路。後續應先固定線材與供電條件，補相機／交換器及觀看端日誌，保留程序輸出與退出碼，再做受控耐久測試。

依據：[10/06 健康與路徑檢查](diagnostics/health_review_20261006.md)、[10/13 週檢查](diagnostics/direct_week_review_20261013.md)、[10/13 斷線調查](diagnostics/disconnect_review_20261013/report.md)。

## 八、目前各版本的位置

以下為目前工作目錄的版本與預設值；不同版本可能使用相同 port，啟動時需選擇一版或明確指定其他 port。

| 模組 | 預設 port | 偵測／分類模型 | 連線與 metadata |
| --- | ---: | --- | --- |
| `rtsp_yolo_direct` | 8080 | `test2.engine` 五類偵測 | STUN／直連＋TURN 備援；WebSocket |
| `rtsp_yolo_direct_with_gcp` | 8081 | `test2.engine` 五類偵測 | 強制 TURN；WebSocket；附 WireGuard 部署工具 |
| `rtsp_yolo_direct_with_gcp_and_datachannel` | 8081 | `test2.engine` 五類偵測 | 強制 TURN；DataChannel |
| `rtsp_yolo_direct_with_gcp_stun` | 8082 | `test2.engine` 五類偵測 | STUN／直連＋TURN 備援；WebSocket |
| `rtsp_yolo_direct_cls` | 8080 | `test3.engine`＋`classifier_fp16.engine` | STUN／直連＋TURN 備援；WebSocket；二階分類 |
| `rtsp_yolo_direct_with_gcp_stun_cls` | 8082 | `test3.engine`＋`classifier_fp16.engine` | STUN／直連＋TURN 備援；WebSocket；二階分類與部署工具 |

近期模型從原先 `11s_car_960.engine` 延伸至 `test2.engine` 五類直接偵測，再新增 `test3.engine` 三類偵測＋獨立分類器。原始三類與最終五類顯示應分開解讀；分類器未就緒時保留 `military_car`。

GCP Nginx 的既有部署紀錄指向 Jetson 8081；分類與 STUN 版本的程式整合完成，不代表雲端代理已自動切到新版本。

## 九、驗證紀錄與後續待完成項目

既有紀錄包含：10/09 原版更新 50 項回歸測試；10/12 投影及相關模組 57 項；10/13 原版 TURN 44 項 Python／31 項前端；分類版 77 項 Python／34 項前端；STUN 分類整合版 78 項 Python／34 項前端。各組測試有重疊，不能加總為獨立測試總量；本文件未重新執行這些測試。

仍需完成的工作：

1. **有效 GPS 與定位精度**：戶外取得穩定 fix，驗證影格歷史配對、框旁座標與地面已知點誤差；核對相機實際 FOV、安裝方向、高度及固定斜拍假設。
2. **分類器訓練設定與準確率**：核對 `class_to_idx`、RGB／BGR、縮放／裁切及正規化；建立有標註的真實影像評估。裁切平滑目前是診斷後的建議，尚非已完成的正式行為。
3. **跨網路與耐久驗收**：選定一個版本，測真實相機、GPU、GPS、遠端瀏覽器、實際 ICE pair、重連與至少 30 分鐘連續運作，記錄端到端延遲及框／影片來源時間差。
4. **相機 LAN 與程序退出原因**：查 eth1 網路線／接頭、上游供電與設備日誌，保留服務終端輸出、退出碼、RTP／RTCP／RTSP 與觀看端紀錄。
5. **動態姿態與時間校正**：MAVLink 已收包，但即時飛控／雲台姿態歷史、定位整合、QGC 分流及 GPS 固定延遲校正仍待實作與驗證。

本階段已具備影片直傳、五類顯示、GPS 配對與投影、遠端多路連線及可追查診斷的完整程式基礎；下一次驗收應集中在選定版本的真實完整流程、定位／分類品質與長時間穩定性。
