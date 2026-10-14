#!/usr/bin/env python3
"""Jetson-only WireGuard setup; does not start the camera/YOLO application."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from relay_config import (
    APP_PORT, GCP_IP, INTERFACE, JETSON_IP, PUBLIC_IP, WG_PORT,
    jetson_config, public_key, route_conflicts,
)


def run(args, *, data=None, show=False, sensitive=False):
    result = subprocess.run(args, input=data, text=True, capture_output=not show, check=False)
    if result.returncode:
        detail = "" if show or sensitive else (result.stderr or "").strip()
        raise RuntimeError(f"{args[0]} 執行失敗：{detail}")
    return (result.stdout or "").strip()


def configure_userspace():
    # Ubuntu's wireguard-go package installs /usr/bin/wireguard, whereas
    # wg-quick defaults to the upstream executable name wireguard-go.
    binary = shutil.which("wireguard-go") or shutil.which("wireguard")
    if not binary:
        raise RuntimeError("wireguard-go 套件安裝後仍找不到 userspace 執行檔")
    directory = Path(f"/etc/systemd/system/wg-quick@{INTERFACE}.service.d")
    override = directory / "10-uav-userspace.conf"
    expected = f'[Service]\nEnvironment="WG_QUICK_USERSPACE_IMPLEMENTATION={binary}"\n'
    if directory.is_symlink() or override.is_symlink():
        raise RuntimeError("wg-uav 的 systemd 設定是符號連結；不會覆寫")
    if override.exists() and override.read_text() != expected:
        raise RuntimeError("既有 wg-uav userspace 設定不同；請先檢查，不會覆寫")
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    if not override.exists():
        with override.open("x") as output:
            output.write(expected)
        os.chmod(override, 0o644)
    run(["systemctl", "daemon-reload"])
    return binary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcp-public-key", required=True)
    args = parser.parse_args(argv)
    gcp_public = public_key(args.gcp_public_key)
    if (os.geteuid() != 0 or not Path("/run/systemd/system").is_dir()
            or Path("/proc/1/comm").read_text().strip() != "systemd"):
        parser.error("請在 Jetson 的普通終端以 sudo 執行")
    if sys.version_info < (3, 8):
        raise RuntimeError("Jetson 安裝腳本需要 Python 3.8+，不會升級系統 Python")
    for command in ("ip", "apt-get", "systemctl"):
        if not shutil.which(command):
            raise RuntimeError(f"缺少 {command}，本安裝包適用有 systemd 的 Ubuntu／Debian Jetson")
    endpoint_route = json.loads(run(["ip", "-j", "-4", "route", "get", PUBLIC_IP]))[0]
    dev = endpoint_route.get("dev", "")
    link = json.loads(run(["ip", "-j", "-d", "link", "show", "dev", dev]))[0]
    kind = link.get("linkinfo", {}).get("info_kind", "")
    if dev in {"tailscale0", INTERFACE, "lo"} or kind in {"wireguard", "tun"}:
        raise RuntimeError(f"GCP 公網 IP 目前走 {dev}；先確認 exit node／其他 VPN 路由再設定")
    conflicts = route_conflicts(json.loads(run(["ip", "-j", "-4", "route", "show", "table", "all"])))
    if conflicts:
        raise RuntimeError(f"WireGuard 私網 IP 與既有路由重疊：{conflicts}")
    directory = Path("/etc/wireguard")
    conf = directory / f"{INTERFACE}.conf"
    key = directory / f"{INTERFACE}.key"
    if any(path.is_symlink() for path in (directory, conf, key)):
        raise RuntimeError("WireGuard 目錄或檔案是符號連結；停止以免改到其他設定")
    if not conf.exists() and Path(f"/sys/class/net/{INTERFACE}").exists():
        raise RuntimeError("wg-uav 已被其他設定使用，不會覆寫")
    if conf.exists() and not key.exists():
        raise RuntimeError("已有設定但找不到對應私鑰檔，不會重新產生金鑰")
    if conf.exists() and conf.read_text() != jetson_config(key.read_text().strip(), gcp_public):
        raise RuntimeError("既有 wg-uav 設定與本次不同；不會覆寫，請先檢查")
    run(["apt-get", "update"], show=True)
    # Jetson kernels may omit CONFIG_WIREGUARD. Install the userspace fallback
    # without the wireguard metapackage's kernel recommends.
    run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y",
         "--no-install-recommends", "wireguard-tools", "wireguard-go"], show=True)
    userspace = configure_userspace()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if not key.exists():
        private = run(["wg", "genkey"], sensitive=True)
        with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            output.write(private + "\n")
    private = key.read_text().strip()
    own_public = run(["wg", "pubkey"], data=private + "\n", sensitive=True)
    if own_public == gcp_public:
        raise RuntimeError("GCP 公鑰與本機公鑰相同；應在 Jetson 上使用 GCP 公鑰")
    expected = jetson_config(private, gcp_public)
    if conf.exists() and conf.read_text() != expected:
        raise RuntimeError("既有 wg-uav 設定與本次不同；不會覆寫，請先檢查")
    if not conf.exists():
        fd, name = tempfile.mkstemp(prefix=".uav-", dir=directory)
        try:
            with os.fdopen(fd, "w") as output:
                output.write(expected)
            os.replace(name, conf)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    os.chmod(key, 0o600)
    os.chmod(conf, 0o600)
    try:
        run(["systemctl", "enable", "--now", f"wg-quick@{INTERFACE}.service"], show=True)
    except RuntimeError:
        run(["journalctl", "-u", f"wg-quick@{INTERFACE}.service", "-n", "40", "--no-pager"], show=True)
        raise
    if (run(["wg", "show", INTERFACE, "public-key"]) != own_public
            or run(["wg", "show", INTERFACE, "peers"]).split() != [gcp_public]):
        raise RuntimeError("正在執行的 wg-uav 金鑰與設定不符，請先檢查")
    addresses = json.loads(run(["ip", "-j", "address", "show", "dev", INTERFACE]))[0]
    if addresses.get("mtu") != 1280 or not any(
        item.get("local") == JETSON_IP and item.get("prefixlen") == 32
        for item in addresses.get("addr_info", [])
    ):
        raise RuntimeError("wg-uav 的位址或 MTU 與預期不符")
    route = json.loads(run(["ip", "-j", "-4", "route", "get", GCP_IP]))[0]
    if route.get("dev") != INTERFACE:
        raise RuntimeError("GCP 隧道 IP 沒有走 wg-uav，請先檢查路由")
    if (run(["wg", "show", INTERFACE, "allowed-ips"]).split() != [gcp_public, f"{GCP_IP}/32"]
            or run(["wg", "show", INTERFACE, "endpoints"]).split() != [gcp_public, f"{PUBLIC_IP}:{WG_PORT}"]
            or run(["wg", "show", INTERFACE, "persistent-keepalive"]).split() != [gcp_public, "25"]):
        raise RuntimeError("wg-uav 的 AllowedIPs、endpoint 或 keepalive 與預期不符")
    current_route = json.loads(run(["ip", "-j", "-4", "route", "get", PUBLIC_IP]))[0]
    if any(current_route.get(field) != endpoint_route.get(field)
           for field in ("dev", "gateway", "prefsrc", "src")):
        raise RuntimeError("GCP 公網路由已改變，請先檢查；尚未確認隧道完成")
    if shutil.which("ufw") and "Status: active" in run(["env", "LC_ALL=C", "ufw", "status"]):
        run(["ufw", "allow", "in", "on", INTERFACE, "proto", "tcp", "from", GCP_IP,
             "to", JETSON_IP, "port", str(APP_PORT), "comment", "uav-web-relay"], show=True)
    print(f"Jetson 設定完成；公網 GCP 原路由介面：{dev}")
    print(f"WireGuard userspace 備援執行檔：{userspace}")
    print(f"JETSON_PUBLIC_KEY={own_public}")
    print("請把以上公鑰登記到 GCP；此時尚未代表 handshake 或串流已成功。")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        raise SystemExit(f"停止：{error}")
