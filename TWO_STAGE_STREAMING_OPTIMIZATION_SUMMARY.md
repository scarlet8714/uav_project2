# 影像串流兩階段效能優化總結

本文件整理以下三份實測報告的主要結論：

- `MJPEG_WEBRTC_PERFORMANCE_REPORT.md`
- `INDUSTRIAL_CAMERA_STREAMING_PERFORMANCE_REPORT.md`
- `YOLO_FINAL_INDUSTRIAL_CAMERA_PERFORMANCE_REPORT.md`

## 階段一：MJPEG → WebRTC

以 1920×1080 @ 30 FPS webcam 測試為例：

| 指標 | MJPEG | WebRTC |
|---|---:|---:|
| Client 收到 FPS | 13.74 | 38.14* |
| 網路流量 | 38.55 Mb/s | 1.14 Mb/s |
| Server CPU | 64.6% | 203.9% |
| Server RSS | 1254.6 MiB | 1451.2 MiB |

\* WebRTC FPS 包含啟動排程追趕與重複最新 YOLO frame，不代表真正有 38.14 FPS 的新推論結果。

### 結論

- WebRTC 將網路流量降低約 **97%**，更適合 Wi-Fi、遠端監看及多 viewer。
- 代價是 aiortc/PyAV 軟體視訊編碼使 CPU 和記憶體用量增加。
- MJPEG 架構簡單，但 1080p 頻寬很高，而且目前每個 client 可能各自執行取像、YOLO 和 JPEG 編碼。
- 兩者真正的新 YOLO 結果率仍由相機、YOLO 和影像處理速度決定，不能只看 WebRTC client 顯示 FPS。

因此第一階段的主要成果是：

> 使用較高的 CPU 成本，換取大幅降低的網路流量與較完整的即時串流能力。

## 階段二：CPU 色彩轉換 → Jetson VIC

工業相機輸入為 1920×1080 @ 30 FPS、未壓縮 YUYV。一般版本使用 CPU `videoconvert`，HW 版本使用 Jetson VIC：

```text
YUY2/YUYV → nvvidconv compute-hw=2 → BGRx
```

### Minimal 實測

| 指標 | WebRTC 軟體轉換 | WebRTC VIC |
|---|---:|---:|
| Server CPU 平均 | 254.94% | 207.28% |
| Server CPU P95 | 297.9% | 262.9% |
| Client 幀間隔 P95* | 57.27 ms | 43.76 ms |

VIC 使平均 CPU 降低約 **18.7%**。

### Final 實測

Final 版本另包含 temporal confirmation、GPS unavailable 處理與完整標註：

| 指標 | `yolo_final.py` | `yolo_final_hw.py` |
|---|---:|---:|
| Server CPU 平均 | 253.56% | 230.75% |
| Server CPU P95 | 298.4% | 287.0% |
| Client 幀間隔 P95* | 57.66 ms | 45.87 ms |
| Server RSS | 1409.62 MiB | 1482.64 MiB |

VIC 使平均 CPU 降低約 **9.0%**，client 幀間隔 P95 改善約 **20.4%**，但 RSS 多約 73 MiB。

\* 幀間隔仍受 WebRTC 追趕與重複 frame 影響，不等於 unique YOLO frame latency。

### 結論

- VIC 已確認真正運作，能降低工業相機 YUYV 色彩轉換的 CPU 負擔。
- CPU 不會降到很低，因為 YOLO 前後處理、標註、buffer copy 和 WebRTC 軟體編碼仍存在。
- 本輪功耗沒有證明 VIC 節能；測試順序與溫度未完全固定，需交錯重測才能比較。
- 目前正式版本建議使用 `yolo_final_hw.py`。

因此第二階段的主要成果是：

> 將輸入端最主要的色彩轉換交給 Jetson VIC，使完整 final pipeline 的 CPU 約降低 9%，並改善幀間隔尾端表現。

## 整體架構與下一步

目前的硬體／軟體分工為：

```text
工業相機 YUYV
→ Jetson VIC 色彩轉換                 硬體
→ YOLO TensorRT inference             GPU
→ 後處理、GPS、確認、標註與 frame copy CPU
→ aiortc/PyAV WebRTC 視訊編碼         CPU 軟體
→ 瀏覽器
```

兩階段完成後，輸入端色彩轉換及 YOLO inference 已硬體加速；目前較大的剩餘 CPU 成本在輸出端軟體視訊編碼和影像複製。

下一個優先方向是：

1. 使用 Jetson 硬體 H.264 encoder 取代 aiortc/PyAV 的軟體編碼部分。
2. 修正 WebRTC 約 10 秒首幀等待及啟動 burst catch-up。
3. 加入 capture `frame_id` 與各階段 timestamp，正確量測 unique YOLO FPS。
4. 減少 BGRx→BGR、latest frame 和 VideoFrame 的重複 copy。

最終簡化結論：

> 第一階段 WebRTC 解決頻寬問題；第二階段 VIC 降低輸入端 CPU。下一階段應處理輸出端軟體編碼，才有機會進一步大幅降低 CPU。
