# rtsp_yolo_direct 最近一週日誌檢查

檢查時間：2026-10-13 約 06:57（Asia/Taipei）。統計窗口：2026-10-06 06:57:28 至 2026-10-13 06:57:28。

只統計 diagnostics/direct_*/events.jsonl 原版直傳服務；不混入 GCP/STUN/DataChannel 版本。29 份執行紀錄，共 15,353 筆 health_sample，約 4.26 小時的每秒取樣量，並非連續一週監控。health_sample 使用與 /api/health 相同的 health_snapshot 資料來源；本次未取得新的即時 API 快照。兩份末尾 JSON 截斷，忽略無法解析的行。

## 關閉事件

| peer_closing.reason | 次數 |
| --- | ---: |
| ice_closed | 16 |
| superseded_by_new_offer | 10 |
| server_shutdown | 12 |
| source_reconnected_or_stalled | 3 |
| disconnected_timeout | 0 |
| connection_timeout | 0 |
| ice_failed / connection_failed | 0 |

41 次關閉不等於 41 次故障或自動重連。12 次停止服務、10 次新 offer 替換既有連線；後者可能是其他觀看頁面，也可能是同一頁的新請求，無法僅憑這個 reason 判定有兩個人觀看。16 次 ice_closed 中，15 次前一筆 health 的來源 connected 且 YOLO age <3秒；剩下一次 10/9 12:31:15 已先發生來源停流和 rtsp_error。ice_closed 是關閉狀態，不能單憑它判定網路掉線、關頁面或重整。日誌沒有 ICE disconnected/failed 狀態事件。

## 來源停流

- 10/9 10:50:59：source_reconnected_or_stalled；直到 10:53:22 停止服務未見 rtsp_connected。
- 10/9 12:31:15：rtsp_error 後 ice_closed；12:39:04 才重建來源 generation=2，約 7 分 49 秒後恢復。
- 10/9 12:41:03：source_reconnected_or_stalled；直到 12:54:11 停止服務未見恢復。
- 10/9 14:30:19：source_reconnected_or_stalled；直到 14:34:20 停止服務未見恢復。

上述是接收端來源更新停止的證據，不能單憑日誌區分相機本身停止送流、相機網路中斷或接收端問題。217 次 rtsp_error 是錯誤／重試事件，不是 217 次獨立停流；其中 212 次集中在上述 10/9 三份執行紀錄，10/12 啟動期另有 5 次。10/12 15:25 啟動期間有 No route to host。

## 對 5 秒門檻的判斷

沒有 disconnected_timeout，無證據支持 WebRTC disconnected 等待 5 秒為這一週主要重連原因。RTSP timeout 5 秒確實參與來源重建，但上述停流後重試持續數分鐘，並非只看到 5～6 秒後穩定恢復的短暫停頓；無法證明放寬 timeout 能避免那些事件。維持原連線是否本可恢復，需要受控測試，現有重試資料不能回答反事實。

## 證據索引

- 2026-10-06T09:04:40.490+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_090412/events.jsonl:41)。前一筆 health：RTSP connected=True；YOLO age=0.049 秒。
- 2026-10-06T09:04:58.885+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_090412/events.jsonl:67)。前一筆 health：RTSP connected=True；YOLO age=0.055 秒。
- 2026-10-06T09:04:59.046+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_090412/events.jsonl:71)。前一筆 health：RTSP connected=True；YOLO age=0.055 秒。
- 2026-10-06T09:32:39.925+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_093150/events.jsonl:64)。前一筆 health：RTSP connected=True；YOLO age=0.005 秒。
- 2026-10-06T14:41:59.713+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_143758/events.jsonl:252)。前一筆 health：RTSP connected=True；YOLO age=0.019 秒。
- 2026-10-06T14:58:16.317+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145743/events.jsonl:47)。前一筆 health：RTSP connected=True；YOLO age=0.052 秒。
- 2026-10-06T14:58:53.159+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145743/events.jsonl:95)。前一筆 health：RTSP connected=True；YOLO age=0.018 秒。
- 2026-10-06T14:59:49.276+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145940/events.jsonl:17)。前一筆 health：RTSP connected=True；YOLO age=0.027 秒。
- 2026-10-06T15:00:15.451+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145940/events.jsonl:57)。前一筆 health：RTSP connected=True；YOLO age=0.064 秒。
- 2026-10-06T15:00:35.011+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145940/events.jsonl:84)。前一筆 health：RTSP connected=True；YOLO age=0.009 秒。
- 2026-10-06T15:00:53.452+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145940/events.jsonl:114)。前一筆 health：RTSP connected=True；YOLO age=0.002 秒。
- 2026-10-08T16:06:56.177+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261008_160606/events.jsonl:58)。前一筆 health：RTSP connected=True；YOLO age=0.038 秒。
- 2026-10-08T16:07:36.109+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261008_160606/events.jsonl:111)。前一筆 health：RTSP connected=True；YOLO age=0.048 秒。
- 2026-10-08T16:07:53.887+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261008_160606/events.jsonl:134)。前一筆 health：RTSP connected=True；YOLO age=0.015 秒。
- 2026-10-08T16:10:20.615+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261008_160606/events.jsonl:293)。前一筆 health：RTSP connected=True；YOLO age=0.071 秒。
- 2026-10-08T16:10:27.903+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261008_160606/events.jsonl:308)。前一筆 health：RTSP connected=True；YOLO age=0.017 秒。
- 2026-10-09T10:50:59.165+08:00 `source_reconnected_or_stalled`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_102245/events.jsonl:1705)。前一筆 health：RTSP connected=False；YOLO age=10.181 秒。
- 2026-10-09T12:31:15.572+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_115424/events.jsonl:2227)。前一筆 health：RTSP connected=True；YOLO age=4.139 秒。
- 2026-10-09T12:41:03.767+08:00 `source_reconnected_or_stalled`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_115424/events.jsonl:2876)。前一筆 health：RTSP connected=False；YOLO age=5.115 秒。
- 2026-10-09T14:30:19.679+08:00 `source_reconnected_or_stalled`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_134727/events.jsonl:2583)。前一筆 health：RTSP connected=False；YOLO age=10.663 秒。
- 2026-10-09T16:28:32.781+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_160948/events.jsonl:1139)。前一筆 health：RTSP connected=True；YOLO age=0.065 秒。
- 2026-10-09T18:21:43.706+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_180758/events.jsonl:837)。前一筆 health：RTSP connected=True；YOLO age=0.033 秒。
- 2026-10-09T18:30:56.982+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_183048/events.jsonl:16)。前一筆 health：RTSP connected=True；YOLO age=0.064 秒。
- 2026-10-09T18:38:38.064+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_183048/events.jsonl:489)。前一筆 health：RTSP connected=True；YOLO age=0.046 秒。
- 2026-10-09T18:40:22.178+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_184009/events.jsonl:21)。前一筆 health：RTSP connected=True；YOLO age=0.001 秒。
- 2026-10-09T18:42:24.759+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261009_184009/events.jsonl:156)。前一筆 health：RTSP connected=True；YOLO age=0.039 秒。
- 2026-10-12T15:26:27.990+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_152523/events.jsonl:84)。前一筆 health：RTSP connected=True；YOLO age=0.056 秒。
- 2026-10-12T15:26:57.343+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_152523/events.jsonl:127)。前一筆 health：RTSP connected=True；YOLO age=0.009 秒。
- 2026-10-12T15:40:50.894+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_153756/events.jsonl:187)。前一筆 health：RTSP connected=True；YOLO age=0.032 秒。
- 2026-10-12T15:45:19.656+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_154337/events.jsonl:118)。前一筆 health：RTSP connected=True；YOLO age=0.062 秒。
- 2026-10-12T15:49:57.442+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_154542/events.jsonl:268)。前一筆 health：RTSP connected=True；YOLO age=0.049 秒。
- 2026-10-12T15:58:41.290+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_155831/events.jsonl:26)。前一筆 health：RTSP connected=True；YOLO age=0.064 秒。
- 2026-10-12T16:04:24.044+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_155831/events.jsonl:378)。前一筆 health：RTSP connected=True；YOLO age=0.045 秒。
- 2026-10-12T16:48:59.531+08:00 `superseded_by_new_offer`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_164653/events.jsonl:140)。前一筆 health：RTSP connected=True；YOLO age=0.013 秒。
- 2026-10-12T16:51:32.405+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_164653/events.jsonl:306)。前一筆 health：RTSP connected=True；YOLO age=0.038 秒。
- 2026-10-12T16:54:40.780+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_164653/events.jsonl:508)。前一筆 health：RTSP connected=True；YOLO age=0.044 秒。
- 2026-10-12T16:59:26.451+08:00 `ice_closed`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_165648/events.jsonl:173)。前一筆 health：RTSP connected=True；YOLO age=0.051 秒。
- 2026-10-12T21:55:09.867+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_215150/events.jsonl:212)。前一筆 health：RTSP connected=True；YOLO age=0.043 秒。
- 2026-10-12T21:59:46.780+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_215825/events.jsonl:94)。前一筆 health：RTSP connected=True；YOLO age=0.056 秒。
- 2026-10-12T22:11:30.539+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_220828/events.jsonl:195)。前一筆 health：RTSP connected=True；YOLO age=0.048 秒。
- 2026-10-12T22:13:53.236+08:00 `server_shutdown`：[事件](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261012_221152/events.jsonl:134)。前一筆 health：RTSP connected=True；YOLO age=0.074 秒。

## 各次執行取樣量

| 紀錄 | 起始 | 結束 | health 樣本 |
| --- | --- | --- | ---: |
| direct_20261006_090412 | 2026-10-06T09:04:12.134+08:00 | 2026-10-06T09:04:59.475+08:00 | 46 |
| direct_20261006_093150 | 2026-10-06T09:31:50.545+08:00 | 2026-10-06T09:32:50.748+08:00 | 59 |
| direct_20261006_143758 | 2026-10-06T14:37:58.940+08:00 | 2026-10-06T14:42:01.206+08:00 | 239 |
| direct_20261006_145743 | 2026-10-06T14:57:43.079+08:00 | 2026-10-06T14:59:06.825+08:00 | 83 |
| direct_20261006_145940 | 2026-10-06T14:59:40.009+08:00 | 2026-10-06T15:01:21.900+08:00 | 101 |
| direct_20261006_170143 | 2026-10-06T17:01:43.263+08:00 | 2026-10-06T17:17:26.653+08:00 | 941 |
| direct_20261008_160606 | 2026-10-08T16:06:06.574+08:00 | 2026-10-08T16:17:29.391+08:00 | 681 |
| direct_20261009_102245 | 2026-10-09T10:22:45.818+08:00 | 2026-10-09T10:53:22.693+08:00 | 1830 |
| direct_20261009_115424 | 2026-10-09T11:54:24.613+08:00 | 2026-10-09T12:54:11.298+08:00 | 3577 |
| direct_20261009_134727 | 2026-10-09T13:47:27.979+08:00 | 2026-10-09T14:34:20.505+08:00 | 2799 |
| direct_20261009_160948 | 2026-10-09T16:09:48.053+08:00 | 2026-10-09T16:28:36.554+08:00 | 1125 |
| direct_20261009_180758 | 2026-10-09T18:07:58.209+08:00 | 2026-10-09T18:21:43.909+08:00 | 823 |
| direct_20261009_183048 | 2026-10-09T18:30:49.140+08:00 | 2026-10-09T18:38:38.520+08:00 | 467 |
| direct_20261009_184009 | 2026-10-09T18:40:09.465+08:00 | 2026-10-09T18:42:24.921+08:00 | 134 |
| direct_20261012_152523 | 2026-10-12T15:25:23.751+08:00 | 2026-10-12T15:27:39.377+08:00 | 135 |
| direct_20261012_153756 | 2026-10-12T15:37:57.026+08:00 | 2026-10-12T15:40:51.027+08:00 | 173 |
| direct_20261012_154337 | 2026-10-12T15:43:38.123+08:00 | 2026-10-12T15:45:23.862+08:00 | 105 |
| direct_20261012_154542 | 2026-10-12T15:45:42.837+08:00 | 2026-10-12T15:49:57.671+08:00 | 254 |
| direct_20261012_155831 | 2026-10-12T15:58:31.614+08:00 | 2026-10-12T16:04:24.265+08:00 | 351 |
| direct_20261012_163609 | 2026-10-12T16:36:10.091+08:00 | 2026-10-12T16:38:21.920+08:00 | 131 |
| direct_20261012_163844 | 2026-10-12T16:38:44.309+08:00 | 2026-10-12T16:39:17.311+08:00 | 32 |
| direct_20261012_164348 | 2026-10-12T16:43:48.063+08:00 | 2026-10-12T16:44:28.517+08:00 | 39 |
| direct_20261012_164653 | 2026-10-12T16:46:53.431+08:00 | 2026-10-12T16:54:55.747+08:00 | 480 |
| direct_20261012_165648 | 2026-10-12T16:56:49.179+08:00 | 2026-10-12T16:59:29.941+08:00 | 160 |
| direct_20261012_171538 | 2026-10-12T17:15:38.383+08:00 | 2026-10-12T17:15:49.908+08:00 | 9 |
| direct_20261012_215150 | 2026-10-12T21:51:50.699+08:00 | 2026-10-12T21:55:09.931+08:00 | 198 |
| direct_20261012_215825 | 2026-10-12T21:58:26.070+08:00 | 2026-10-12T21:59:46.922+08:00 | 80 |
| direct_20261012_220828 | 2026-10-12T22:08:28.629+08:00 | 2026-10-12T22:11:30.709+08:00 | 181 |
| direct_20261012_221152 | 2026-10-12T22:11:52.866+08:00 | 2026-10-12T22:13:53.508+08:00 | 120 |

## 追加：幾秒停流是否自行恢復

逐秒檢查來源 last_packet_age_s >=1 秒的連續區段，找到五段約 5 秒後來源計數增加的現象。但每段都只多出一個 packet／解碼影格，不是恢復連續送流：10/9 的四段隨即再次停止、進入前述長時間停流；10/6 17:17:26 那段只多一個影格後日誌即截斷，無法確認後續。這些不能算成五次短暫停流後正常恢復。

排除這些長停流前兆與截斷案例，本次取樣未找到「來源停 1～幾秒，之後連續恢復正常影格」的確定案例。每秒取樣及有限覆蓋時間不能排除其他未記錄時段或不足一秒的停頓；接收端的 packet 計数亦不是網卡原始 RTP 封包擷取，不能單靠計数確定相機真正送包時間。
