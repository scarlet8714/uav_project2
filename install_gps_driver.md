# Jetson GPS USB 驅動安裝與開機設定

可以全部使用終端機指令完成，不需要圖形安裝程式。本文針對 GPS 使用的
CH340 USB 轉串口晶片；Linux 對應驅動名稱是 **ch341**。
驅動讓系統建立串口，GPS 是否能定位仍取決於天線、衛星訊號等條件。

本專案已驗證環境：Jetson Linux R36.3.0、核心 `5.15.136-tegra`、
aarch64、CH340 USB ID `1a86:7523`。以下編譯方法針對此環境；
其他核心應使用相符的原始碼與 headers，不能直接搬用這台的 `.ko`。

## 1. 確認 USB、核心與驅動

接上 GPS 後執行：

```bash
uname -r
lsusb
modinfo ch341
lsmod | grep ch341
python3 -m serial.tools.list_ports -v
```

- `lsusb` 應列出 `1a86:7523`／CH340。
- `modinfo ch341` 成功：模組已安裝，可先執行 `sudo modprobe ch341`，
  不需要重新編譯，接著檢查串口與 brltty。
- `Module ch341 not found`：目前核心找不到模組，依下一節編譯。
- USB 清單完全沒有 CH340：先檢查 USB 線材、供電與接頭；載入驅動
  無法解決 USB 本身沒有枚舉的問題。

`serial.tools.list_ports` 來自專案的 pyserial 套件；沒有安裝時也可以用：

```bash
ls -l /dev/serial/by-id/
sudo journalctl -k -n 50 --no-pager
```

## 2. 缺少模組時：編譯 ch341

本機原本的核心設定為 `# CONFIG_USB_SERIAL_CH341 is not set`，
但已有可用的核心 headers，因此可以單獨編譯模組，不必重編整個核心。

安裝編譯工具：

```bash
sudo apt update
sudo apt install build-essential curl
```

確認 headers 與符號表存在：

```bash
ls -ld /lib/modules/$(uname -r)/build
ls /lib/modules/$(uname -r)/build/Module.symvers
ls /lib/modules/$(uname -r)/build/include/generated/autoconf.h
```

若缺少 headers，Jetson 可先檢查 NVIDIA 套件來源提供的版本：

```bash
apt-cache policy nvidia-l4t-kernel nvidia-l4t-kernel-headers
```

只有候選 headers 與目前 Jetson Linux／核心版本相符時才安裝：

```bash
sudo apt install nvidia-l4t-kernel-headers
```

安裝後重新確認 `/lib/modules/$(uname -r)/build`。不要用一般 Ubuntu
`linux-headers-generic` 代替 Jetson 核心 headers；也不要為了安裝驅動
直接換成不相符的最新版 headers。找不到對應版本時，需先取得該版
Jetson Linux 的 headers／核心原始碼。

以下整段限目前已驗證的 `5.15.136-tegra`，在同一個終端機貼上執行。
原始碼來自 [Linux stable v5.15.136 的 ch341.c](https://github.com/gregkh/linux/blob/v5.15.136/drivers/usb/serial/ch341.c)：

```bash
(
  set -eu
  test "$(uname -r)" = '5.15.136-tegra' || {
    echo '核心版本不同，請先取得對應版本原始碼與 headers。'
    exit 1
  }
  gps_build_dir="$HOME/gps-driver-build/5.15.136-tegra"
  mkdir -p "$gps_build_dir"
  cd "$gps_build_dir"
  curl --fail --location --retry 3 \
    https://raw.githubusercontent.com/gregkh/linux/v5.15.136/drivers/usb/serial/ch341.c \
    -o ch341.c
  printf 'obj-m += ch341.o\n' > Makefile
  make -C /lib/modules/$(uname -r)/build M="$gps_build_dir" modules
  modinfo ./ch341.ko
)
```

成功後會有 `~/gps-driver-build/5.15.136-tegra/ch341.ko`。
`vermagic` 必須對應目前的核心；本機實測為
`5.15.136-tegra SMP preempt mod_unload modversions aarch64`。

若發生 `Invalid module format` 或 `Unknown symbol`，先檢查核心紀錄與
headers／Module.symvers 是否相符，不要使用強制載入選項：

```bash
sudo journalctl -k -n 40 --no-pager
```

## 3. 永久安裝並設定開機自動載入

使用上一節編譯的檔案：

```bash
sudo install -D -m 644 \
  "$HOME/gps-driver-build/5.15.136-tegra/ch341.ko" \
  /lib/modules/5.15.136-tegra/extra/ch341.ko
sudo depmod -a 5.15.136-tegra
printf 'ch341\n' | sudo tee /etc/modules-load.d/ch341.conf
sudo modprobe ch341
```

此次協助測試時，模組曾編譯在 `/tmp/uav-ch341-build/ch341.ko`。
若該檔案仍存在且核心相同，可用它替換上面 `install` 的來源路徑；
`/tmp` 可能被清除，長期重建請使用第 2 節。

`depmod` 建立模組及 USB 裝置對應索引，`modules-load.d` 則明確要求
開機載入。這是核心模組，不需要另開 Python 常駐程式。
未來更新核心後，必須為新核心重新編譯、安裝並執行 `depmod`。

## 4. brltty 搶佔 CH340 的問題

本機實際遇到：ch341 建立 `/dev/ttyUSB4` 後，brltty 把 USB 裝置
當成點字設備，重新設定 USB，導致串口消失。

檢查：

```bash
sudo journalctl -k -n 60 --no-pager
systemctl status brltty.service brltty-udev.service --no-pager
pgrep -a brltty
```

典型紀錄：

```text
ch341-uart converter now attached to ttyUSB4
interface 0 claimed by ch341 while 'brltty' sets config #1
ch341-uart converter now disconnected from ttyUSB4
```

### 暫時停用：只對本次開機有效

```bash
sudo systemctl mask --runtime --now brltty-udev.service brltty.service
```

### 永久停用：重開機後仍有效

若這台不使用 brltty 提供的點字設備支援，執行：

```bash
sudo systemctl unmask --runtime brltty-udev.service brltty.service
sudo systemctl mask --now brltty-udev.service brltty.service
```

必須包含 **brltty-udev.service**。只 `disable brltty.service` 不夠，
udev 仍可能啟動另一個服務；`mask` 才會阻止它被啟動。
這會停用 brltty 的點字設備支援；需要該功能的主機應改為調整
針對 CH340 的 udev 比對規則，而不是整體停用。

確認服務完全停止：

```bash
systemctl is-active brltty.service brltty-udev.service
systemctl is-enabled brltty.service brltty-udev.service
pgrep -a brltty
```

預期是 `inactive`、`masked`（暫時設定是 `masked-runtime`），
且 `pgrep` 沒有結果。這些檢查在 inactive／masked／無程序時可能回傳
非零 exit code，不代表停用失敗。

**等服務完全停止後，再拔插 GPS USB。** 本機停止曾需等待約 90 秒；
若還顯示 `deactivating` 就拔插，舊程序仍可能再次搶走 GPS。

若之後要恢復 brltty：

```bash
sudo systemctl unmask --runtime brltty.service brltty-udev.service
sudo systemctl unmask brltty.service brltty-udev.service
sudo systemctl start brltty.service
```

恢復後，原有 CH340 搶佔問題可能再次出現。

## 5. 重開機驗證與串口權限

完成永久設定後，可重開機驗證：

```bash
sudo reboot
```

登入後、GPS 接著的情況下：

```bash
uname -r
lsmod | grep ch341
modinfo ch341
systemctl is-enabled brltty.service brltty-udev.service
ls -l /dev/serial/by-id/
python3 -m serial.tools.list_ports -v
```

本機 GPS 是：

```text
/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 -> ../../ttyUSB4
```

`/dev/ttyUSB0`～`3` 是板上的 FTDI，不是 GPS。請優先用 `by-id` 路徑，
避免 USB 枚舉順序變動；多顆沒有唯一序號的相同 CH340 需另用
`/dev/serial/by-path/` 或自訂 udev 規則區分。

遇到 `Permission denied` 時檢查：

```bash
id
ls -l /dev/ttyUSB4
```

Ubuntu 通常透過 `dialout` 群組授權串口：

```bash
sudo usermod -aG dialout "$USER"
```

執行後登出再登入。本機 jetson 使用者已在 dialout，不需重複修改。

## 6. 測試 GPS 資料與執行專案

先關閉其他正在讀 GPS 的程式，同一串口不要同時開兩個讀取者。
系統 Python 已安裝專案 requirements 的 pyserial／pynmea2 後，可讀取
約 10 秒資料（只讀，不傳送 GPS 設定指令）：

```bash
python3 - <<'PY'
import time
import serial
import pynmea2

port = '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
with serial.Serial(port, 9600, timeout=1, exclusive=True) as gps:
    end = time.monotonic() + 10
    while time.monotonic() < end:
        raw = gps.readline()
        if not raw:
            continue
        try:
            msg = pynmea2.parse(raw.decode('ascii').strip(), check=True)
        except (UnicodeError, ValueError, pynmea2.ParseError):
            continue  # 剛開啟時可能讀到半筆句子
        print(msg)
PY
```

能持续收到 checksum 正確的 NMEA 代表串口通訊成功。
室內可能看到 RMC 狀態 `V`、GGA quality `0`、衛星數 `00`：代表
尚未定位，不能僅憑這點判定 GPS 故障。戶外開闊處才能進一步測定位。
完全無資料時則要檢查 GPS 的 baudrate、供電、UART 接線與輸出設定，
不能單純歸因於室內沒有訊號。

本專案 webcam＋GPS 測試指令：

```bash
python3 yolo_final_jetson_h264.py \
  --camera-backend opencv \
  --camera-index 0 \
  --model-path yolo11s.pt \
  --gps-port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

啟用 GPS 時不要加 `--no-gps`。`yolo_final.py` 也支援 `--gps-port`。
此處用通用 `yolo11s.pt`，原 car engine 尚需依本機 TensorRT 重新匯出。

本次實測結果：9600 baud 約 20 秒取得 161 筆 checksum 正確資料，
GPSReader 為 `connected=True`、`fix_valid=False`，室內無定位；
已驗證通訊與解析，尚未驗證戶外定位或永久設定後的重開機行為。
