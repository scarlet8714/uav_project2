# Jetson H.264 WebRTC 整合與效能檢測報告

日期：2026-08-05  
平台：NVIDIA Jetson Orin NX、Jetson Linux R36.5.0、aarch64  
Python 環境：專案 `.venv`，aiortc 1.15.0、PyAV 17.1.0  
測試解析度／幀率：1920×1080、30 FPS  
目標 bitrate：3,000,000 bit/s

## 結論

已新增 `webrtc_yolo_minimal_jetson_h264.py`。它保留
`webrtc_yolo_minimal_hw.py` 的 Jetson VIC 相機轉換和 YOLO 路徑，並把
WebRTC 的 aiortc 軟體編碼路徑替換為 Jetson `nvv4l2h264enc`。

實機確認結果：

- `nvv4l2h264enc` 確實建立 NVENC channel，沒有退回軟體 encoder。
- SDP answer 只包含 `H264/90000`，profile-level-id 固定為 `42e01f`
  （constrained baseline），不會協商成 VP8。
- 本機 aiortc client 完成 ICE、DTLS、RTP、H.264 解碼並連續收到 90 幀。
- 校正 track 起始時鐘後，完整本機 WebRTC 測得 30.00 FPS；幀間隔 P50
  33.34 ms、P95 36.41 ms。
- 在固定 30 FPS 節奏的 encoder-only 比較中，Jetson adapter 平均每幀
  process CPU time 為 9.91 ms，aiortc/libx264 為 90.42 ms，降低約 89.0%。
- 硬體版正常穩態已達 1080p30；第一幀仍有 NVENC 初始化成本。
- 使用實際 DFK 工業相機、TensorRT YOLO 與本機 WebRTC client 的完整測試
  中，server process CPU 由 204.58% 降至 120.58%，降低 41.1%，約省下
  0.84 個 CPU core。這組數據已使用 encoded appsink `drop=false`。

## 兩個版本的實際差異

| 項目 | `webrtc_yolo_minimal_hw.py` | `webrtc_yolo_minimal_jetson_h264.py` |
|---|---|---|
| 相機 YUY2 → BGRx | Jetson VIC／`nvvidconv` | 相同 |
| YOLO 輸入與標註 | BGR、TensorRT YOLO | 相同 |
| WebRTC codec 協商 | 未強制；瀏覽器通常優先 VP8 | 強制 H.264 constrained baseline |
| 正式測試 encoder | aiortc/PyAV `libvpx` VP8 | Jetson `nvv4l2h264enc` H.264 |
| RTP H.264 packetization | aiortc | 沿用 aiortc H.264 packetizer |
| PLI／強制 keyframe | libx264 I-frame | `force-IDR` action |
| SPS/PPS | libx264 | 每個 IDR 插入 SPS/PPS |
| 多 viewer | 每 peer 一個軟體 encoder | 每 peer 一個 NVENC instance |
| bitrate | aiortc 可動態調整 libx264 | 啟動時固定；CLI 可設定 |

新版本的完整資料路徑為：

```text
camera YUY2
  → nvvidconv (VIC)
  → BGRx/BGR
  → YOLO + overlay
  → PyAV BGR frame
  → BGRx appsrc
  → nvvidconv → NVMM NV12
  → nvv4l2h264enc
  → Annex-B H.264 access unit
  → aiortc H.264 RTP packetization
  → WebRTC browser/client
```

## 實作重點

### 硬體 encoder adapter

新版本在 aiortc 建立 H.264 encoder 時回傳 `JetsonH264Encoder`。GStreamer
pipeline 使用：

```text
appsrc (BGRx, host memory)
→ nvvidconv
→ video/x-raw(memory:NVMM),format=NV12
→ nvv4l2h264enc
→ video/x-h264,stream-format=byte-stream,alignment=au
→ appsink
```

輸出的 Annex-B NAL units 交給 aiortc 1.15.0 的 H.264 packetizer，沿用其
STAP-A／FU-A 分包與 90 kHz RTP timestamp 行為。

### 一幀 pipeline latency

若每次 `encode()` 都等同一幀從 appsink 回來，會把 nvvidconv 與 NVENC
序列化，初版只得到約 24～27 FPS。最終版本允許一幀在硬體 pipeline 中
處理：送入目前影格後，非阻塞取出先前已完成的 access unit。aiortc 原生
允許 encoder 暫時回傳空 payload，因此不需要修改 RTP sender loop。

### Jetson `force-IDR` 限制

實測在 Jetson Linux R36.5.0 上，若尚未送入第一個 buffer 就呼叫
`nvv4l2h264enc` 的 `force-IDR` action，process 會 segmentation fault。最終
版本在新 encoder 的第一幀依賴其自然產生的 IDR，只在至少成功輸出一幀後
回應 WebRTC PLI。修正後包含中途強制 IDR 的多幀測試可正常完成。

### Bitrate 行為

R36.5.0 的 `nvv4l2h264enc bitrate` property 只允許在 NULL／READY 狀態
修改。早期版本依 REMB 重建 pipeline，實測會造成約 200 ms 初始化停頓和
新的 IDR，並把 90 幀 WebRTC 測試降至 27.41 FPS。因此最終版本在同一解析
度生命週期內固定使用 `--h264-bitrate`；若解析度改變而必須重建，才會套用
最近收到的 bitrate estimate。

## 效能測試

### 1. 固定 30 FPS encoder 呼叫成本

方法：建立相同的 1920×1080 合成 BGR frames，以 30 FPS 節奏送入 encoder；
兩者 bitrate 都設定為 3 Mbps，共 120 幀，排除前 10 幀。硬體版測量的是
`VideoFrame → BGRx → appsrc → 已完成 AU 的 RTP packetization` 呼叫成本；
軟體版使用 aiortc 1.15.0 原生 `H264Encoder`／libx264。`process_time` 會累計
libx264 多執行緒的 CPU time，所以可能大於單幀 wall time。

| 指標 | Jetson `nvv4l2h264enc` | aiortc/libx264 | 差異 |
|---|---:|---:|---:|
| 平均 encode call wall time | 8.19 ms | 31.46 ms | -74.0% |
| P50 encode call wall time | 8.41 ms | 29.94 ms | -71.9% |
| P95 encode call wall time | 9.59 ms | 41.84 ms | -77.1% |
| 平均 process CPU time／幀 | 9.91 ms | 90.42 ms | -89.0% |
| 第一個 call | 66.87 ms | 37.58 ms | HW 多 29.29 ms |
| warm-up 後 RTP payload bytes | 971,742 | 753,572 | 不作畫質結論 |

硬體版 120 次呼叫中有 7 次暫時沒有完成的 access unit，主要出現在 pipeline
warm-up／排程時；aiortc 會繼續取下一幀，完整 WebRTC 測試仍持續收到 30 FPS。
合成畫面的碼流大小不能當作畫質或實拍 bitrate 比較，因兩個 encoder 的 rate
control、QP 和實際畫面複雜度並未做到主觀品質對齊。

### 2. 完整本機 WebRTC 收流

方法：Jetson 上同時執行 server 與 aiortc client，使用 1920×1080 合成相機
frames，完成 SDP、ICE、DTLS、RTP、H.264 編碼與解碼。重置
`CameraVideoTrack.started_at` 後才開始計時，避免 ICE gathering 期間累積的
追趕 burst；接收 90 幀，排除前 15 幀。

| 指標 | Jetson H.264 最終版 | aiortc/libx264 對照 |
|---|---:|---:|
| 協商 codec | H264/90000 | H264/90000（測試時強制） |
| 接收 FPS | 30.00 | 30.02 |
| 平均幀間隔 | 33.33 ms | 33.31 ms |
| P50 幀間隔 | 33.34 ms | 未另記錄 |
| P95 幀間隔 | 36.41 ms | 45.80 ms |

這是同機 client 測試，包含 Jetson 上的 client H.264 軟體解碼成本；不可視為
純 server 功耗或 LAN glass-to-glass latency。不過它已驗證新增 adapter 並非
只產生裸 H.264，而是真的能經 aiortc RTP 被另一個 WebRTC peer 解碼。

### 3. 純 GStreamer hardware pipeline

使用 `videotestsrc` 將 90 幀 1080p30 BGRx 經 `nvvidconv → NVMM NV12 →
nvv4l2h264enc → fakesink`，pipeline 從 PLAYING 到 EOS 為 1.108 秒，約
81.2 FPS。這代表 NVENC pipeline 本身有高於 30 FPS 的吞吐餘裕，但它允許
多幀同時在 pipeline 中，不應直接拿來當 WebRTC 單幀延遲。

### 4. 實際工業相機 + YOLO + WebRTC 完整測試

這組測試直接執行使用者實際會啟動的兩個程式，不再使用合成 frames：

```bash
python webrtc_yolo_minimal_hw.py \
  --camera-source v4l2 --v4l2-device /dev/video0

python webrtc_yolo_minimal_jetson_h264.py \
  --camera-source v4l2 --v4l2-device /dev/video0 \
  --h264-bitrate 3000000
```

共同條件：

- 相機：DFK AFU130-L53，序號 26410280
- 輸入：`/dev/video0`、YUYV 1920×1080 @ 30 FPS
- 模型：`yolo11s.engine`，TensorRT
- Jetson power mode：15W，mode ID 2；4 個 CPU core online、2 個 off
- client：同一台 Jetson 上的 aiortc receive-only peer
- 每組先連線暖機 10 秒，再量測 30 秒
- server CPU／RSS：每秒以獨立 server PID 的 `psutil`／`/proc` 統計
- 整機 CPU、RAM、GPU、溫度及 rails：`tegrastats` 每秒統計
- CPU 100% 代表一個 CPU core，process CPU 可以超過 100%
- Jetson H.264 encoded appsink：`max-buffers=1 drop=false sync=false`
- Jetson H.264 bitrate：固定 3 Mbps CBR

軟體版維持原程式的預設協商順序，實際選擇 VP8；硬體版的 SDP answer 只
保留 H264/90000 constrained baseline。這是兩個檔案「照正式啟動方式」的
比較，不是相同 codec 的 encoder-only 比較；相同 H.264 輸入的純 encoder
差異請看前面的固定 30 FPS 測試。

#### 完整串流結果

| 指標 | `minimal_hw` 軟編碼 | Jetson H.264 | 差異 |
|---|---:|---:|---:|
| 實際 codec | VP8/90000 | H264/90000 | — |
| 收到的影格／30 秒 | 949 | 901 | — |
| client 接收 FPS | 31.63 | 30.03 | 都在 30 FPS 附近 |
| 平均幀間隔 | 31.66 ms | 33.33 ms | +1.67 ms |
| P50 幀間隔 | 30.98 ms | 33.57 ms | +2.59 ms |
| P95 幀間隔 | 41.82 ms | 43.48 ms | +1.66 ms |
| RTP packets lost | 0 | 0 | 相同 |
| **server process CPU** | **204.58%** | **120.58%** | **-41.1%** |
| server CPU P95 | 208.90% | 122.90% | -41.2% |
| server RSS | 1539.28 MiB | 1477.76 MiB | -61.52 MiB |
| 同機 client CPU | 33.15% | 33.87% | +2.2% |

軟體版 31.63 FPS 略高於相機的 30 FPS，不代表相機輸出超過 30 FPS。原因是
原始 `CameraVideoTrack` 在 ICE／DTLS 建連期間已開始計算 `started_at`，連線
後會短暫追趕其排程。硬體版 30.03 FPS、零 packet loss，已實際維持 1080p30。

最重要的完整應用結果是：相機、VIC、YOLO、畫框和 WebRTC 全部開啟時，
Jetson H.264 仍讓 server 從約 2.05 個 CPU core 降到約 1.21 個 core，省下
約 0.84 個 core。總程式 CPU 降幅為 41.1%，不是 encoder-only 的 89.0%。

#### `tegrastats` 整機結果

以下為各次測試穩態區間最後 30 筆、每秒一筆的統計。整機數字包含同機
client 解碼及背景程序，因此 server PID CPU 是判斷 server 改善的主要指標。

| 指標 | 軟編碼 | Jetson H.264 | 差異 |
|---|---:|---:|---:|
| 4 個 online core 合計 CPU | 285.30% | 209.57% | -26.5% |
| online core 平均使用率 | 71.33% | 52.39% | -18.94 百分點 |
| 系統 RAM | 2454.37 MiB | 2353.90 MiB | -100.47 MiB |
| GR3D 平均 | 43.67% | 41.93% | -1.74 百分點 |
| VDD_IN 平均 | 8.578 W | 8.248 W | -0.331 W（-3.9%） |
| VDD_CPU_GPU_CV 平均 | 2.490 W | 2.105 W | -0.385 W（-15.5%） |
| VDD_SOC 平均 | 2.073 W | 2.182 W | +0.109 W（+5.2%） |
| TJ 平均 | 51.06°C | 50.63°C | -0.43°C |
| CPU 平均溫度 | 50.40°C | 49.70°C | -0.70°C |
| GPU 平均溫度 | 48.41°C | 47.93°C | -0.48°C |

CPU rail 功耗下降、SOC rail 略增，符合把 CPU 軟編碼移到 Jetson multimedia
硬體路徑後的方向；VDD_IN 淨下降約 0.33 W。GPU 使用率大致相同，因兩版
都執行相同 TensorRT YOLO，且 NVENC 不是 GR3D CUDA workload。

這輪 H.264 的三個溫度平均低 0.43～0.70°C，但 30 秒不足以消除散熱器熱慣性，
不能據此宣稱長時間一定更冷。若要比較熱穩態，應交錯測試順序並各跑至少
10～15 分鐘。

#### `drop=false` 重測與取捨

原硬體版的 encoded appsink 使用 `max-buffers=1 drop=true`。實際使用時觀察
到極少數短暫破圖，原因很可能是 appsink 偶爾丟掉已編碼的參考 P-frame；
這種遺失發生在 RTP 之前，所以 client 的 `packetsLost` 仍可能是 0。

目前改成：

```text
raw frame（encoder 前）：queue max-size-buffers=1 leaky=downstream
encoded H.264（encoder 後）：appsink max-buffers=1 drop=false sync=false
```

負載過高時仍可在 encoder 前丟棄尚未形成參考關係的 raw frame，但不再丟棄
已編碼 H.264 access unit。使用者初步實測後未再觀察到破圖。

| 指標 | 上一輪 `drop=true` | 本輪 `drop=false` | 差異 |
|---|---:|---:|---:|
| server CPU | 121.24% | 120.58% | -0.66 百分點 |
| client FPS | 29.83 | 30.03 | +0.20 FPS |
| P95 幀間隔 | 43.47 ms | 43.48 ms | +0.01 ms |
| VDD_IN | 8.320 W | 8.248 W | -0.072 W |
| RTP packets lost | 0 | 0 | 相同 |
| 使用者觀察的偶發破圖 | 有 | 初步未再出現 | 改善 |

這是不同時間的兩次 30 秒測試，約 1% 內的差異應視為量測波動。至少目前沒有
證據顯示 `drop=false` 明顯增加 CPU、延遲或功耗。

`drop=false` 的優點：

- 保護 H.264 參考鏈完整，避免 server 在 RTP 前丟掉 P-frame。
- 不需靠縮短 IDR interval 掩蓋問題，畫面穩定性較好。
- 本次重測維持 30 FPS，沒有量到明顯 CPU 代價。

`drop=false` 的缺點：

- 若 RTP sender 長時間跟不上，backpressure 會往 encoder 前傳遞。
- 極端負載下可能增加等待時間；目前 queue 很小，因此不會無限制累積延遲。
- 30 秒單 viewer 測試不能代表多 viewer 或長時間網路阻塞，仍需 soak test。

#### Bitrate、畫質與頻寬取捨

兩個正式啟動版本的 bitrate 行為不同：

| 項目 | 原版 VP8 軟編碼 | Jetson H.264 |
|---|---:|---:|
| 初始目標 bitrate | 500 kbps | 3 Mbps |
| 允許範圍 | 250 kbps～1.5 Mbps | 本程式允許 0.5～20 Mbps |
| 串流期間調整 | 依 WebRTC REMB 動態調整 | 同一解析度期間固定 |
| 本次設定 | aiortc 預設 | 3 Mbps CBR |

3 Mbps H.264 的優點是 1080p30 快速移動、相機晃動、細節與 YOLO 文字通常能
保留得更好；NVENC 也讓提高 bitrate 不需要回到高 CPU 軟編碼。缺點是所需
網路頻寬高於原 VP8 的上限，而且目前不會依 REMB 即時降碼率；若實際鏈路
不足 3 Mbps，可能造成排隊、延遲或真正的 RTP packet loss。

`drop=false` 不會改變 encoder 的 3 Mbps 目標，只是不再刻意丟棄已完成的
access unit，因此實際送出資料會更完整。這次 aiortc client stats 沒有提供
`bytesReceived`，所以報告只記錄設定 bitrate，不能把 RTP packet 數量誤當成
實測 Mbps。若要比較 2、3、4 Mbps 的畫質，應同步記錄網卡 bytes、PSNR／
SSIM 或相同場景的截圖，不能只憑本次 CPU 表格決定。

#### 測試時發現並修正的 codec 協商問題

第一次完整 H.264 測試的 answer 仍以 VP8 為第一個 payload，server log 也
沒有建立 NVENC。原因是 aiortc 在 `setRemoteDescription()` 時就固定 common
codec list；原實作在此呼叫之後才設定 H.264 preference，時機太晚。

最終版已改為：先建立 send-only video transceiver、限制為 H.264 constrained
baseline，再套用 remote offer，最後以 `replaceTrack()` 接上 YOLO track。
修正後的實際 answer 只有：

```text
m=video ... 101
a=rtpmap:101 H264/90000
a=fmtp:101 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f
```

server log 同時確認 `NvMMLiteOpen`、`NVENC` 和 `NvMMLiteBlockCreate`。上述
表格只採用修正後重新執行的結果；錯誤協商成 VP8 的那輪沒有當作硬編碼數據。

## 已執行的正確性檢查

- `py_compile`：原 HW 檔與新 Jetson H.264 檔通過。
- CLI `--help`：通過；新增 `--h264-bitrate`。
- GStreamer element：`appsrc`、`nvvidconv`、`nvv4l2h264enc`、`appsink`
  均存在。
- 實機單幀：成功建立 NVENC，輸出 8 個 RTP payload、共 8,238 bytes，
  RTP timestamp 3,000。
- 多幀與 PLI：第 60 幀觸發 `force-IDR`，沒有 crash。
- SDP：修正 preference 設定時機後，實際相機測試的 answer 只宣告
  `H264/90000`。
- WebRTC：本機 client 成功解碼並接收 90 幀。
- 完整應用：實際 DFK 相機、TensorRT YOLO、VIC、NVENC、本機 WebRTC client
  暖機 10 秒並量測 30 秒，成功且零 packet loss。
- Python whitespace／patch：`git diff --check` 通過。

## 限制與下一步

1. encoder-only 比較使用合成 frames；完整應用比較已使用工業相機與 YOLO，
   但 client 仍在同一台 Jetson，不是實體遠端瀏覽器。
2. 每個 viewer 仍各自建立一個 NVENC instance；應測試 1、2、4 viewers，
   確認 Jetson encoder session、NVMM、功耗與溫度上限。
3. 現在仍有 host BGR/BGRx copy；更進一步的方向是讓 YOLO overlay 後的
   buffer 更直接進入 NVMM，或改成共享 encoder／SFU。
4. 硬體版同一解析度期間固定 bitrate，尚未實作不中斷的 REMB 動態調碼率。
5. adapter 使用 aiortc 1.15.0 的內部 H.264 packetizer／encoder factory；
   `requirements.txt` 已固定該版本。升級 aiortc 時必須重跑 SDP、PLI、RTP
   packetization 與瀏覽器互通測試。
6. 下一輪應用另一台實體電腦作 client，記錄 codec `getStats()`、server-only
   CPU、RAM、NVENC/VIC 使用率、功耗、溫度、丟幀和 glass-to-glass latency。

## 執行方式

```bash
source .venv/bin/activate
python webrtc_yolo_minimal_jetson_h264.py \
  --camera-source v4l2 \
  --v4l2-device /dev/video0 \
  --h264-bitrate 3000000
```

啟動時若缺少任一 Jetson element 或 NVENC 無法進入 PLAYING，程式會直接報錯，
不會退回 VP8 或 libx264。
