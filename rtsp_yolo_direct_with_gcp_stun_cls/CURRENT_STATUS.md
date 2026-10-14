# GCP STUN 連線與分類功能整合

2026-10-13 新建 `rtsp_yolo_direct_with_gcp_stun_cls`。
以 `rtsp_yolo_direct_with_gcp_stun` 的連線／部署工具為基礎，
加入 `rtsp_yolo_direct_cls` 的偵測、追蹤、分類、GPS／Canvas 功能。

- 連線：GCP STUN、TURN 備援、ICE policy `all`，預設 port 8082。
- 模型：專案根目錄 `test3.engine` 與 `classifier_fp16.engine`。
- 分類：0 cm34、1 light_tactical、2 medium_tactical；最近 7 次等權重投票。
- 追蹤：預設 legacy，ByteTrack 可選；漏檢 ID 內部保留 0.5 秒，不顯示預測框。
- GPS：歷史資料配對、固定 pitch -50°／高度 110 m 地面投影。
- 顯示：來源 PTS 對齊、實際框到期清除、類別與座標文字。
- 診斷：ICE 路徑資訊保留，新增 CLS 狀態和分類設定。
- 前端版本：`20261013.stun_cls.1`。
- 事件目錄：`diagnostics/gcp_stun_cls_<時間>/events.jsonl`。

兩個來源資料夾未修改；TURN 設定來自 STUN 版，副本權限 600。
本次未啟停串流服務，也未改 GCP Nginx、WireGuard、coturn。

驗證結果：

- 78 項 Python 回歸測試通過，包括分類／追蹤／GPS、metadata、ICE、健康狀態。
- 34 項前端測試通過，包括實際框到期清除、預測框隱藏、STUN／TURN 與重連。
- 全部 Python 檔語法編譯通過；主程式、check_ice、check_turn、check_classifier 的 CLI help 通過。
- 比對 STUN 版後端所有連線函式與前端連線／重連區段，確認內容相同。
- turn.py、source.py、codec.py、gps.py 與 TURN 設定和 STUN 版相同。
- 以檔案雜湊確認兩個來源資料夾未被修改。

以上為本機回歸與模擬整合驗證，未執行相機串流或 GPU 分類實測。
測試環境出現既有 torch／torchvision 相容性及 sandbox GPU／EGL 初始化提示，未造成測試失敗。

待實機確認：跨網路瀏覽器連線、相機／GPS／GPU 完整流程與真實影像分類／追蹤品質。
分類前處理與輸出索引的訓練設定核對旗標沿用來源 `preprocessing_verified: false`。

操作見 [README.md](README.md)，部署歷史保留在 `BASELINE_*.md`。
