# 新版觀看測試

1. 從專案根目錄執行 `python3 -m rtsp_yolo_direct_with_gcp_stun`，開啟 Jetson 的 8082 網頁。
2. 要使用既有公網 HTTPS／WSS 入口，先停止舊版，再以 `--port 8081` 啟動新版。
3. 從不同網路開啟網頁，查看「影像路徑」與 `/api/health` 的 `ice_pair.path`。
4. 確認影像、YOLO 框／GPS 與 WebSocket 獨立重連，再以 `--ice-transport-policy relay` 比對 TURN。

STUN 直連取決於雙端 NAT／防火牆。顯示 `turn` 代表 ICE 使用保留的中繼路徑。
來源部署歷史見 `BASELINE_NEXT_STEP.md`，不需重新設 WireGuard 或重啟 coturn。
