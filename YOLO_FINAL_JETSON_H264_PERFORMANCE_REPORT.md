# YOLO Final Jetson H.264 整合與效能比較

日期：2026-08-05  
平台：NVIDIA Jetson Orin NX、Jetson Linux R36.5.0、aarch64  
Jetson power mode：15W，mode ID 2；4 個 CPU core online、2 個 off  
Python：專案 `.venv`，aiortc 1.15.0、PyAV 17.1.0  
輸入：DFK AFU130-L53（序號 26410280）、YUYV 1920×1080 @ 30 FPS

## 結論

已新增 `yolo_final_jetson_h264.py`。它保留 `yolo_final_hw.py` 的完整 final
功能，包括：

- Jetson VIC YUY2 → BGRx 相機轉換
- `11s_car_544_960.engine` TensorRT YOLO
- temporal confirmation
- GPS reader、目標 GPS 投影與標註
- 相機控制、截圖、runtime camera source 與 shutdown 行為

WebRTC 輸出改為 Jetson `nvv4l2h264enc`、固定 3 Mbps H.264 constrained
baseline，encoded appsink 使用 `drop=false`，避免在 RTP 前丟失 H.264
參考幀。

實際工業相機、完整 final processor 與本機 WebRTC client 的 30 秒穩態結果：

- server CPU：226.05% → 157.93%，降低 30.1%，約省下 0.68 個 CPU core。
- client 接收：28.73 → 30.03 FPS，提升 4.5%。
- P95 幀間隔：48.15 → 42.84 ms，改善 11.0%。
- 兩版 RTP packets lost 都是 0。
- 整機 4-core CPU：301.47% → 248.33%，降低 17.6%。
- VDD_IN：9.415 → 9.366 W，差約 -0.05 W，屬接近相同功耗。

final 版的總 CPU 降幅小於 minimal 版，因 final 還有較重的 YOLO 模型、GPS
計算、temporal confirmation 與標註。這些非 encoder 工作不會因 NVENC 而
消失；但硬編碼仍讓 final 串流從未滿 30 FPS 回到穩定 30 FPS。

## 新增檔案與架構

新增檔案：`yolo_final_jetson_h264.py`

它重用：

- `yolo_final.py`：final processor、Web UI、GPS、YOLO、控制 API
- `yolo_final_hw.py`：`FinalHardwareCameraManager`／Jetson VIC capture
- `webrtc_yolo_minimal_jetson_h264.py`：已實測的 Jetson H.264 encoder adapter

完整資料路徑：

```text
DFK camera YUY2
  → nvvidconv compute-hw=2 (Jetson VIC)
  → BGRx → BGR
  → 11s_car_544_960.engine TensorRT YOLO
  → temporal confirmation + GPS projection + annotation
  → PyAV BGR VideoFrame
  → BGRx appsrc
  → nvvidconv → NVMM NV12
  → nvv4l2h264enc (3 Mbps CBR)
  → H.264 Annex-B access units
  → aiortc STAP-A / FU-A RTP packetization
  → WebRTC client
```

queue 策略：

```text
相機 appsink：max-buffers=1 drop=true
encoder 前 raw queue：max-size-buffers=1 leaky=downstream
encoder 後 H.264 appsink：max-buffers=1 drop=false sync=false
```

相機端與 encoder 前可以丟棄尚未形成 H.264 參考關係的 raw frame，以限制
延遲；encoder 後不再丟棄已完成的 H.264 access unit。

## Codec 協商

aiortc 會在 `setRemoteDescription()` 時固定 common codec list。因此新版本會
先建立 send-only video transceiver、限制 H.264 constrained baseline，再
套用 client offer，最後用 `replaceTrack()` 接上 final `CameraVideoTrack`。

實際測試的 answer 只包含：

```text
H264/90000
profile-level-id=42e01f
packetization-mode=1
```

server log 同時確認：

```text
NvMMLiteOpen
===== NvVideo: NVENC =====
NvMMLiteBlockCreate
```

所以 H.264 版本沒有悄悄退回 VP8 或 software H.264。

## 測試方法

比較檔案：

```bash
python yolo_final_hw.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0

python yolo_final_jetson_h264.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --h264-bitrate 3000000
```

每組流程：

1. 啟動實際 DFK 工業相機與完整 final processor。
2. 本機 aiortc receive-only client 完成 SDP、ICE、DTLS、RTP 與解碼。
3. 連線後暖機 10 秒。
4. 量測 30 秒；server PID 的 CPU／RSS 每秒取樣。
5. `tegrastats` 每秒記錄整機 CPU、RAM、GR3D、溫度與 power rails。
6. 取得 client 收幀時間、RTP packet loss 與實際 codec。

CPU 100% 代表一個 CPU core，因此 process CPU 可以高於 100%。兩組使用同一
相機、解析度、場景、YOLO engine、Jetson power mode 與 client 架構。

## 完整串流結果

| 指標 | `yolo_final_hw.py` | `yolo_final_jetson_h264.py` | 差異 |
|---|---:|---:|---:|
| 實際 codec | VP8/90000 | H264/90000 | — |
| 收到影格／30 秒 | 862 | 901 | +39 |
| client FPS | 28.73 | 30.03 | +4.5% |
| 平均幀間隔 | 34.82 ms | 33.33 ms | -1.49 ms |
| P50 幀間隔 | 33.62 ms | 33.69 ms | +0.07 ms |
| P95 幀間隔 | 48.15 ms | 42.84 ms | -11.0% |
| 最大幀間隔 | 79.66 ms | 53.82 ms | -32.4% |
| RTP packets lost | 0 | 0 | 相同 |
| **server CPU 平均** | **226.05%** | **157.93%** | **-30.1%** |
| server CPU P95 | 236.70% | 169.70% | -28.3% |
| server RSS | 1461.14 MiB | 1456.13 MiB | -5.01 MiB |
| 同機 client CPU | 27.64% | 33.23% | +20.2% |
| 同機 client RSS | 89.36 MiB | 83.74 MiB | -5.62 MiB |

H.264 client CPU 較高約 5.59 個百分點，這是同一台 Jetson 上的 client 解碼
差異，不屬於 server CPU。即使把同機 client 成本計入整機，總 CPU 仍顯著
下降。正式部署若 client 在另一台電腦，Jetson server 不會承擔這段 client
decode CPU。

原 VP8 版只有 28.73 FPS，顯示完整 final workload 加上軟編碼已接近／超過
此 15W mode 的即時處理預算；NVENC 版回到 30.03 FPS，且 P95、最大幀間隔
都改善。

## `tegrastats` 整機結果

下表採各測試穩態區間最後 30 筆、每秒一筆的數據。整機統計包含同機 client
與背景程序，server PID CPU 是判斷 server 改善的主要數字。

| 指標 | VP8 軟編碼 | Jetson H.264 | 差異 |
|---|---:|---:|---:|
| 4 個 online core 合計 CPU | 301.47% | 248.33% | -17.6% |
| online core 平均使用率 | 75.37% | 62.08% | -13.29 百分點 |
| 系統 RAM | 2392.93 MiB | 2354.47 MiB | -38.46 MiB |
| GR3D 平均 | 52.43% | 63.20% | +10.77 百分點 |
| VDD_IN 平均 | 9.415 W | 9.366 W | -0.049 W（-0.5%） |
| VDD_CPU_GPU_CV 平均 | 3.025 W | 2.797 W | -0.228 W（-7.5%） |
| VDD_SOC 平均 | 2.221 W | 2.363 W | +0.142 W（+6.4%） |
| TJ 平均 | 51.75°C | 53.32°C | +1.57°C |
| CPU 平均溫度 | 51.30°C | 52.78°C | +1.48°C |
| GPU 平均溫度 | 49.39°C | 50.95°C | +1.56°C |

CPU/GPU/CV rail 下降而 SOC rail 上升，方向符合把軟體編碼移到 Jetson
multimedia/NVMM 路徑；兩者抵銷後 VDD_IN 只差約 0.05 W，應視為同一功耗
量級。

不能將第二組溫度高約 1.5°C 直接歸因於 NVENC：H.264 測試緊接 VP8 測試，
未冷機重置，散熱器已有熱累積。GR3D 平均較高也不能視為 NVENC GPU 使用率，
因 NVENC 不是 GR3D CUDA workload；YOLO burst、場景與 1 Hz sampling phase
都會影響 GR3D 平均。熱穩態與 GPU 比較需交錯順序，各跑至少 10～15 分鐘。

## Bitrate、畫質與網路取捨

| 項目 | final VP8 軟編碼 | final Jetson H.264 |
|---|---:|---:|
| 初始目標 bitrate | 500 kbps | 3 Mbps |
| 調整範圍 | 250 kbps～1.5 Mbps | CLI 允許 0.5～20 Mbps |
| 串流期間 | 依 REMB 動態調整 | 同一解析度期間固定 |
| 本次設定 | aiortc 預設 | 3 Mbps CBR |

Jetson H.264 3 Mbps 的優點：

- 1080p30 快速移動、相機晃動、車輛細節與 YOLO/GPS 文字通常較清楚。
- NVENC 降低 CPU，final pipeline 能恢復 30 FPS。
- 固定 bitrate 讓畫質較可預期。

缺點：

- 所需網路頻寬高於原 VP8 的 1.5 Mbps 上限。
- 目前無法在 PLAYING 狀態不中斷套用 REMB；鏈路不足時不會自動降碼率。
- 網路若無法穩定提供 3 Mbps，可能增加排隊、延遲或 RTP packet loss。

`drop=false` 不會提高 encoder 設定的 3 Mbps，只會確保已完成的 access unit
不在 RTP 前被 appsink 丟棄。aiortc client 本次沒有回報 `bytesReceived`，所以
本報告記錄的是設定 bitrate，而不是假裝 RTP packet 數可直接換算成 Mbps。

## `drop=false` 的優缺點

優點：

- 保護 H.264 參考鏈，避免丟失 P-frame 後短暫破圖。
- 原 minimal H.264 版本的使用者實測在改成 `drop=false` 後未再觀察到破圖。
- final 本次維持 30.03 FPS、零 RTP packet loss。

缺點：

- RTP sender 若長時間跟不上，會產生 backpressure。
- 極端負載可能增加等待；目前 buffer 上限為 1，不會無限制累積延遲。
- 單 viewer 30 秒不能涵蓋多 viewer、弱網路與長時間阻塞。

正確策略是保留 encoder 前的 leaky raw queue，讓超載時丟 raw frame，而不是
丟掉已形成參考鏈的 encoded H.264 access unit。

## 驗證項目

- 新舊 final 檔案 `py_compile` 通過。
- 新檔 CLI `--help` 通過。
- `FinalHardwareCameraManager` 替換成功。
- final camera/control/capture/startup/shutdown 路由存在。
- H.264 transceiver timing regression test 通過；answer 不含 VP8。
- 實機建立 NVENC channel。
- 實際 DFK 相機、final TensorRT engine、GPS reader、WebRTC client完成
  10 秒暖機加 30 秒量測。
- 兩版 RTP packets lost 都為 0。

## 限制與下一步

1. client 在同一台 Jetson；應使用另一台實體電腦分離 client decode CPU。
2. 測試啟動 GPS reader 與 GPS 計算路徑，但本次沒有驗證真實飛行 GPS 資料與
   姿態輸入精度。
3. 尚未量測 glass-to-glass latency、網卡實際 Mbps 或 PSNR／SSIM。
4. 應以相同動態場景測 2、3、4 Mbps，決定正式部署畫質／頻寬平衡點。
5. 應執行至少 10～15 分鐘 soak test，包含快速移動、斷線重連與瀏覽器背景化。
6. 多 viewer 仍各自建立 NVENC instance；需測 1、2、4 viewer 的 session、
   NVMM、功耗與延遲。
7. adapter 使用 aiortc 1.15.0 的內部 encoder factory 和 H.264 packetizer；
   升級 aiortc 後必須重跑 SDP、PLI、RTP 與瀏覽器互通測試。

## 執行方式

```bash
source .venv/bin/activate
python yolo_final_jetson_h264.py \
  --camera-backend gstreamer \
  --gstreamer-device /dev/video0 \
  --h264-bitrate 3000000
```

若 Jetson element 或 NVENC 無法啟動，程式會直接報錯，不會退回 VP8 或軟體
H.264。
