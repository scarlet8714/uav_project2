"""Exercise installer safeguards without root, packages, interfaces or real keys."""
import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import setup_jetson_wireguard as setup


class JetsonSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "systemd").mkdir()
        (self.root / "comm").write_text("systemd\n")
        self.directory = self.root / "wireguard"
        self.conf = self.directory / "wg-uav.conf"
        self.key = self.directory / "wg-uav.key"
        self.dropin_directory = self.root / "unit.d"
        self.dropin = self.dropin_directory / "10-uav-userspace.conf"
        self.private = base64.b64encode(b"\x01" * 32).decode()
        self.public = base64.b64encode(b"\x02" * 32).decode()
        self.gcp = base64.b64encode(b"\x03" * 32).decode()
        self.route = {"dev": "eth0", "gateway": "192.168.125.1", "prefsrc": "192.168.125.100"}
        self.current_route = dict(self.route)
        self.routes = [{"dst": "default", "dev": "eth0"},
                       {"dst": "192.168.125.0/24", "dev": "eth0"}]
        self.kind = ""
        self.allowed = "10.77.0.1/32"
        self.ufw = False
        self.userspace_binary = "wireguard"
        self.calls = []
        for target, replacement in (
            ("Path", self.redirect_path), ("run", self.fake_run),
            ("os.geteuid", lambda: 0), ("shutil.which", self.which),
        ):
            patcher = patch.object(setup, target, replacement) if "." not in target else patch(
                "setup_jetson_wireguard." + target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def redirect_path(self, name):
        return {
            "/etc/wireguard": self.directory,
            "/run/systemd/system": self.root / "systemd",
            "/proc/1/comm": self.root / "comm",
            "/sys/class/net/wg-uav": self.root / "net-wg-uav",
            "/etc/systemd/system/wg-quick@wg-uav.service.d": self.dropin_directory,
        }.get(str(name), Path(name))

    def which(self, name):
        if (name == "ufw" and not self.ufw
                or name in ("wireguard", "wireguard-go") and name != self.userspace_binary):
            return None
        return "/usr/bin/" + name

    def fake_run(self, args, **kwargs):
        self.calls.append(tuple(args))
        if args[:5] == ["ip", "-j", "-4", "route", "get"]:
            route = ({"dev": "wg-uav"} if args[-1] == "10.77.0.1"
                     else self.current_route if self.conf.exists() else self.route)
            return json.dumps([route])
        if args == ["ip", "-j", "-4", "route", "show", "table", "all"]:
            return json.dumps(self.routes)
        if args[:5] == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps([{"linkinfo": {"info_kind": self.kind}}])
        if args == ["ip", "-j", "address", "show", "dev", "wg-uav"]:
            return json.dumps([{"mtu": 1280, "addr_info": [
                {"local": "10.77.0.2", "prefixlen": 32}]}])
        if args == ["wg", "genkey"]:
            return self.private
        if args == ["wg", "pubkey"]:
            self.assertEqual(kwargs["data"], self.private + "\n")
            return self.public
        if args[:3] == ["wg", "show", "wg-uav"]:
            return {"public-key": self.public, "peers": self.gcp,
                    "allowed-ips": self.gcp + "\t" + self.allowed,
                    "endpoints": self.gcp + "\t104.155.197.179:51820",
                    "persistent-keepalive": self.gcp + "\t25"}[args[-1]]
        if args == ["env", "LC_ALL=C", "ufw", "status"]:
            return "Status: active"
        if args[0] in ("apt-get", "env", "systemctl", "ufw"):
            return ""
        self.fail("Unexpected command: " + repr(args))

    def install(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            setup.main(["--gcp-public-key", self.gcp])
        return output.getvalue()

    def existing(self):
        self.directory.mkdir()
        self.key.write_text(self.private + "\n")
        self.conf.write_text(setup.jetson_config(self.private, self.gcp))

    def assert_no_install(self):
        self.assertFalse(any("apt-get" in call for call in self.calls))

    def test_install_has_userspace_package_and_keeps_secrets_local(self):
        output = self.install()
        install = next(call for call in self.calls if "install" in call)
        self.assertIn("--no-install-recommends", install)
        self.assertIn("wireguard-go", install)
        self.assertIn("wireguard-tools", install)
        self.assertNotIn("wireguard", install)
        for path, mode in ((self.directory, 0o700), (self.key, 0o600), (self.conf, 0o600)):
            self.assertEqual(path.stat().st_mode & 0o777, mode)
        self.assertIn("JETSON_PUBLIC_KEY=" + self.public, output)
        self.assertNotIn(self.private, output)
        self.assertNotIn("0.0.0.0/0", self.conf.read_text())
        self.assertNotIn("DNS", self.conf.read_text())

    def test_ubuntu_binary_name_is_configured_for_boot_before_service_start(self):
        self.install()
        self.assertEqual(self.dropin.read_text(),
                         '[Service]\nEnvironment="WG_QUICK_USERSPACE_IMPLEMENTATION=/usr/bin/wireguard"\n')
        self.assertEqual(self.dropin.stat().st_mode & 0o777, 0o644)
        self.assertLess(self.calls.index(("systemctl", "daemon-reload")),
                        self.calls.index(("systemctl", "enable", "--now", "wg-quick@wg-uav.service")))

    def test_upstream_binary_name_is_also_supported(self):
        self.userspace_binary = "wireguard-go"
        self.install()
        self.assertIn("WG_QUICK_USERSPACE_IMPLEMENTATION=/usr/bin/wireguard-go", self.dropin.read_text())

    def test_missing_userspace_binary_stops_before_key_generation_or_activation(self):
        self.userspace_binary = None
        with self.assertRaisesRegex(RuntimeError, "找不到 userspace"):
            self.install()
        self.assertNotIn(("wg", "genkey"), self.calls)
        self.assertFalse(any("enable" in call for call in self.calls))

    def test_conflicting_systemd_dropin_is_preserved(self):
        self.dropin_directory.mkdir()
        self.dropin.write_text("[Service]\nEnvironment=ANOTHER_SETTING=1\n")
        with self.assertRaisesRegex(RuntimeError, "userspace 設定不同"):
            self.install()
        self.assertIn("ANOTHER_SETTING=1", self.dropin.read_text())
        self.assertFalse(any("enable" in call for call in self.calls))

    def test_rerun_preserves_private_key(self):
        self.install()
        self.calls.clear()
        self.install()
        self.assertNotIn(("wg", "genkey"), self.calls)
        self.assertEqual(self.key.read_text(), self.private + "\n")

    def test_conflicting_config_stops_before_package_changes(self):
        self.existing()
        original = self.conf.read_text().replace("10.77.0.1/32", "0.0.0.0/0")
        self.conf.write_text(original)
        with self.assertRaisesRegex(RuntimeError, "既有 wg-uav 設定"):
            self.install()
        self.assert_no_install()
        self.assertEqual(self.conf.read_text(), original)

    def test_missing_private_key_does_not_rotate_identity(self):
        self.existing()
        self.key.unlink()
        with self.assertRaisesRegex(RuntimeError, "找不到對應私鑰"):
            self.install()
        self.assert_no_install()

    def test_existing_unmanaged_interface_is_preserved(self):
        (self.root / "net-wg-uav").mkdir()
        with self.assertRaisesRegex(RuntimeError, "其他設定"):
            self.install()
        self.assert_no_install()

    def test_symlink_key_is_rejected(self):
        self.directory.mkdir()
        self.key.symlink_to(self.root / "another-service-key")
        with self.assertRaisesRegex(RuntimeError, "符號連結"):
            self.install()
        self.assert_no_install()

    def test_tailscale_endpoint_is_rejected(self):
        self.route["dev"] = "tailscale0"
        with self.assertRaisesRegex(RuntimeError, "VPN 路由"):
            self.install()
        self.assert_no_install()

    def test_other_vpn_endpoint_is_rejected(self):
        self.kind = "tun"
        with self.assertRaisesRegex(RuntimeError, "VPN 路由"):
            self.install()
        self.assert_no_install()

    def test_overlapping_lan_route_is_rejected(self):
        self.routes.append({"dst": "10.77.0.0/24", "dev": "eth1"})
        with self.assertRaisesRegex(RuntimeError, "路由重疊"):
            self.install()
        self.assert_no_install()

    def test_runtime_full_tunnel_is_rejected(self):
        self.allowed = "0.0.0.0/0"
        with self.assertRaisesRegex(RuntimeError, "AllowedIPs"):
            self.install()

    def test_changed_public_route_does_not_report_success(self):
        self.current_route["dev"] = "tailscale0"
        with self.assertRaisesRegex(RuntimeError, "公網路由已改變"):
            self.install()

    def test_active_ufw_only_allows_the_relay_app(self):
        self.ufw = True
        self.install()
        self.assertIn(("ufw", "allow", "in", "on", "wg-uav", "proto", "tcp", "from",
                       "10.77.0.1", "to", "10.77.0.2", "port", "8081", "comment",
                       "uav-web-relay"), self.calls)

    def test_nonroot_stops_before_running_commands(self):
        with patch("setup_jetson_wireguard.os.geteuid", return_value=1000):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.install()
        self.assertEqual(self.calls, [])


class InstalledQuickTests(unittest.TestCase):
    @unittest.skipUnless(Path("/usr/bin/wg-quick").exists(), "wg-quick is not installed")
    def test_installed_wg_quick_uses_environment_override_after_kernel_failure(self):
        # Execute the installed add_if function with a failing fake ip and a
        # fake userspace binary. No root or network interface is involved.
        source = Path("/usr/bin/wg-quick").read_text()
        function = source[source.index("add_if() {"):source.index("\ndel_if() {")]
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            ip = directory / "ip"
            ip.write_text("#!/bin/sh\nexit 1\n")
            binary = directory / "wireguard"
            binary.write_text('#!/bin/sh\nprintf "userspace-called:%s\\n" "$1"\n')
            ip.chmod(0o700)
            binary.chmod(0o700)
            script = ('set -e\nPATH="$1:/usr/bin:/bin"\n'
                      'export WG_QUICK_USERSPACE_IMPLEMENTATION="$1/wireguard"\n'
                      'INTERFACE=wg-uav\ncmd() { "$@"; }\n' + function + '\nadd_if\n')
            result = subprocess.run(["/bin/bash", "-c", script, "test", name],
                                    text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("userspace-called:wg-uav", result.stdout)


if __name__ == "__main__":
    unittest.main()
