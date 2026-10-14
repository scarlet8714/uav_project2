# 三類偵測／軍車細分類／GPS + GCP STUN／TURN

2026-10-13 新建，以 `rtsp_yolo_direct_with_gcp_stun` 為連線基礎，加入
`rtsp_yolo_direct_cls` 的偵測、分類、追蹤、GPS 與顯示功能。
兩個來源資料夾保留原樣；新模組獨立啟動，不匯入來源模組的程式。

## 啟動

從專案根目錄執行：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun_cls
```

網頁預設 `http://<Jetson-IP>:8082/`。預設使用專案根目錄的
`test3.engine` 偵測模型及 `classifier_fp16.engine` 分類模型，不複製模型檔。
分類前處理使用本資料夾 [classifier_config.json](classifier_config.json)。

預設追蹤為 `legacy`；要使用最近分類版實機測試的 ByteTrack：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun_cls --tracker bytetrack
```

8082 與來源 STUN 版相同，兩版須輪流啟動，或用 `--port` 指定其他埠。
既有 GCP 網頁入口指向 Jetson 8081 時，以相同埠取代原服務：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun_cls --tracker bytetrack --port 8081
```

可覆寫模型及分類／追蹤設定：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun_cls \
  --model-path test3.engine \
  --classifier-model-path classifier_fp16.engine \
  --classifier-history 7 --track-hold-seconds 0.5
```

`--no-classifier` 關閉細分類，保留三類偵測／追蹤／GPS。
`--no-gps`、`--gps-port`、`--transport tcp`、`--rtsp-timeout`、
`--playout-delay-ms` 及相機投影參數均保留。

## 沿用 STUN 版連線

- STUN 預設 `stun:104.155.197.179:3478`。
- TURN URL 與帳密複製自 STUN 版 `.turn.env`，新副本權限 `600`，由 `.gitignore` 排除。
- ICE policy 預設 `all`，允許 host／srflx／prflx 直連及 TURN relay，實際路徑由 ICE 檢查決定。
- `--ice-transport-policy relay` 強制兩端只使用 TURN；此模式不加入 STUN。
- HTTP／WebRTC offer、單一觀看連線、WebSocket 獨立重連、健康檢查和看門狗沿用 STUN 版。
- H.264 壓縮封包直傳瀏覽器，沒有為網頁重新編碼；pacing buffer 預設 300 ms，RTSP timeout 8 秒。

新觀看連線會取代舊觀看連線，仍只支援一個 viewer。
兩個來源版本的重連程式目前相同，此次整合保留原本 `viewer session no longer exists` 的處理。

覆寫選項 `--turn-config`、`--stun-url`、`--turn-url` 均保留。
URL 優先序為命令列、環境變數、`.turn.env`，STUN 缺省時使用內建 URL。
TURN 設定仍為啟動必要條件；每次啟動使用一個 TURN URL，UDP 失敗不自動切換 TCP。
`--transport tcp` 控制相機 RTSP 傳輸。

網頁與 `/api/health` 顯示 `ice_pair.path`（`direct`／`turn`）、候選類型及 `uses_turn`。
`check_ice`、`check_turn` 與 `jetson_setup/` 工具保留自 STUN 版。
本次未修改 GCP Nginx、WireGuard 或 coturn；部署歷史見 `BASELINE_*.md`。

## 偵測與軍車細分類

`test3.engine` 偵測 `car`、`military_car`、`amphibious_armored_vehicle`。
只有當次實際偵測為 `military_car` 的框裁切並送入原生 TensorRT 分類器：

| 輸出索引 | 顯示類別 |
| --- | --- |
| 0 | `cm34` |
| 1 | `light_tactical` |
| 2 | `medium_tactical` |

分類就緒後顯示五類：`car`、`cm34`、`light_tactical`、`medium_tactical`、
`amphibious_armored_vehicle`。分類 engine 未就緒或載入／執行失敗時，
軍車仍顯示 `military_car`，偵測、追蹤、GPS 和串流持續運作。
每隔約 5 秒的推論更新重試載入，engine 檔案穩定至少 2 秒後才嘗試；
支援 TensorRT 8.6、FP16／FP32、固定／動態 batch。

每個 ID 保留最近 7 次實際分類，以最高分的類別各投一票，採等權重多數決。
不足 7 次使用已有票數，第一次即顯示分類。平票優先沿用目前且並列最高票的類別，
否則使用並列類別中最近出現的一類。切成其他偵測類別時清除細分類累積。
可用 `--classifier-history` 調整窗口，不增加置信度差距或連續次數門檻。

JSON 保留 `detector_label`、`classifier_index`、`classifier_confidence`、
`classifier_probs`、`classification_count`、`classifier_votes`。
confidence／probs 表示投票比例，最新模型輸出另存 `classifier_raw_index`、`classifier_raw_probs`。

前處理沿用分類版：BGR 轉 RGB、直接縮放 224×224、除以 255、ImageNet mean/std。
`preprocessing_verified: false` 仍保留，實際訓練 transforms／類別索引尚待核對。
可透過 `--classifier-config` 指定設定，支援 RGB／BGR、stretch／center_crop、scale、mean/std、logits／probabilities。

## 追蹤、GPS 與顯示

`legacy` 使用運動／尺寸預測供內部配對，預設以來源 PTS 保留漏檢 ID 0.5 秒，
兩次實際配對確認目標。`bytetrack` 保留高／低信心配對與 ID，加入相同時間保留。
漏檢期間保留 ID 與分類紀錄，不輸出預測框、不重新分類或更新 GPS；接回時沿用歷史。
RTSP generation 變動、PTS 倒退／重複或處理影格間隔超過 1 秒時重置追蹤與分類。

Canvas 與影像來源 PTS 配對，只顯示實際偵測框；忽略 `observed: false`，
依 `expiresPts` 到期清框，即使 WebSocket 暫時沒有新資料。
框使用實線，類別／座標文字固定 20 px 粗體、不加黑底，類別顏色沿用分類版。

GPS 保留歷史配對與固定姿態地面投影，預設高度 110 m、pitch -50°、
yaw offset 0°、HFOV 49.4°、VFOV 29.7°。朝天空或地平線的目標保留框但不生成目標 GPS。
姿態與平坦地面模型、GPS COG 近似機頭方向等限制與來源分類版相同。

## 診斷與驗證

前端版本 `20261013.stun_cls.1`；每 5 秒終端狀態保留 ICE 路徑並新增 `CLS`。
事件目錄為 `diagnostics/gcp_stun_cls_<時間>/events.jsonl`。
`/api/health` 的 `yolo.classifier` 提供分類狀態、投票方式、前處理旗標及錯誤，
`settings` 同時保留 STUN／TURN 與模型／分類／追蹤設定。

```bash
python3 -m unittest discover -s rtsp_yolo_direct_with_gcp_stun_cls -t . -v
node rtsp_yolo_direct_with_gcp_stun_cls/test_browser.cjs
python3 -m rtsp_yolo_direct_with_gcp_stun_cls --help
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_ice --help
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_turn --help
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_classifier --help
```

實際 ICE 診斷與 GPU 分類／ONNX 數值比對可分別使用：

```bash
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_ice
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_turn --both --webrtc
python3 -m rtsp_yolo_direct_with_gcp_stun_cls.check_classifier
```

已完成的整合驗證與待實機項目見 [CURRENT_STATUS.md](CURRENT_STATUS.md)。
