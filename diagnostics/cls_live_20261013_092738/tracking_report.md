# 左下角目標：ByteTrack 與 legacy 同影格對照

資料：cls_live_20261013_092738，30 秒、390 次推論。
ByteTrack 實際運行，YOLO 門檻 0.1，高分／新軌跡門檻 0.3。
保留同一批 YOLO NMS 後候選，再取 >=0.3 的候選回放目前 legacy TargetTracker。
這不是再拍一次影片，兩者看到的是同一批影格／同一批偵測候選。
两者均保留 ID 0.5 秒、只輸出實際匹配框，沒有預測補框。
legacy 回放只比較框與 ID，不重新執行 classifier；其 label 是偵測類別。

| 指標 | legacy 回放 | ByteTrack 實際輸出 |
| --- | ---: | ---: |
| 有框更新 | 314 | 359 |
| 無框更新 | 76 | 31 |
| 有框比例 | 80.51% | 92.05% |
| 出現／消失切換 | 53 | 10 |
| 消失段數 | 27 | 5 |
| 最長消失 | 0.662 秒 | 0.757 秒 |
| ID 變更 | 4 | 2 |

ByteTrack 實際回傳 48 次低於 0.3 的低分配對框。
ByteTrack 有框而 legacy 無框的更新 48 次；
legacy 有高分框而 ByteTrack 無輸出的更新 3 次。
追蹤器可延续既有低分配對，但新軌跡確認、配對失敗、lost 狀態等條件仍會限制輸出。
低門檻候選中目標實際出現 379 次，
完全沒有 >=0.1 候選 11 次。

前次 legacy 30 秒（09:05）373/423 有框，而第一段 ByteTrack 30 秒（09:17）
僅 2/425 有框。這兩段不是同一批影格，不應用來單獨量化追蹤器增益。
補測 5 秒的同影格對照為 legacy 35/68、ByteTrack 38/68；
本報告再以完整 30 秒的原始候選給出較完整的公平對照。
標註畫面見 [overview.jpg](overview.jpg)，圖表見 [tracking_comparison.png](tracking_comparison.png)。
原始資料見 [detections.jsonl](detections.jsonl)、[tracking_comparison.json](tracking_comparison.json)。
正式 cls 的預設模式未修改。
