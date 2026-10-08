# Managed by uav-web-relay setup
"""Fixed, non-secret settings for the uavproject web relay."""
import base64
import configparser
import ipaddress

PROJECT = "project-5f8f1817-eb20-4a35-a41"
ZONE = "asia-east1-a"
INSTANCE = "uavproject"
PUBLIC_IP = "104.155.197.179"
TAG = "uav-web-relay"
RULE = "uav-web-relay-ingress"
INTERFACE = "wg-uav"
GCP_IP = "10.77.0.1"
JETSON_IP = "10.77.0.2"
WG_PORT = 51820
APP_PORT = 8081
MARKER = "# Managed by uav-web-relay setup"
CERT_NAME = "uav-web-relay-ip"
CERTBOT = "/opt/uav-web-relay/certbot/bin/certbot"


def public_key(value):
    value = value.strip()
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("WireGuard 公鑰格式錯誤") from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode() != value:
        raise ValueError("WireGuard 公鑰必須是 32 bytes 的標準 Base64")
    if decoded == bytes(32):
        raise ValueError("WireGuard 公鑰不可全部為零")
    return value


def route_conflicts(routes):
    conflicts = []
    for route in routes:
        dst = route.get("dst", "default")
        if dst == "default" or route.get("dev") == INTERFACE:
            continue
        network = ipaddress.ip_network(dst, strict=False)
        if network.version == 4 and network.prefixlen:
            if any(ipaddress.ip_address(ip) in network for ip in (GCP_IP, JETSON_IP)):
                conflicts.append(route)
    return conflicts


def rule_matches(rule, network):
    allowed = {}
    for item in rule.get("allowed", []):
        protocol = item.get("IPProtocol")
        protocol = {"6": "tcp", "17": "udp"}.get(protocol, protocol)
        ports = item.get("ports", [])
        # gcloud emits one entry per CLI spec, e.g. separate tcp:80 and tcp:443.
        # An entry with no ports means ALL ports, even if another entry is narrower.
        if protocol not in {"tcp", "udp"} or not ports:
            return False
        allowed.setdefault(protocol, set()).update(ports)
    return (
        rule.get("network") == network
        and rule.get("direction") == "INGRESS"
        and rule.get("priority") == 1000
        and not rule.get("disabled", False)
        and allowed == {"tcp": {"80", "443"}, "udp": {str(WG_PORT)}}
        and set(rule.get("sourceRanges", [])) == {"0.0.0.0/0"}
        and set(rule.get("targetTags", [])) == {TAG}
        and not any(rule.get(field) for field in (
            "denied", "sourceTags", "sourceServiceAccounts", "targetServiceAccounts",
            "destinationRanges",
        ))
    )


def wg_config(private, peer=None):
    text = (
        f"{MARKER}\n[Interface]\nAddress = {GCP_IP}/32\n"
        f"ListenPort = {WG_PORT}\nPrivateKey = {private.strip()}\nMTU = 1280\n"
    )
    if peer:
        text += f"\n[Peer]\nPublicKey = {public_key(peer)}\nAllowedIPs = {JETSON_IP}/32\n"
    return text


def jetson_config(private, gcp_public_key):
    return (
        f"{MARKER}\n[Interface]\nAddress = {JETSON_IP}/32\n"
        f"PrivateKey = {private.strip()}\nMTU = 1280\n\n[Peer]\n"
        f"PublicKey = {public_key(gcp_public_key)}\n"
        f"Endpoint = {PUBLIC_IP}:{WG_PORT}\nAllowedIPs = {GCP_IP}/32\n"
        "PersistentKeepalive = 25\n"
    )


def wg_values(text):
    if not text.startswith(MARKER + "\n"):
        raise RuntimeError("既有 WireGuard 設定不是本安裝程式建立，停止以免覆寫")
    parsed = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parsed.read_string(text)
    except configparser.Error as error:
        # ConfigParser errors can include a malformed line containing a private key.
        raise RuntimeError("WireGuard 設定格式錯誤；請在本機檢查，不會輸出內容") from error
    allowed_sections = {"Interface", "Peer"}
    if set(parsed.sections()) - allowed_sections:
        raise RuntimeError("WireGuard 設定含未預期的 section")
    interface = parsed["Interface"]
    if (set(interface) != {"address", "listenport", "privatekey", "mtu"}
            or interface["address"] != f"{GCP_IP}/32"
            or interface["listenport"] != str(WG_PORT)
            or interface["mtu"] != "1280"):
        raise RuntimeError("既有 WireGuard 設定已被更改；請先檢查，不會覆寫")
    peer = None
    if "Peer" in parsed:
        section = parsed["Peer"]
        if set(section) != {"publickey", "allowedips"} or section["allowedips"] != f"{JETSON_IP}/32":
            raise RuntimeError("既有 WireGuard peer 與預期不符")
        peer = public_key(section["publickey"])
    return interface["privatekey"], peer
