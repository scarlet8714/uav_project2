# 暫存對話與接續紀錄

更新日期：2026-08-18

## Webcam 與 VIC

- 現有程式可使用一般 USB webcam。
- OpenCV backend 適合 webcam 的 MJPEG 1920×1080 @ 30 FPS。
- GStreamer/VIC 路徑目前固定要求 YUYV；已測 webcam 的 1080p30 只提供
  MJPEG，YUYV @ 30 FPS 最高約 640×480。
- 若要 webcam 1080p30 並使用 VIC，需修改 pipeline：

  ```text
  Webcam MJPEG
  → v4l2src
  → nvjpegdec
  → nvvidconv compute-hw=2（VIC）
  → BGRx/BGR
  → YOLO
  → NVENC H.264
  → WebRTC
  ```

- VIC 不直接解碼 MJPEG，負責色彩轉換與縮放。
- 現有 `--jpeg-decoder` 參數尚未真正接入現行 HW pipeline。

## 目標 GPS 換算

- 使用 YOLO bbox 中心作為目標 pixel。
- Pixel 依 FOV 與固定 AGL 高度投影成畫面右方／上方的地面位移。
- 位移依 GPS COG 加相機 yaw offset 旋轉為 North/East，再換成經緯度。
- Final 目前固定參數：

  ```text
  ALTITUDE_AGL_M = 75.0
  HFOV_DEG = 52.0
  VFOV_DEG = 31.0
  CAMERA_YAW_OFFSET_DEG = 180.0
  ```

- 主要限制：固定高度、無 roll/pitch 補償、無鏡頭畸變校正、bbox 中心
  不一定是接地點，且影像與 GPS 尚未按 measurement time 對齊。

## COG 與移動方向

- 方向直接使用 NMEA RMC `true_course` 或 VTG `true_track`，不是程式以
  前後座標自行計算。
- 速度至少 1 m/s 才接受新 COG；低速時沿用上一個有效 COG。
- COG（Course Over Ground）是地面移動方向；SOG（Speed Over Ground）
  是地面移動速度。兩者是不同欄位，但 RMC／VTG 通常會一起提供。
- COG 是地面移動方向，不是機身 yaw：

  ```text
  機頭朝北、向東側飛：yaw=0°，COG=90°
  機頭朝北、向南倒飛：yaw=0°，COG=180°
  機頭朝北懸停、被風吹向東南：yaw=0°，COG 約 135°
  繞 POI 飛行：機頭朝圓心，COG 沿圓周切線，可能相差約 90°
  ```

- 因此側飛、倒飛、懸停漂移、強側風、原地旋轉或 POI 飛行時，不能把
  COG 當成相機 yaw。
- 原地旋轉時 GPS 無法觀測機頭方向，現有邏輯會沿用旋轉前的 COG。
- 若是持續向前、保持速度且每次只緩慢轉 10～20°，使用 GPS COG 是合理
  的近似。應對方向向量做 circular smoothing，不能直接平均角度，否則
  `359°` 與 `1°` 會錯算成 `180°`：

  ```python
  east = sin(radians(cog_deg))
  north = cos(radians(cog_deg))
  east_f = (1 - alpha) * east_f + alpha * east
  north_f = (1 - alpha) * north_f + alpha * north
  smooth_cog = degrees(atan2(east_f, north_f)) % 360
  ```

- 初始可測試 `alpha=0.5`。現行接受 COG 的門檻為 1 m/s；若低速 COG
  太不穩，可提高至 2 m/s。濾波越強，轉彎時的方向延遲也越大。
- SAM-M8Q 的 RMC／VTG COG 通常比用相鄰 GPS 座標差分自行算方向可靠；
  座標差分在低速時容易被數公尺的位置雜訊淹沒。

### M490TOP／ArduPilot 自動航線假設

- 使用者的飛行器是亞拓 M490TOP，App 推測由 ArduPilot 改版；AUTO 飛行
  時不會手動操作 yaw。
- 尚未找到亞拓公開文件能確認改版韌體的確切預設值。若保留 ArduCopter
  行為，關鍵參數是 `WP_YAW_BEHAVIOR`：

  ```text
  0 = 不改變 yaw
  1 = 機頭朝下一個 waypoint
  2 = 機頭朝下一個 waypoint，但 RTL 除外
  3 = 機頭沿 GPS course
  ```

- 對現有演算法而言，值 3 最符合「COG 約等於機頭 yaw」；值 1/2 在直線
  航段通常接近，但轉彎時「朝下一點」不一定等於曲線瞬時切線；值 0 不適合。
- 任務中的 `CONDITION_YAW`、`DO_SET_ROI`／POI 也可能覆蓋一般 yaw 行為。
- ArduPilot 普通 waypoint 間通常使用 S-Curve，不必每個點都停下再轉。
  但 waypoint Delay 非 0、下一命令是 LAND／LOITER／RTL、轉彎半徑太小、
  點距太近或 App 指定逐點 yaw 時，仍可能減速、停下或做明顯逐點旋轉。
- 第一次試飛可用「北向直線→緩右轉→東向直線→緩右轉→南向直線」，
  觀察 App 箭頭與實際航跡。需分別觀察位置是否畫弧、機頭箭頭是否連續
  旋轉、懸停時箭頭是否穩定，以及 RTL 是否改變朝向規則。
- 最可靠的驗證仍是匯出參數搜尋 `WP_YAW_BEHAVIOR`，或比較飛行 log 的
  `ATT/Yaw` 與 GPS course。

## GPS 與相機 timestamp

- NMEA RMC 通常包含 UTC 時間與日期，GGA 通常包含 UTC 時間。
- 現有 `GPSReader` 沒有保存 NMEA UTC，只以 Jetson `time.monotonic()`
  記錄資料接收時間。
- 現有相機路徑沒有將 timestamp 傳到 YOLO/GPS 處理層。
- OpenCV 可在 `read()` 返回後立即記錄 Jetson `monotonic_ns()`；這是
  frame 到達應用程式的近似時間，不是感光瞬間。
- GStreamer/VIC 可保存 `Gst.Buffer.pts`。目前 V4L2 HW pipeline 使用
  `do-timestamp=true`，PTS 主要來自 Jetson/GStreamer clock，尚未證明是
  相機硬體曝光 timestamp。
- `time.monotonic_ns()` 可視為 Jetson 這次開機 session 內持續前進的時間
  軸；不受 NTP、時區或手動校時影響，適合同機資料對齊，但重新開機後會
  建立新時間軸，且本身不能轉成年月日時分秒。
- 影像與 GPS 都應使用同一個 Jetson monotonic clock domain，但保留不同
  的事件欄位，不要只存一個模糊的 timestamp：

  ```text
  Image:
    frame_id
    frame_receive_mono_ns
    gst_pts_ns                  # 若 GStreamer 可取得
    camera_hardware_ts_ns       # 未來若相機支援

  GPS:
    gps_receive_mono_ns
    gps_utc / gps_iTOW          # 模組取得有效時間後仍要保存
    fix / position / speed / COG

  Session:
    session_id
    startup_unix_ns             # 區分不同開機／飛行紀錄
  ```

- OpenCV 應在 `read()` 返回後立刻記 `frame_receive_mono_ns`；GPS 應在收到
  完整 NMEA／UBX 訊息時立刻記 `gps_receive_mono_ns`。不可等 YOLO 推論完成
  後才加時間，否則會混入不固定的推論延遲。
- 兩者都是「資料到達應用程式」的時間，不是相機曝光或 GPS measurement
  的硬體時間；USB/UART、解碼、kernel buffer 會造成不同延遲。
- 每個輸出應帶 `gps_age_ms` 與狀態：

  ```text
  valid       = fix 有效且 GPS age 在門檻內
  invalid_fix = 收到 GPS 訊息但沒有定位
  stale       = 最後有效資料太舊
  unavailable = 從未收到可用 GPS
  ```

- GPS 約 1 Hz 時可先用 2 秒作 stale 門檻，之後依實測調整。GPS 暫時缺失
  時 YOLO／相機仍可運作，但目標座標必須標記 stale/unavailable，不能悄悄
  無限沿用舊位置。

### 1 Hz GPS 對齊與位置補償

- 相機約 30 FPS、GPS 預設約 1 Hz。若無人機以 10 m/s 移動，直接沿用上
  一筆 GPS，最差可接近 10 m 的時間落後誤差。
- 即時模式可用 SOG、COG 與 Jetson monotonic 時差短期外推：

  ```python
  dt = (frame_mono_ns - gps_mono_ns) / 1e9
  north_speed = speed_mps * cos(radians(cog_deg))
  east_speed = speed_mps * sin(radians(cog_deg))
  north_offset = north_speed * dt
  east_offset = east_speed * dt
  ```

- 建議只做有限外推：`age <= 1.5 s` 正常使用，1.5～2 s 降低可信度，
  `> 2 s` 標為 stale。門檻需用實際 GPS 更新間隔與飛行速度驗證。
- 若允許約一個 GPS 週期的延遲，可等待下一筆 GPS，依 frame monotonic
  time 在前後兩筆位置之間插值；轉彎／變速時通常比只用上一筆外推準。
- 時間補償只能改善位置陳舊造成的誤差，不能消除 GPS 本身誤差、COG/yaw
  不一致、roll/pitch、相機接收延遲或 bbox 落點模型誤差。
- SAM-M8Q 不只支援 1 Hz；可考慮改成 UBX-NAV-PVT、提高 UART baud rate
  至 38400/115200，再測試 5～10 Hz。即使提高頻率，monotonic 對齊仍保留。

## `/dev/ttyUSB0` 實際檢查

重新插入後已偵測：

```text
Device: /dev/ttyUSB0
USB ID: 1a86:7523
Adapter: QinHeng CH340 USB serial converter
Stable path: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
Permissions: root:dialout 0660
```

首次檢查時，當時的 session 尚未取得 `dialout` 群組，讀取失敗：

```text
PermissionError: [Errno 13] Permission denied: '/dev/ttyUSB0'
```

後續群組權限與 NMEA 實測結果如下。

### 2026-08-18 接續實測

- 系統群組資料已確認 `lab508-orin` 是 `dialout` 成員；舊 Codex sandbox
  session 顯示的群組清單未刷新，但在主機環境可正常唯讀開啟裝置。
- 以 9600 baud 監測 15 秒，成功收到 NMEA，未輸出或保存座標：

  ```text
  GGA  15（約 1 Hz）
  GLL  15（約 1 Hz）
  GSA  30（含多 GNSS／多句組，不能解讀成 2 Hz 定位更新）
  GSV  30（含多頁衛星資訊，不能解讀成 2 Hz 定位更新）
  RMC  16（約 1 Hz）
  VTG  15（約 1 Hz）
  TXT   1
  ```

- Checksum：122 句有效、2 句無效。
- 當時尚未定位：RMC status `V`、GGA quality `0`、衛星數 `00`、
  GSA fix type `1`。
- RMC/GGA 的 UTC 欄位及 RMC 日期欄位當時皆為空，因此尚未取得可用的
  GPS UTC/date。需將天線移至可見天空處，待 2D/3D fix 後再次檢查。

### 2026-08-18 第二次即時實測

- 再以 9600 baud 監測 6 秒，成功收到 48 句 checksum 有效、1 句無效；
  GGA/GLL/RMC/VTG 各約 1 Hz，GSA/GSV 因多星系統／多頁訊息而每秒多句。
- Talker prefixes 有：`GP`（GPS）、`GL`（GLONASS）、`GN`（合併星系統）。
- 這次 UTC/date 欄位已出現：

  ```text
  RMC UTC = 09:27:47.00
  RMC date = 180826（2026-08-18）
  GGA/GLL UTC = 09:27:47.00
  ```

- 但導航仍無效：

  ```text
  RMC status = V
  RMC mode = N
  GGA quality = 0
  satellites = 00
  GSA fix type = 1
  PDOP/HDOP/VDOP = 99.99
  speed / COG / altitude / position = unavailable
  ```

- 結論：SAM-M8Q 確實會輸出 UTC/date，但目前只有欄位值，尚不能僅靠
  NMEA 判定它已由 GNSS 完整確認。後續若啟用 UBX-NAV-PVT，應檢查
  `validDate`、`validTime`、`fullyResolved`、`confirmedDate`、
  `confirmedTime`。

## SAM-M8Q 可提供的資訊

- 預設 NMEA 輸出：

  ```text
  RMC = UTC、日期、位置、SOG、COG、有效狀態
  GGA = UTC、位置、fix quality、衛星數、HDOP、海拔、geoid separation
  GLL = 位置、UTC、有效狀態
  GSA = 2D/3D fix、使用衛星、PDOP/HDOP/VDOP
  GSV = 可見衛星、方位角、仰角、SNR
  VTG = 真北／磁北航跡、knots/km/h 地面速度
  TXT = 模組啟動、版本或狀態文字
  ```

- GGA altitude 是相對平均海平面的高度，不是 AGL；目前程式仍使用手動
  `ALTITUDE_AGL_M=75.0`。
- 可另外啟用 UBX binary，例如 UBX-NAV-PVT／UBX-NAV-TIMEUTC，取得
  `iTOW`、UTC 年月日時分秒、`nano` 修正及時間有效旗標。
- SparkFun SAM-M8Q 板有 PPS/TIMEPULSE 腳位，預設可輸出 1 PPS 並對齊
  GNSS/UTC 整秒；PPS 不會因為使用 CH340 `/dev/ttyUSB0` 就自動成為精準
  host timestamp，需要另接 Jetson GPIO 並做 kernel/應用層 timestamp。
- SAM-M8Q 本身不提供機身 roll、pitch、yaw、相機曝光 timestamp 或真正
  AGL；靜止時也無法靠 COG 得到可靠機頭方向。

## 相機投影模型

### 目前 Final：垂直向下 90°

- `gps_geolocation.py::pixel_to_ground_offset()` 明確假設相機光軸垂直向下、
  地面平坦、不補償 roll/pitch、無鏡頭畸變校正。
- 以 bbox 中心、frame 原始寬高、HFOV/VFOV 與固定 AGL 將 pixel 轉成
  `image_right_m`／`image_forward_m`，再用 COG + yaw offset 旋轉為 N/E。
- Final 參數：

  ```text
  ALTITUDE_AGL_M = 75.0
  HFOV_DEG = 52.0
  VFOV_DEG = 31.0
  CAMERA_YAW_OFFSET_DEG = 180.0
  ROTATE_180 = False
  ```

- 在 75 m、HFOV 52°、VFOV 31° 下，理論邊界約為左右各 36.6 m、上下
  各 20.8 m，總覆蓋約 73.2 × 41.6 m。`CAMERA_YAW_OFFSET_DEG=180°`
  只處理地面平面內的 yaw，不代表相機向下角度。

### 若相機改為向下 45°

- 不能只改 FOV 或 yaw；現行公式會把畫面中心錯放在無人機正下方。
- 若「向下 45°」是相對水平線的俯角，在 AGL 75 m 時畫面中心約落在
  前方 75 m。以 VFOV 31° 計算：

  ```text
  上緣俯角 = 29.5° → 前方約 132.6 m
  中心俯角 = 45.0° → 前方 75.0 m
  下緣俯角 = 60.5° → 前方約 42.4 m
  ```

- 地面 footprint 會成為透視梯形。需改成：pixel → 相機座標射線 → 套用
  camera pitch/yaw（以及機身 roll/pitch/yaw）→ 射線與地面平面求交 → N/E。
- 若雲台能相對世界穩定保持 45°，固定 camera pitch 尚可；若相機硬鎖在
  機身，前飛傾斜會持續改變光軸，最好由飛控取得 roll/pitch/yaw。

## 下次接續步驟

1. 在可見天空處讓 SAM-M8Q 取得 fix，再確認 RMC/GGA/VTG 的位置、速度、
   COG、UTC/date 與穩定更新率；測試輸出時避免顯示座標。
2. 試飛 M490TOP 簡單緩彎航線，確認位置 S-Curve 與箭頭／機頭 yaw 行為；
   若能匯出參數，檢查 `WP_YAW_BEHAVIOR`。
3. 實作 Jetson 共同 monotonic timebase：frame/GPS 分別記 receive timestamp、
   保存 GPS age/status，先完成最近資料配對與 stale 防護。
4. 再加入 1 Hz GPS 的 SOG/COG 有限外推；若可接受延遲，再比較前後 GPS
   插值。用實際 flight log 量測誤差後調整 1.5/2 秒門檻。
5. 評估將 SAM-M8Q 改成 UBX-NAV-PVT 及 5～10 Hz；若要求精準 UTC 同步，
   再把 PPS 接至 Jetson GPIO。
6. 相機若維持正下視，先實測／校正 FOV、AGL、yaw offset 與鏡頭畸變；
   若改成 45°，重寫為完整 ray-ground intersection，不能沿用現行投影。

## 官方參考

- ArduPilot Auto Mode：<https://ardupilot.org/copter/docs/auto-mode.html>
- ArduPilot Copter parameters：<https://ardupilot.org/copter/docs/parameters.html>
- ArduPilot Mission Commands：
  <https://ardupilot.org/copter/docs/common-mavlink-mission-command-messages-mav_cmd.html>
- SparkFun SAM-M8Q Hookup Guide：
  <https://learn.sparkfun.com/tutorials/sparkfun-gps-breakout-zoe-m8q-and-sam-m8q-hookup-guide/all>
- u-blox SAM-M8Q datasheet：
  <https://content.u-blox.com/sites/default/files/documents/SAM-M8Q_DataSheet_UBX-16012619.pdf>
- u-blox 8 / M8 Receiver Protocol Specification：
  <https://content.u-blox.com/sites/default/files/products/documents/u-blox8-M8_ReceiverDescrProtSpec_UBX-13003221.pdf>
