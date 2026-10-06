# 最近 7 天 `/api/health` 與 Tailscale 紀錄檢查

檢查範圍：2026-09-29T19:20:31+08:00 至 2026-10-06T19:20:31+08:00（台灣時間）。

結論：保存的遠端監測確實有播放期間 direct／DERP 反覆切換，且兩次 ICE 關閉時 RTSP／YOLO 仍正常；另有持續直連的時段。資料不足以算出完整 7 天的切換頻率，也無法判定是基地台壅塞、NAT 或其他 UDP 路徑因素。

## 資料涵蓋

- 共 34 個執行紀錄、12,654 筆逐秒 `health_sample`。各執行取樣首尾區間合計 3.51 小時；不是 7 天連續監測。
- 另讀取兩份遠端 `/api/health`／Tailscale 同步取樣及已保存的 Tailscale journal。這些 health 取樣和執行紀錄有重疊，不重複加入上述樣本總數。
- 9/29 晚間、9/30、10/4 沒有找到範圍內的 health 歷史；這表示缺少紀錄，不能表示當天沒有異常。
- `health_sample` 由與 `/api/health` 相同的 `health_snapshot()` 產生，但只保存 RTSP／YOLO／peer 欄位，不保存 Tailscale 路徑。舊版沒有逐 peer 欄位。
- `/api/health` 的 `healthy` 只依 RTSP connected 與 YOLO 最新更新小於 3 秒判斷；沒有觀眾或 ICE 已關閉時也能是 true。
- 現存 system journal 只讀到 10/6 17:11:20 至 19:20:10；更早只能依已保存的日誌，無完整 7 天 Tailscale history。
- 三個 events 檔案末尾有無法解析的一行，本次只統計成功解析的紀錄。

## 每日已保存的執行紀錄

| 日期 | 執行數 | health 樣本 | ICE 關閉事件 | RTSP error 事件 | YOLO error 事件 |
|---|---:|---:|---:|---:|---:|
| 2026-09-30 | 無紀錄 | — | — | — | — |
| 2026-10-01 | 2 | 1,609 | 3 | 27 | 0 |
| 2026-10-02 | 2 | 1,644 | 0 | 13 | 0 |
| 2026-10-03 | 7 | 2,197 | 3 | 51 | 14,548 |
| 2026-10-04 | 無紀錄 | — | — | — | — |
| 2026-10-05 | 17 | 5,735 | 29 | 37 | 0 |
| 2026-10-06 | 6 | 1,469 | 6 | 0 | 0 |

**事件數不等於網路故障數。** ICE 關閉可能包含瀏覽器關閉、重連、測試結束及網路異常；其中 10/5 10:36:31、10:45:17 是本機五分鐘測試結束附近的事件。RTSP error 包含啟動找不到來源、同一失敗的重試及關閉時錯誤；YOLO error 多次重複同一模型尺寸錯誤。不可把這些數字當作 DERP 次數或獨立故障數。

## 已確認的 direct／DERP 切換

來源：[遠端取樣](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl)；301 筆、每秒取樣，另每 10 秒保存 `tailscale status` 文字。對象為遠端筆電 100.83.253.28。

| 10/5 台灣時間（取樣） | Tailscale 路徑 | 同步證據 |
|---|---|---|
| 11:01:39–11:02:01 | direct | [status 文字第 1 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:1) |
| 11:02:02–11:02:18 | DERP（hkg） | [status 文字第 31 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:31) |
| 11:02:19–11:02:34 | direct | [status 文字第 41 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:41) |
| 11:02:35–11:03:19 | DERP（hkg） | [status 文字第 61 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:61) |
| 11:03:20–11:05:37 | direct | [status 文字第 111 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:111) |
| 11:05:38–11:06:39 | DERP（hkg） | [status 文字第 241 行](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_110139/samples.jsonl:241) |

取樣路徑為 `direct → DERP → direct → DERP → direct → DERP`：這個五分鐘窗口觀察到 5 次路徑狀態改變、3 段 DERP 狀態。切換時刻由每秒端點欄位界定，各段均有 status 文字確認；時間精度約一秒，不能排除取樣間額外變化。11:03:10 起 health 連線被拒絕，後兩次路徑改變不能稱為影片播放中的切換。

前兩段切換與 WebRTC 關閉的對照：

| 時間 | 證據 |
|---|---|
| 11:02:02 | 原 WebRTC peer 仍 connected，Tailscale 直連端點消失；稍後 status 確認 DERP。 |
| 11:02:08.585 | [ICE 關閉](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_110019/events.jsonl:140)。11:02:09 的 health 仍 healthy=true、RTSP connected、reconnects=0、YOLO 更新 age=0.003 秒，但 peers=[]。 |
| 11:02:19 | 恢復 direct；11:02:29.304 新 peer connected。 |
| 11:02:35 | 再次失去直連端點；11:02:39 status 確認 DERP。 |
| 11:03:00.957 | [ICE 再次關閉](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_110019/events.jsonl:202)。11:03:01 health 仍 healthy=true、RTSP connected、reconnects=0、YOLO age=0.016 秒、peers=[]。 |

這是網路路徑波動與 ICE 關閉時間相近的證據，不是單憑 `via=derp` 協商日誌推測。沒有遠端瀏覽器的 WebSocket close code、接收丟包及解碼紀錄，因此不能證明切 DERP 本身造成關閉，更不能確定 NAT／基地台根因。

## 穩定時段與其他異常

- **10/5 11:19:09–11:24:09：**[另一份遠端取樣](/home/jetson/Desktop/uav_project2/diagnostics/remote_probe_20261005_111909/samples.jsonl) 301 筆全數 healthy=true，同一 peer connected，Tailscale 始終保存直連端點；此時是 IPv4 140.123.103.43:41641，而前述不穩定窗口主要是 IPv6 端點。兩段不能視為完全相同網路條件。每秒取樣不能排除瞬間變化，也沒有遠端畫面統計。
- **10/5 17:03:06–17:11:21：**[同一次執行](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_165056/events.jsonl:742) 約 8 分鐘內有 8 次 ice_closed。來源 generation=1、RTSP 重連數維持 0，該執行沒有 rtsp_error、yolo_error，初始恢復後無 input_stall。沒有同時段 Tailscale status，不能把 8 次 ICE 關閉算成 8 次 DERP 切換，也無法排除瀏覽器操作。
- **10/6 17:17:24：**[input_stall](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_170143/events.jsonl:951) 時 RTSP 最新封包 age=3.283 秒、解碼 age=3.271 秒、YOLO age=3.142 秒，來源停止更新。這次有來源端停滯證據，不能把所有卡頓歸因於遠端 DERP；末尾紀錄截斷，無法查看後續恢復。
- **10/3：**14,548 次 yolo_error 都是 `input size [1,3,544,960] not equal to max model size [1,3,960,960]` 的重複錯誤，屬模型輸入尺寸問題。
- 共 41 次 ice_closed；其中 37 次前一筆 health 的來源／YOLO符合 healthy 條件、4 次不符合。這只能定位關閉時後端是否更新，不能證明 41 次皆是網路掉線。

## 可下的判斷

這台設備的保存資料同時呈現：播放期間短時間內多次直連／DERP 切換，以及另一時段持續直連。不能用「同一地區」推論整天都應維持同一路徑。也不能用只有約 3.5 小時、跨測試／正常使用的紀錄，宣稱這是所有 4G 的正常頻率。完整頻率需要持續保存被動 Tailscale 路徑與遠端瀏覽器接收狀態；本次僅分析已有資料，沒有修改程式或服務。

## 34 份執行紀錄

| 紀錄 | 首筆事件 | 末筆事件 | health 樣本 |
|---|---|---|---:|
| [direct_20261001_130226/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261001_130226/events.jsonl) | 10-01 13:02:27 | 10-01 13:05:08 | 159 |
| [direct_20261001_130600/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261001_130600/events.jsonl) | 10-01 13:06:00 | 10-01 13:30:13 | 1450 |
| [direct_20261002_165705/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261002_165705/events.jsonl) | 10-02 16:57:05 | 10-02 17:04:50 | 462 |
| [direct_20261002_172818/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261002_172818/events.jsonl) | 10-02 17:28:19 | 10-02 17:48:02 | 1182 |
| [direct_20261003_101530/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_101530/events.jsonl) | 10-03 10:15:30 | 10-03 10:16:17 | 44 |
| [direct_20261003_102511/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_102511/events.jsonl) | 10-03 10:25:11 | 10-03 10:31:52 | 392 |
| [direct_20261003_103855/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_103855/events.jsonl) | 10-03 10:38:55 | 10-03 10:40:00 | 63 |
| [direct_20261003_104215/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_104215/events.jsonl) | 10-03 10:42:15 | 10-03 10:44:20 | 124 |
| [direct_20261003_104511/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_104511/events.jsonl) | 10-03 10:45:11 | 10-03 10:59:02 | 830 |
| [direct_20261003_110331/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_110331/events.jsonl) | 10-03 11:03:31 | 10-03 11:09:18 | 338 |
| [direct_20261003_111413/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261003_111413/events.jsonl) | 10-03 11:14:13 | 10-03 11:21:00 | 406 |
| [direct_20261005_094209/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_094209/events.jsonl) | 10-05 09:42:09 | 10-05 09:46:10 | 240 |
| [direct_20261005_094625/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_094625/events.jsonl) | 10-05 09:46:25 | 10-05 09:47:49 | 82 |
| [direct_20261005_095940/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_095940/events.jsonl) | 10-05 09:59:40 | 10-05 10:03:28 | 226 |
| [direct_20261005_100338/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_100338/events.jsonl) | 10-05 10:03:38 | 10-05 10:09:32 | 353 |
| [direct_20261005_101719/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_101719/events.jsonl) | 10-05 10:17:19 | 10-05 10:19:42 | 141 |
| [direct_20261005_102047/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_102047/events.jsonl) | 10-05 10:20:47 | 10-05 10:22:35 | 107 |
| [direct_20261005_104802/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_104802/events.jsonl) | 10-05 10:48:02 | 10-05 10:51:34 | 210 |
| [direct_20261005_105529/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_105529/events.jsonl) | 10-05 10:55:29 | 10-05 10:58:17 | 166 |
| [direct_20261005_110019/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_110019/events.jsonl) | 10-05 11:00:19 | 10-05 11:03:09 | 169 |
| [direct_20261005_110941/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_110941/events.jsonl) | 10-05 11:09:41 | 10-05 11:26:13 | 981 |
| [direct_20261005_112621/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_112621/events.jsonl) | 10-05 11:26:21 | 10-05 11:29:44 | 202 |
| [direct_20261005_113007/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_113007/events.jsonl) | 10-05 11:30:07 | 10-05 11:32:05 | 116 |
| [direct_20261005_162151/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_162151/events.jsonl) | 10-05 16:21:51 | 10-05 16:27:07 | 314 |
| [direct_20261005_165026/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_165026/events.jsonl) | 10-05 16:50:26 | 10-05 16:50:34 | 6 |
| [direct_20261005_165056/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261005_165056/events.jsonl) | 10-05 16:50:56 | 10-05 17:20:04 | 1746 |
| [direct_20261006_090412/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_090412/events.jsonl) | 10-06 09:04:12 | 10-06 09:04:59 | 46 |
| [direct_20261006_093150/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_093150/events.jsonl) | 10-06 09:31:50 | 10-06 09:32:50 | 59 |
| [direct_20261006_143758/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_143758/events.jsonl) | 10-06 14:37:58 | 10-06 14:42:01 | 239 |
| [direct_20261006_145743/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145743/events.jsonl) | 10-06 14:57:43 | 10-06 14:59:06 | 83 |
| [direct_20261006_145940/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_145940/events.jsonl) | 10-06 14:59:40 | 10-06 15:01:21 | 101 |
| [direct_20261006_170143/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_20261006_170143/events.jsonl) | 10-06 17:01:43 | 10-06 17:17:26 | 941 |
| [direct_sync_20261005_103047/direct_20261005_103051/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_sync_20261005_103047/direct_20261005_103051/events.jsonl) | 10-05 10:30:51 | 10-05 10:36:31 | 338 |
| [direct_sync_20261005_103934/direct_20261005_103938/events.jsonl](/home/jetson/Desktop/uav_project2/diagnostics/direct_sync_20261005_103934/direct_20261005_103938/events.jsonl) | 10-05 10:39:38 | 10-05 10:45:17 | 338 |

無法解析的末尾行：`diagnostics/direct_20261001_130600/events.jsonl:1506`、`diagnostics/direct_20261003_111413/events.jsonl:438`、`diagnostics/direct_20261006_170143/events.jsonl:955`。
