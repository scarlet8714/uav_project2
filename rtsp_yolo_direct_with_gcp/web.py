"""Browser UI: direct video, time-matched Canvas boxes, and reconnect."""

UI_REVISION = "20261007.3"

HTML = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTSP YOLO GPS GCP TURN</title>
<style>
body{margin:0;background:#17191b;color:#eee;font-family:sans-serif}
main{width:min(96%,1280px);margin:18px auto}
h1{font-size:1.35rem}
#stage{position:relative;width:100%;background:#000}
video{display:block;width:100%;background:#000}
canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#status{white-space:pre-wrap;font-family:monospace;line-height:1.5}
#metadata{font-family:monospace}
</style></head><body><main>
<h1>RTSP + YOLO / GPS · GCP TURN</h1>
<p id="version">GCP · 資料獨立重連 · __UI_REVISION__</p>
<div id="stage"><video id="video" autoplay playsinline muted></video>
<canvas id="overlay"></canvas></div>
<pre id="status">Connecting…</pre>
<pre id="transport">RTP waiting</pre>
<p id="metadata">框／GPS 等待連線</p>
<p>RTSP 來源不提供本機曝光、增益及對焦控制。<a href="/api/health">健康狀態</a></p>
</main><script>
const video = document.getElementById('video');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const status = document.getElementById('status');
const transportStatus = document.getElementById('transport');
const metadataStatus = document.getElementById('metadata');
const iceConfiguration = __TURN_ICE_CONFIGURATION__;
const frontendRevision = '__UI_REVISION__';
let peer = null, socket = null, origin = null, generation = null;
let detections = [], videoPts = null;
let retrySeconds = 1, retryTimer = null, connectionSerial = 0, stopped = false;
let peerId = null, metadataRetrySeconds = 1, metadataRetryTimer = null, metadataOpenTimer = null;
let lastDecodedFrames = null;
let lastReconnectReason = 'initial';
const classColors = new Map([
  ['car', '#00e676'],
  ['light_tactical', '#00d5ff'],
  ['medium_tactical', '#ffeb3b'],
  ['cm34', '#6ca7ff'],
  ['amphibious_armored_vehicle', '#b388ff'],
]);

function colorForClass(label) {
  if (!classColors.has(label)) {
    // Additional classes stay in the yellow/green/cyan/blue/violet hue range.
    const hue = 70 + ((classColors.size - 5) * 137.508) % 190;
    classColors.set(label, `hsl(${hue.toFixed(3)}, 90%, 70%)`);
  }
  return classColors.get(label);
}

function reconnect(reason) {
  if (stopped || retryTimer) return;
  status.textContent = `Reconnecting: ${reason}`;
  lastReconnectReason = reason;
  const oldPeer = peer; peer = null; peerId = null;
  stopMetadata(); oldPeer?.close();
  metadataRetrySeconds = 1;
  metadataStatus.textContent = '框／GPS 等待影像連線';
  origin = null; generation = null; detections = []; videoPts = null;
  lastDecodedFrames = null;
  transportStatus.textContent = 'RTP waiting';
  const delay = retrySeconds * 1000;
  retrySeconds = Math.min(retrySeconds * 2, 8);
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, delay);
}

function stopMetadata() {
  if (metadataRetryTimer !== null) clearTimeout(metadataRetryTimer);
  if (metadataOpenTimer !== null) clearTimeout(metadataOpenTimer);
  metadataRetryTimer = null; metadataOpenTimer = null;
  const oldSocket = socket; socket = null;
  oldSocket?.close();
}

function metadataPeerIsCurrent(pc, id, serial) {
  return !stopped && pc === peer && id === peerId && serial === connectionSerial;
}

function retryMetadata(pc, id, serial) {
  if (!metadataPeerIsCurrent(pc, id, serial) || metadataRetryTimer !== null) return;
  stopMetadata();
  const delay = metadataRetrySeconds * 1000;
  metadataRetrySeconds = Math.min(metadataRetrySeconds * 2, 8);
  metadataStatus.textContent = `框／GPS 中斷，${delay/1000} 秒後重試（保留影像連線）`;
  metadataRetryTimer = setTimeout(() => {
    metadataRetryTimer = null;
    connectMetadata(pc, id, serial);
  }, delay);
}

function connectMetadata(pc, id, serial) {
  if (!metadataPeerIsCurrent(pc, id, serial)) return;
  stopMetadata();
  metadataStatus.textContent = '框／GPS 連線中…';
  let ws;
  try {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//`+
      `${location.host}/events/${id}`);
  } catch (_) {
    retryMetadata(pc, id, serial); return;
  }
  socket = ws;
  const current = () => metadataPeerIsCurrent(pc, id, serial) && socket === ws;
  // A stalled WebSocket handshake must not close or stall the video peer.
  metadataOpenTimer = setTimeout(() => {
    if (current()) retryMetadata(pc, id, serial);
  }, 10000);
  ws.onopen = () => {
    if (!current()) return;
    clearTimeout(metadataOpenTimer); metadataOpenTimer = null;
    metadataRetrySeconds = 1;
    metadataStatus.textContent = '框／GPS 已連線';
  };
  ws.onmessage = event => {
    if (!current()) return;
    let data;
    try { data = JSON.parse(event.data); } catch (_) { return; }
    if (!data || typeof data !== 'object') return;
    if (data.type === 'origin' && Number.isFinite(data.rtpOrigin)) origin = data.rtpOrigin >>> 0;
    if (data.type === 'detection' && data.generation === generation) {
      detections.push(data);
      if (detections.length > 180) detections.shift();
    }
  };
  ws.onclose = ws.onerror = () => { if (current()) retryMetadata(pc, id, serial); };
}

function draw(now, frame) {
  if (peer?.connectionState === 'connected') retrySeconds = 1;
  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (origin !== null && Number.isFinite(frame.rtpTimestamp)) {
    videoPts = (((frame.rtpTimestamp >>> 0) - origin) >>> 0) / 90000;
  }
  const match = videoPts === null ? null :
    [...detections].reverse().find(item =>
      item.generation === generation && item.ptsSeconds <= videoPts + 0.005);
  const selected = match && videoPts - match.ptsSeconds < 1 ? match : null;
  if (selected) {
    const sx = canvas.width / selected.width, sy = canvas.height / selected.height;
    const displayWidth = canvas.clientWidth || canvas.width;
    const fontSize = Math.max(24, displayWidth/40) * canvas.width/displayWidth;
    const padding = fontSize/4, lineHeight = fontSize*1.2;
    ctx.lineWidth = Math.max(2, canvas.width/600);
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textBaseline = 'top';
    for (const box of selected.boxes) {
      const color = colorForClass(box.label);
      ctx.strokeStyle = color;
      ctx.strokeRect(box.x1*sx, box.y1*sy,
        (box.x2-box.x1)*sx, (box.y2-box.y1)*sy);
      const coordinates = Number.isFinite(box.target_lat) && Number.isFinite(box.target_lon)
        ? `${box.target_lat.toFixed(7)}, ${box.target_lon.toFixed(7)}` : '--, --';
      const textWidth = Math.max(ctx.measureText(box.label).width,
                                 ctx.measureText(coordinates).width);
      const labelWidth = Math.min(canvas.width, textWidth + padding*2);
      const labelHeight = lineHeight*2 + padding*2;
      const x = Math.max(0, Math.min(box.x1*sx, canvas.width-labelWidth));
      const above = box.y1*sy-labelHeight;
      const y = Math.max(0, Math.min(above >= 0 ? above : box.y1*sy,
                                    canvas.height-labelHeight));
      ctx.fillStyle = 'rgba(0,0,0,.65)';
      ctx.fillRect(x, y, labelWidth, labelHeight);
      ctx.fillStyle = color;
      ctx.fillText(box.label, x+padding, y+padding, labelWidth-padding*2);
      ctx.fillText(coordinates, x+padding, y+padding+lineHeight, labelWidth-padding*2);
    }
  }
  video.requestVideoFrameCallback(draw);
}
if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw);
else status.textContent = 'This browser requires requestVideoFrameCallback.';

async function connect() {
  const serial = ++connectionSerial;
  const pc = new RTCPeerConnection(iceConfiguration); peer = pc;
  lastDecodedFrames = null;
  pc.addTransceiver('video', {direction:'recvonly'});
  pc.ontrack = event => { video.srcObject = event.streams[0]; video.play().catch(()=>{}); };
  pc.onconnectionstatechange = () => {
    if (pc !== peer) return;
    status.textContent = `WebRTC ${pc.connectionState}`;
    transportStatus.textContent = `WebRTC ${pc.connectionState} | RTP waiting`;
    if (['failed','closed'].includes(pc.connectionState)) reconnect(pc.connectionState);
  };
  try {
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pc.removeEventListener('icegatheringstatechange', check);
        reject(Error('TURN ICE gathering timeout'));
      }, 10000);
      function check() {
        if (pc.iceGatheringState === 'complete') {
          clearTimeout(timer);
          pc.removeEventListener('icegatheringstatechange', check); resolve();
        }
      }
      pc.addEventListener('icegatheringstatechange', check);
      check();
    });
    if (!/a=candidate:.* typ relay/m.test(pc.localDescription.sdp)) {
      throw Error('TURN allocation failed: no relay candidate');
    }
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(),15000);
    let response;
    try { response = await fetch('/offer', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sdp:pc.localDescription.sdp, type:pc.localDescription.type,
        clientRevision:frontendRevision, reconnectReason:lastReconnectReason}),
      signal:controller.signal}); }
    finally { clearTimeout(timeout); }
    if (!response.ok) throw Error(await response.text());
    const answer = await response.json();
    if (stopped || serial !== connectionSerial || pc !== peer) return pc.close();
    await pc.setRemoteDescription({sdp:answer.sdp,type:answer.type});
    if (stopped || serial !== connectionSerial || pc !== peer) return pc.close();
    generation = answer.generation;
    peerId = answer.peerId;
    connectMetadata(pc, peerId, serial);
  } catch (error) {
    if (pc === peer) reconnect(error.message);
  }
}
setInterval(async () => {
  const pc = peer;
  if (!pc || pc.connectionState !== 'connected') return;
  try {
    const stats = await pc.getStats();
    if (pc !== peer) return;
    const inbound = [...stats.values()].find(item =>
      item.type === 'inbound-rtp' && item.kind === 'video');
    if (!video.requestVideoFrameCallback && !document.hidden &&
        Number.isFinite(inbound?.framesDecoded)) {
      const decoded = inbound.framesDecoded;
      if (decoded > (lastDecodedFrames ?? 0)) retrySeconds = 1;
      lastDecodedFrames = decoded;
    }
    transportStatus.textContent = inbound ?
      `WebRTC ${pc.connectionState} | RTP ${inbound.packetsReceived ?? 0} packets / `+
      `${inbound.framesDecoded ?? 0} decoded frames / `+
      `${inbound.keyFramesDecoded ?? 0} keyframes / ${inbound.packetsLost ?? 0} lost` :
      `WebRTC ${pc.connectionState} | RTP 0 packets / 0 decoded frames`;
  } catch (_) {}
}, 1000);
setInterval(async () => {
  const pc = peer, id = peerId, serial = connectionSerial;
  try {
    const response = await fetch('/api/health', {cache:'no-store'});
    if (!response.ok) return;
    const health = await response.json();
    if (stopped || !pc || pc !== peer || serial !== connectionSerial) return;
    if (health.rtsp?.connected === false) reconnect('RTSP reconnecting');
    else if (id && Array.isArray(health.peers) && !health.peers.some(item => item.id === id)) {
      reconnect('viewer session no longer exists');
    }
  } catch (_) {}
}, 2000);
window.addEventListener('pagehide', () => {
  stopped = true; if (retryTimer) clearTimeout(retryTimer);
  stopMetadata(); peer?.close();
});
connect();
</script></body></html>"""

HTML = HTML.replace("__UI_REVISION__", UI_REVISION)
