import sys, socket, time, json, collections, datetime
sys.path.insert(0, '/tmp/mavlink-monitor-deps')
from pymavlink.dialects.v20 import ardupilotmega as mav

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', 14550))
sock.settimeout(1)
start = time.monotonic()
parsers = {}
counts = collections.Counter()
latest = {}
ranges = {}
sources = collections.Counter()
versions = collections.Counter()
packets = 0
out = '/tmp/mavlink_14550_capture.json'
print('Listening UDP 0.0.0.0:14550 for 60 seconds (receive only)', flush=True)
while time.monotonic() - start < 60:
    try:
        data, peer = sock.recvfrom(65535)
    except socket.timeout:
        continue
    packets += 1
    sources[str(peer)] += 1
    parser = parsers.setdefault(peer, mav.MAVLink(None))
    parser.robust_parsing = True
    try:
        messages = parser.parse_buffer(data) or []
    except Exception as exc:
        print('Parse error:', str(exc), flush=True)
        continue
    for msg in messages:
        name = msg.get_type()
        counts[name] += 1
        if name == 'BAD_DATA':
            continue
        versions[str(msg.get_msgbuf()[0])] += 1
        key = f'{msg.get_srcSystem()}:{msg.get_srcComponent()}:{name}'
        value = msg.to_dict()
        latest[key] = value
        for field, val in value.items():
            if isinstance(val, (int, float)):
                k = key + ':' + field
                lo, hi = ranges.get(k, (val, val))
                ranges[k] = [min(lo, val), max(hi, val)]
        if counts[name] == 1:
            print(json.dumps({'source': peer, 'system': msg.get_srcSystem(), 'component': msg.get_srcComponent(), 'first': value}, ensure_ascii=False), flush=True)
sock.close()
report = {'timestamp': datetime.datetime.now().astimezone().isoformat(), 'seconds': time.monotonic()-start, 'udp_packets': packets, 'sources': dict(sources), 'frame_magic_counts': dict(versions), 'message_counts': dict(counts), 'latest': latest, 'numeric_ranges': ranges}
with open(out, 'w') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print('SUMMARY', json.dumps(report, ensure_ascii=False), flush=True)
print('Saved:', out, flush=True)
