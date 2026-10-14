# RTSP 直傳 + 三類偵測 + 軍車細分類 + GPS

此模組完整複製自目前工作目錄的 `rtsp_yolo_direct`，原版未修改。
保留單一 RTSP 來源、H.264 封包直傳 WebRTC、Jetson NVDEC／YOLO、
GPS 歷史配對與固定姿態地面投影、來源 PTS 對齊、STUN／TURN、
單一觀看連線、影片與 WebSocket 獨立重連、看門狗、健康狀態及事件記錄。

## 啟動

從專案根目錄執行：

```bash
python3 -m rtsp_yolo_direct_cls
```

停止伺服器（從專案根目錄執行）：

```bash
python3 stop_rtsp_yolo_direct_cls.py
```

程式會辨識以 `python3 -m rtsp_yolo_direct_cls` 啟動的所有伺服器，
送出 SIGTERM 並等待最多 15 秒正常關閉。可用 `--timeout 30` 調整等待時間；
加上 `--force` 可在逾時後送出 SIGKILL 強制停止。

預設偵測模型為根目錄 `test3.engine`，分類模型為根目錄
`classifier_fp16.engine`。預設 8080 埠與原版相同，請只啟動一版；
若需同時比較，可用 `--port 8082`。觀看網址為 `http://<jetson-ip>:8080/`。

```bash
python3 -m rtsp_yolo_direct_cls \
  --model-path test3.engine \
  --classifier-model-path classifier_fp16.engine \
  --track-hold-seconds 0.5 --classifier-history 7
```

`--no-gps`、`--gps-port`、`--transport tcp`、`--playout-delay-ms`、
`--rtsp-timeout`、`--camera-pitch-deg`、`--altitude-agl-m`、
`--turn-config`、`--stun-url`、`--turn-url`、`--ice-transport-policy relay`
等原版參數仍可使用。`.turn.env` 已完整複製且保留 600 權限，並排除版本控制。
不開分類時可加 `--no-classifier`。

分類 engine 尚未完成、檔案剛寫入，或載入／執行失敗時，偵測、追蹤、
GPS 和串流持續運作，軍車顯示 `military_car`。每隔約 5 秒的推論更新
重試載入；engine 寫入穩定至少 2 秒後才嘗試，不需要重新啟動。
建議轉換時先輸出暫存檔，完成後再移到最終路徑。

## 偵測與分類

`test3.engine` 的類別為 `car`、`military_car`、`amphibious_armored_vehicle`。
只有當次實際偵測為 `military_car` 的框會裁切並送入細分類；
`car` 與兩棲車直接顯示三類偵測結果。分類輸出順序依使用者指定：

| 分類輸出索引 | 顯示名稱 | 說明 |
| --- | --- | --- |
| 0 | `cm34` | CM34 |
| 1 | `light_tactical` | 輕型戰術車 |
| 2 | `medium_tactical` | 中型戰術車 |

因此接入分類後的五類顯示為 `car`、`cm34`、`light_tactical`、
`medium_tactical`、`amphibious_armored_vehicle`。分類器就緒前軍車
仍顯示三類模型的 `military_car`，不將其冒充任何細分類結果。

每個 ID 預設保留最近 7 次實際分類，每次以模型最高分的類別投一票，
每票權重相同，顯示最多票的類別。票數相同時優先沿用目前顯示類別，
但它必須也是最多票之一；否則選並列類別中最近出現的那一類。
不足 7 次時用已有的結果，第一次就給分類，沒有「不確定」類別。
後續其他類別占多數時仍會更新，不加分數差距或額外連續次數門檻。
這只作用在軍車細分類，不覆蓋偵測模型的 car／兩棲車。
切成其他偵測類別時清除該 ID 的細分類累積；漏檢時暫存分類紀錄，
不顯示補框、不重新分類，重新配對成功後繼續更新。
分類欄位保留在 JSON：`detector_label`、`classifier_index`、
`classifier_confidence`、`classifier_probs`、`classification_count`。
其中 confidence／probs 現在表示選中類別的投票比例／各類投票比例，
不是模型的單次機率。`classifier_votes` 為票數，`classifier_raw_index` 與
`classifier_raw_probs` 保留最新一次模型原始分類與機率，供診斷使用。

## 分類前處理與 TensorRT

設定在 [classifier_config.json](classifier_config.json)，可用
`--classifier-config /path/to/config.json` 指定其他檔案。
輸出索引由使用者暫定，仍需與另一台訓練電腦的 `class_to_idx` 對照。
目前前處理使用 **BGR 轉 RGB、直接縮放 224×224、除以 255、
ImageNet mean/std**；這是待核對的初始設定，不是從 ONNX 推得的訓練設定。
`preprocessing_verified: false` 會反映在健康狀態；核對完成後可改為 `true`。

支援 `color_order` RGB／BGR、`resize_mode` stretch／center_crop、
`resize_shorter`、`scale`、`mean`、`std` 及 logits／probabilities 輸出。
中心裁切模式先依短邊縮放，再裁出 `input_size`。

原 `classifier.onnx` 是非 Ultralytics 的一般分類器，輸入
`images: [batch, 3, 224, 224]`，輸出 `logits: [batch, 3]`。
本版用原生 TensorRT execution context 執行，不交給 YOLO 載入。
支援 TensorRT 8.6 的 FP16／FP32 線性 CUDA 輸入輸出、固定或動態 batch；
固定 batch 大於 1 時以同一裁切補齊並取第一筆輸出。
engine 必須在相容的 Jetson／TensorRT 平台上轉換，且仍保留三個輸出分數。

可以請訓練電腦的 Codex 協助：

> 請找出 classifier 訓練及 ONNX 匯出程式，列出 class_to_idx、驗證／推論的
> 影像 transforms（色彩順序、resize/crop、scale、mean/std），以及 ONNX
> 輸入輸出 shape 和是否輸出 logits。確認輸出順序是否為
> 0=cm34、1=light_tactical、2=medium_tactical。

## 追蹤與漏檢

預設維持 `--tracker legacy` 的中心配對架構，增加來源 PTS 的時間保留，
利用最後幾次實際偵測的位置／尺寸變化推估速度。配對參考預測中心距離、
框重疊與尺寸相容性，同一影格一對一配對；類別不參與 ID 配對。
累計兩次實際配對確認目標，預測不增加確認次數。

目標短暫漏檢時，內部保留 ID 與分類紀錄最多 0.5 秒，
位置／尺寸預測只供重新配對使用，**不輸出、不顯示預測框**。
每次追蹤更新只回傳當次配對到的實際偵測框，均使用實線；
漏檢時不在舊位置補畫，因此不會因殘留的預測軌跡再疊一個框。
重新配對成功沿用 ID，超時移除。前端也會忽略 `observed: false` 的舊版資料。
前端依最後實際偵測的 `expiresPts` 清框，即使 WebSocket
暫時沒有新結果，也不會額外顯示一秒。GPS 只以實際偵測框更新。
新欄位為 `observed`、`lastObservedPts`、`expiresPts`、`missingSeconds`。
RTSP generation 改變、PTS 倒退／重複或處理影格間隔超過 1 秒，會重置追蹤與分類歷史。
沒有外觀重識別或相機運動補償，交錯／快速轉向仍需實際影片測試。

可選 `--tracker bytetrack`，保留 ByteTrack 的高／低信心配對及 ID，
外層加入相同的內部時間保留，也只回傳實際配對的偵測框。
`--bytetrack-buffer` 為最低內部保留更新數，
會依觀察到的來源時間間隔提高以涵蓋保留期限；顯示期限仍以秒數為準。

## 診斷與驗證

頁面版本 `20261013.cls.4`。`/api/health` 的 `yolo.classifier` 包含
載入狀態、類別順序、前處理核對旗標、執行耗時與錯誤，
`aggregation: majority_vote` 表示使用等權重多數決；
`settings` 記錄模型、保留時間與分類設定。終端每 5 秒顯示 `CLS` 狀態，
事件紀錄在 `diagnostics/direct_cls_<時間>/events.jsonl`。

```bash
python3 -m unittest discover -s rtsp_yolo_direct_cls -t . -v
node rtsp_yolo_direct_cls/test_browser.cjs
python3 -m rtsp_yolo_direct_cls.check_turn --help
python3 -m rtsp_yolo_direct_cls.check_classifier
```

測試包含原版 WebSocket／ICE／看門狗／GPS 功能回歸，以及漏檢恢復、
來源時間超時、軍車分類觸發、歷史更新、engine 延後載入與前端清框。
分類邏輯使用模擬分數驗證，不能代替 engine 完成後的實機推論與準確度測試。

`check_classifier` 只使用 GPU 分類 engine 和 ONNX 官方參考執行器，
不開相機、GPS 或伺服器。列出實際 tensor shape／dtype，並比較三組合成影像
的分類與機率；可加 `--probability-tolerance 0.01` 做嚴格數值比對。
目前 engine 已完成並能執行，輸入為 FP32 `[1,3,224,224]`，輸出為 FP32 `[1,3]`，
內部運算精度由 engine 決定。初次比對三組最高分類別一致，但機率差最多約
0.0169，因此 0.01 的嚴格門檻未通過；官方參考執行器亦確認該差異。
這是已記錄的 FP16／FP32 數值差異，不能據此推定真實影像的分類準確率。

原版完整說明保留在 [BASELINE_README.md](BASELINE_README.md)，
原版歷史紀錄保留在 [BASELINE_STATUS.md](BASELINE_STATUS.md)。
其中 `rtsp_yolo_direct` 命令、五類直接偵測、舊追蹤行為與版本號屬來源版紀錄。
