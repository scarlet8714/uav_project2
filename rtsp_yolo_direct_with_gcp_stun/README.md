# RTSP + YOLO／GPS + GCP STUN 直連與 TURN 備援

驗證結果見 [CURRENT_STATUS.md](CURRENT_STATUS.md)：兩版共 95 項回歸測試與本機 RTSP 完整流程已通過。

2026-10-09 複製自 `rtsp_yolo_direct_with_gcp`。來源版本保留強制 TURN；此資料夾的
預設 ICE policy 改為 `all`，瀏覽器與 Jetson 同時使用：

- STUN：`stun:104.155.197.179:3478`。
- TURN：沿用複製過來的 `.turn.env` 帳密與 URL，預設 `turn:104.155.197.179:3478?transport=udp`。

ICE 可選 host／srflx／prflx 直連，或 TURN relay 路徑。一般候選優先序偏好直連，
直接路徑不可用時可選 TURN；最終由 ICE 的連通性檢查與提名決定，不保證每個網路都直連。
STUN 用來取得公網映射，不中繼影像。WebRTC 仍傳送相機 H.264 壓縮封包，
YOLO、GPS、PTS 對齊及 WebSocket 資料獨立重連沿用來源版本。

Canvas 的 class 名稱與目標座標使用固定 20 px 粗體文字，不加黑底。

RTSP 開啟／讀取逾時預設為 8 秒，可用 `--rtsp-timeout` 覆寫。
後端在 ICE `disconnected` 持續超過 8 秒後關閉觀看連線；監測每秒執行一次。
已執行的服務需重新啟動生效，啟動時明確指定的 RTSP 逾時仍優先使用。

目標 GPS 使用固定姿態與平坦地面的近似投影，預設參數如下：

| 參數 | 預設值 |
| --- | ---: |
| `--altitude-agl-m` | 110 m（相機到地面的垂直高度） |
| `--camera-pitch-deg` | -50°（0° 水平，-90° 垂直向下） |
| `--camera-yaw-offset-deg` | 0°（畫面上方為正前方） |
| `--hfov-deg` | 49.4° |
| `--vfov-deg` | 29.7° |

用針孔相機近似建立視線，依固定 pitch 旋轉後與平坦地面求交點。
預設設定下，畫面中心約在前方 92.3 m，上緣約 156.2 m，下緣約 51.6 m。
方位仍用 GPS COG 近似機頭方向，roll 假設為零；未接入即時飛控／雲台
姿態或鏡頭畸變校正。朝天空或地平線的偵測仍保留框，但不產生目標 GPS。
可用啟動參數覆寫以上設定，重新啟動程式生效。

從專案根目錄啟動：

```bash
cd /home/jetson/Desktop/uav_project2
python3 -m rtsp_yolo_direct_with_gcp_stun
```

新版預設網頁為 `http://<Jetson-IP>:8082/`，來源 TURN 版仍是 8081。
模型預設使用專案根目錄的 `test2.engine`，不需再複製模型。
兩版各有自己的 `.turn.env`，已保留權限 `600` 並由各自 `.gitignore` 排除。

需要強制 TURN 比對時：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun --ice-transport-policy relay
```

`relay` 模式在兩端僅使用 TURN，沒有 relay 候選就失敗並重試。
此模式不加入 STUN server，避免 aioice 0.10.2 在 relay 策略下仍產生 srflx 候選。

可覆寫 STUN 與 TURN：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun \
  --stun-url 'stun:104.155.197.179:3478' \
  --turn-url 'turn:104.155.197.179:3478?transport=tcp'
```

STUN URL 優先序為 `--stun-url`、環境變數 `STUN_URL`、`.turn.env` 的 `STUN_URL`、內建預設。
TURN URL 優先序為 `--turn-url`、環境變數 `TURN_URL`、`.turn.env`；帳密也允許環境變數覆寫。
TURN 設定仍為必要條件，確保啟動時保留備援。直連候選已取得時，不要求 TURN allocation 成功。
每次啟動使用一個 TURN URL，UDP 失敗不會自動改用 TURN TCP。
`--transport tcp` 控制相機 RTSP，與 TURN 傳輸設定不同。

網頁會顯示實際「直連」或「TURN 中繼」及候選類型。`/api/health` 提供：

- `settings.stun_url`、`settings.turn_url`、`settings.ice_transport_policy`。
- `peers[].ice_pair.path`：`direct` 或 `turn`。
- `peers[].ice_pair.uses_turn`：任一端為 relay 即為 `true`。
- `peers[].ice_pair.local_type`／`remote_type`：host、srflx、prflx 或 relay。
- `relay_verified` 僅代表雙端皆為 relay；直連時為 `false` 是正常行為。

公網網頁與訊號入口仍沿用原本部署。既有 GCP Nginx 指向 Jetson 8081，
若要透過同一個公網網址使用新版，先停止占用 8081 與相機／GPS 的舊程序，再啟動：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun --port 8081
```

本次沒有修改 GCP Nginx、WireGuard 或 coturn。不同 port 讓兩版網頁不衝突，
實際串流建議輪流啟動，避免同時讀同一 GPS 串口或爭用相機、GPU。

本機回歸測試：

```bash
python3 -m unittest rtsp_yolo_direct_with_gcp_stun.test_turn rtsp_yolo_direct_with_gcp_stun.test_metadata -v
python3 -m unittest diagnostics.test_direct_gps_projection -v
node rtsp_yolo_direct_with_gcp_stun/test_browser.cjs
python3 -m unittest rtsp_yolo_direct_with_gcp.test_turn rtsp_yolo_direct_with_gcp.test_metadata -v
node rtsp_yolo_direct_with_gcp/test_browser.cjs
```

不占用相機／GPS／模型的實際網路診斷：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun.check_ice
python3 -m rtsp_yolo_direct_with_gcp_stun.check_turn --both --webrtc
```

`check_ice` 檢查 STUN binding、預設 policy 的合成 H.264 直連、僅在 SDP 提供 relay
候選時的 TURN 備援，以及雙端強制 TURN。診斷兩端都在本 Jetson，跨網路觀看端的
NAT 穿透仍需開啟真實瀏覽器確認。

來源版本的完整媒體流程與部署歷史保留在 `BASELINE_README.md`、`BASELINE_STATUS.md`
和 `BASELINE_NEXT_STEP.md`。複製的 `jetson_setup/` 也沿用既有 8081 部署設定，
這次不需重新執行安裝。ICE API 定義參考 [W3C WebRTC](https://w3c.github.io/webrtc-pc/#rtcicetransportpolicy-enum)。
