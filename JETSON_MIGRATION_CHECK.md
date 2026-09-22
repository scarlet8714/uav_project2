# 換機檢查：2026-09-05

## 結果

系統 Python 3.10.12 可直接使用。已補安裝 requirements.txt 與
requirements-yolo.txt 中缺少的套件；保留既有 NVIDIA PyTorch、
torchvision、NumPy 1.26.1 和系統編譯 OpenCV 4.8.0。

主機環境是 Jetson Linux R36.3.0／TensorRT 8.6.2，與原 README 的
R36.5.0 不同。tiscamera 0.14.0、Tcam 0.1、nvvidconv 和
nvv4l2h264enc 均存在，相機序號為 26410280。

## 已通過的實機檢查

- PyTorch 可使用 CUDA；torchvision CUDA NMS 執行成功。
- yolo_final_jetson_h264 及相依模組匯入成功。
- 使用 yolo11s.pt、tiscamera、1920×1080 @ 30 FPS 和 --no-gps
  啟動 final processor，GPS thread 未啟動。
- HTTP 首頁、相機狀態 API、WebRTC offer 均回應 200。
- 相機狀態回報曝光、亮度、對比、飽和度、增益、銳利度可用。
- SDP 僅協商 H264/90000；NVENC 實際啟動，本機 aiortc 接收端
  成功解碼 60 幀 1920×1080 影像。
- 測試後關閉 peer、processor 與相機，程序正常退出。

這是短時間本機端到端測試，未測遠端瀏覽器、長時間效能、相機控制寫入、
截圖或 GPS。設定的 30 FPS 不等於本次量測到的穩態推論 FPS。

## 尚未解決：原 car 模型

11s_car_544_960.engine 實際推論時反序列化失敗：

```text
Current Version: 236, Serialized Engine Version: 239
TensorRT model exported with a different version than expected
```

需要原 car 模型的 .pt／.onnx，在本機重建 engine。專案現有 yolo11s.pt
是通用 COCO 模型，只能作流程測試，不等同 car 模型；原 engine 未修改。
使用不相容 engine 啟動現行服務時，模型延遲載入會讓背景處理持續報錯，
所以 HTTP 啟動成功本身不能證明推論成功。

## 環境提示

Ultralytics 會提示 torch 2.4／torchvision 0.18 配對警告；此處是
NVIDIA 預發行 PyTorch，CUDA NMS 和完整推論已通過，不直接套用
提示中的 PyPI 升級命令。

pip check 仍回報：

- ultralytics 缺 opencv-python metadata：實際 cv2 4.8.0 來自
  /usr/local/lib/python3.10/dist-packages，取像及推論已驗證。
- pyds 缺 pgi、onnx-graphsurgeon 缺 onnx、PyNaCl 1.5.0 平台提示：
  不屬於本次入口所使用的依賴，未修改這些既有套件。

安裝與啟動指令見 README.md。requirements-yolo.txt 必須使用
--no-deps 安裝，避免 pip 另外安裝 OpenCV 遮蔽系統版本。

## USB webcam 追加測試

GENERAL WEBCAM 位於 /dev/video0（另有 /dev/video1）。使用
`yolo_final_jetson_h264.py --camera-backend opencv --camera-index 0
--model-path yolo11s.pt --no-gps` 的設定完成本機端到端測試。
HTTP／camera API／offer 回應 200，NVENC 啟動，成功解碼 300 幀
1920×1080；略過最初 60 幀後接收約 30.05 FPS，結束時 processor
平滑 FPS 約 19.76。接收 FPS 包含重複使用最新處理畫面的情況，
不代表每秒完成 30 次 YOLO 推論。測試後相機與服務已關閉。

限制與觀察：

- 裝置列出的 1080p30 使用 MJPEG，YUYV 最高列出 640×480；
  目前固定 1080p YUY2 的硬體 GStreamer 取像設定不適用這支 webcam。
- 取像持續出現 `Corrupt JPEG data: ... extraneous bytes before marker 0xd9`，
  仍可解碼和推論；尚未確認是裝置輸出或解碼相容性問題。
- 接收端曾出現一次 `No start code is found / Error splitting the input into NAL units`，
  後續仍完成 300 幀接收，未進行長時間穩定性或畫面品質驗證。
- 控制 API 僅 brightness 回報支援，其餘多數既有工業相機控制名稱
  不適用此裝置；未測控制寫入。

## GPS 室內實測

CH340 (1a86:7523) 使用 `/dev/ttyUSB4`，穩定裝置路徑為
`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`。
本機核心未啟用 CONFIG_USB_SERIAL_CH341，已從 Linux stable v5.15.136
的 drivers/usb/serial/ch341.c，以本機 headers 編譯 /tmp/uav-ch341-build/ch341.ko，
使用者手動 insmod 載入成功。brltty-udev 曾搶佔裝置；使用者 runtime mask
並停止服務後重新插入，串口恢復。這些修正尚未永久安裝，重開機後需要重新處理；
/tmp 中編譯產物也不是永久備份。

9600 baud 讀取約 20 秒，收到 4548 bytes、161 筆 checksum 通過的 NMEA
（RMC/GGA 各 20 筆），另有 1 筆無效或不完整資料。RMC=V、GGA quality=0、
使用衛星數=0，最後一筆 GSV 可見衛星數=0。
GPSReader 連續三次讀取均 connected=True、fix_valid=False，無位置，
錯誤為 RMC received but fix is invalid；停止後 thread 正常退出。
通訊及解析成功，尚未驗證戶外定位或 GPS 與影像同時執行。

yolo_final.py 與 yolo_final_jetson_h264.py 新增 --gps-port，使用時指定上述
by-id 路徑，啟用 GPS 時不要加 --no-gps。
