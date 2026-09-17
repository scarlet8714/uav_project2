# RTSP 中斷／卡頓診斷

診斷時間：2026-09-17 09:52–09:57（Asia/Taipei）  
來源：`rtsp://192.168.144.135/live`  
平台：Jetson Orin NX，15W power mode

## 結論

固定週期的中斷來源是攝影機的 RTSP/RTP server，不是 Orin NX 的效能或硬體瓶頸。

攝影機約每 49.4–50.6 秒主動送出 RTCP `BYE`，隨後關閉 RTSP TCP 連線。`rtsp_minimal.py` 收到 EOS 後等待 1 秒再重連，所以畫面會約每 50 秒凍結約 1–1.5 秒。這個結果在完全不使用 NVDEC、NVENC、NumPy 和 WebRTC 的純壓縮 H.264 接收測試中也可重現。

信心：高。協定層 log 明確記錄 `received BYE`，緊接著是 `server closed connection`；此時資料在 BYE 前仍持續到達，並非 Orin 處理不及。

## 證據

### 完整應用管線（120 秒）

- `rtsp_minimal.py` 在約第 50 秒和第 101 秒兩度出現 `RTSP pipeline reached end of stream`。
- RTSP 解碼輸入平均 28.99 fps；兩次中斷造成平均值低於正常 30 fps。
- WebRTC 收端未出現大於 100 ms 的 RTP/解碼輸出間隔，但這不代表來源沒停：`RtspVideoTrack.recv()` 在來源不更新時會持續送出最後一張影格，所以凍結被「重複舊影格」掩蓋。
- WebRTC 最大影格間隔 45.5 ms，p99 41.1 ms。

### 純攝影機壓縮流（排除 Orin 編解碼）

- 管線只有 `rtspsrc ! rtph264depay ! appsink`，沒有解碼或重編碼。
- 預定測試 70 秒，實際 48.99 秒就收到 EOS。
- 收到 1471 個 H.264 access unit，平均 30.02/s。
- 第二次協定除錯測試在約 49.44 秒收到來源 SSRC 的 RTCP BYE，接著攝影機關閉 TCP socket。
- 攝影機 SDP 自報為舊版 `Ambarella streaming 2012.03.12`；RTSP server 的 Date 也停在 2021，建議優先檢查攝影機韌體與 RTSP session 設定。

### Orin 資源

- `rtsp_minimal.py` 平均 CPU：67.95%（約 0.68 個核心）；短暫峰值 159.7%（約 1.6 個核心）。
- Orin NX 有 6 核，此次 15W 模式中 4 核 online，仍未接近 CPU 飽和。
- 程式最大 RSS：301 MB。
- 系統 RAM 最大使用：1433/7607 MB；swap 維持 0。
- 最高溫度：54.4°C，沒有熱節流跡象。
- 最高輸入功耗：6.63 W，顯著低於 15W 模式上限。
- GR3D 0% 是正常現象：NVDEC/NVENC 是獨立硬體引擎，不用 3D GPU。

## 次要卡頓特徵

未中斷時來源 PTS 穩定約每 33.3 ms（30 fps），但 TCP 到達時間偶有約 100–128 ms 間隔，之後多張影格快速到達。這是攝影機輸出／TCP 聚合造成的 burst pattern，不像 Orin 運算延遲。100 ms jitter buffer 可接近其上限，網路稍有抖動時可能造成額外短卡。

## 建議處理順序

1. 更新或重啟攝影機韌體，檢查是否有 50 秒 RTSP session、preview/recording duration、client timeout 或 watchdog 設定。
2. 用 VLC 或另一台電腦連同一 URL 超過 60 秒；預期同樣會在約 50 秒停止。若成立，可直接交由攝影機廠商依 RTCP BYE 證據處理。
3. 測試攝影機的其他 RTSP path／substream；若只有 `/live` 發生，改用不會自動結束的 continuous-live endpoint。
4. 若攝影機韌體無法修正，可保留目前自動重連，但把 1 秒固定等待縮短，並在來源失聯時顯示 stale 狀態，而不是持續重送舊影格。
5. 對 100–128 ms 的短抖動，可把 `--rtsp-latency` 從 100 調到 200–300 ms 做 A/B 測試；這只改善短抖動，無法修復伺服器主動 BYE。

## Log 索引

- `20260917_095221/summary.json`：完整管線摘要
- `20260917_095221/events.jsonl`：0.25 秒採樣與 EOS/stall 時間軸
- `20260917_095221/rtsp_minimal.log`：應用與 NVDEC/NVENC 訊息
- `20260917_095221/tegrastats.log`：Orin 資源、溫度和功耗
- `20260917_095541/summary.json`：70 秒純壓縮流測試（在約 49 秒提早 EOS）
- `rtsp_protocol_debug.log`：GStreamer RTSP/RTCP 協定層原始 log

可用下列指令重跑完整診斷：

```bash
./.venv/bin/python -u rtsp_diagnostic.py --camera-seconds 30 --e2e-seconds 120
```
