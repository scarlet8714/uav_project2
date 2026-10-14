# STUN 直連與 TURN 備援版本現況

## 2026-10-12 固定斜拍目標 GPS 投影

與 `rtsp_yolo_direct` 同步更新 GPS 投影：預設 AGL 110 m、pitch -50°、
相機方向偏移 0°、HFOV 49.4°、VFOV 29.7°，畫面上方為正前方；
0° 為水平，-90° 為垂直向下。新增 `--camera-pitch-deg`，重啟程式生效。

以未校正的針孔視線與平坦地面求交點；畫面中心約在前方 92.3 m，
上／下緣約 156.2／51.6 m。仍用 GPS COG 近似機頭方向、roll 為零，
未接入即時飛控／雲台姿態。無地面交點時保留框，但不輸出目標座標。
相關離線測試位於 `diagnostics/test_direct_gps_projection.py`。
57 項離線回歸測試通過，包括新投影、GPS 歷史配對、後端狀態、
WebSocket 重接及 STUN／TURN 設定；尚未進行此次角度的實機定位驗證。
本次的 GPS／inference 改動已與直傳版同步，因此不再與原強制 TURN
來源版本逐位元相同；以下 10/9 的比對結果為當時紀錄。

更新：2026-10-09，Asia/Taipei。來源為 `rtsp_yolo_direct_with_gcp`。

新版已完成複製與調整，預設 STUN `stun:104.155.197.179:3478`、ICE policy `all`、
網頁 port 8082；TURN 帳密保留。可用 `--ice-transport-policy relay` 強制雙端 TURN。
網頁與 health 可判別直連／TURN，包括只有一端使用 relay 的路徑。

來源資料夾共 25 個檔案（排除 Python cache）逐一 SHA-256 比對一致，未被修改。
新版的 `source.py`、`inference.py`、`gps.py`、`codec.py`、`byte_tracking.py`
與來源逐位元相同。兩份 `.turn.env` 內容相同，新版權限 600，git ignore 驗證成功。

回歸測試全部通過：

| 版本 | Python | 前端 |
| --- | ---: | ---: |
| 原強制 TURN 版 | 15 | 26 |
| STUN／TURN 新版 | 23 | 31 |

新版 Python 模組編譯、兩版 `--help` 也通過。

實際 GCP STUN／TURN 網路測試全部通過，兩個測試端均在本 Jetson：

| 檢查 | 結果 |
| --- | --- |
| 指定 STUN binding | 取得 host 與 srflx 候選、公網映射 |
| `all` policy 合成 H.264 直連 | host／host，收到 5 幀 160×120 影像 |
| `all` policy TURN 備援 | 在 SDP 隱藏直連候選，relay／relay，收到 5 幀 |
| 強制 TURN | relay／relay，收到 5 幀 |

備援測試保留發送端 `all` 策略及全部已收集候選，只在診斷的 SDP 隱藏直連候選；
接收端設為 `relay`。單端設 `relay` 仍可能透過 peer-reflexive 找到直連，
因此測試不能僅憑單端策略就宣稱實際走 TURN，結果皆檢查 nominated pair。

完整應用流程也通過：用本機 GStreamer RTSP 測試來源，經原程式 H.264 封包直傳、
Jetson 硬體解碼、既有 `test2.engine` 的 TensorRT 推論及 WebSocket metadata。
這些測試使用 `--no-gps`，沒有占用或設定 GPS 串口。

| 情境 | 影像路徑 | 接收影像 | Metadata | 程序退出 |
| --- | --- | --- | --- | --- |
| 原版 8081 | TURN relay／relay | 5 幀 640×360 | origin＋detection | 0 |
| 新版 8082、`all` | 直連 host／host | 5 幀 640×360 | origin＋detection | 0 |
| 新版 8082、`relay` | TURN relay／relay | 5 幀 640×360 | origin＋detection | 0 |

紀錄：[results.jsonl](../diagnostics/gcp_stun_synthetic_runtime_20261009/results.jsonl)，
同目錄保留三次標準輸出與事件 log。

真實相機 `rtsp://192.168.144.135/live` 本次沒有送出封包；兩版的 HTTP 與背景工作
均可啟動，但等候 60 秒仍無相機／YOLO資料，測試程序均正常退出。
紀錄：[真實來源檢查](../diagnostics/gcp_stun_runtime_20261009/results.jsonl)。
不能把合成來源結果當成此次真實相機或跨網路瀏覽器播放的證據。
跨網路 NAT 穿透與真實 GPS 有效 fix 仍需相機／GPS就緒後實測。

既有 GCP Nginx 仍指向 Jetson 8081。新版要用同一公網網址，先停止舊版再加 `--port 8081`。
未修改 WireGuard、GCP Nginx、coturn 或其他版本；所有本次測試程序均已停止。
操作方式見 [README.md](README.md) 及 [NEXT_STEP.md](NEXT_STEP.md)。
