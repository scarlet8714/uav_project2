"""Browser UI: direct video, time-matched Canvas boxes, and reconnect."""

HTML = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTSP YOLO GPS direct WebRTC</title>
<style>
body{margin:0;background:#17191b;color:#eee;font-family:sans-serif}
main{width:min(96%,1280px);margin:18px auto}
h1{font-size:1.35rem}
#stage{position:relative;width:100%;background:#000}
video{display:block;width:100%;background:#000}
canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
#status{white-space:pre-wrap;font-family:monospace;line-height:1.5}
button{padding:8px 12px;cursor:pointer}
#message{margin-left:12px}
</style></head><body><main>
<h1>RTSP 直傳 + YOLO / GPS</h1>
<div id="stage"><video id="video" autoplay playsinline muted></video>
<canvas id="overlay"></canvas></div>
<pre id="status">Connecting…</pre>
<pre id="transport">RTP waiting</pre>
<button id="capture">立即儲存 5 張</button><span id="message"></span>
<p>RTSP 來源不提供本機曝光、增益及對焦控制。<a href="/api/health">健康狀態</a></p>
</main><script>
const video = document.getElementById('video');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const status = document.getElementById('status');
const transportStatus = document.getElementById('transport');
let peer = null, socket = null, origin = null, generation = null;
let detections = [], videoPts = null;
let retrySeconds = 1, retryTimer = null, connectionSerial = 0, stopped = false;
const FIRST_FRAME_TIMEOUT_MS = 10000, VIDEO_STALL_TIMEOUT_MS = 5000;
let videoConnectedAt = null, lastVideoProgressAt = null, lastDecodedFrames = null;
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

function resetVideoWatchdog() {
  videoConnectedAt = null; lastVideoProgressAt = null; lastDecodedFrames = null;
}

function noteVideoProgress(now) {
  lastVideoProgressAt = now;
  retrySeconds = 1;
}

function checkVideoTimeout(pc) {
  // Background tabs may stop presenting frames; resume with a fresh grace period.
  if (stopped || document.hidden || pc !== peer || pc.connectionState !== 'connected') return false;
  const now = performance.now();
  if (videoConnectedAt === null) videoConnectedAt = now;
  const waiting = lastVideoProgressAt === null;
  const age = now - (lastVideoProgressAt ?? videoConnectedAt);
  const limit = waiting ? FIRST_FRAME_TIMEOUT_MS : VIDEO_STALL_TIMEOUT_MS;
  if (age < limit) return false;
  reconnect(`${waiting ? 'first video frame timeout' : 'video stalled'} (${(age/1000).toFixed(1)} s)`);
  return true;
}

function reconnect(reason) {
  if (stopped || retryTimer) return;
  status.textContent = `Reconnecting: ${reason}`;
  socket?.close(); socket = null;
  peer?.close(); peer = null;
  origin = null; generation = null; detections = []; videoPts = null;
  resetVideoWatchdog();
  transportStatus.textContent = 'RTP waiting';
  const delay = retrySeconds * 1000;
  retrySeconds = Math.min(retrySeconds * 2, 8);
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, delay);
}

function draw(now, frame) {
  const frameAt = performance.now();
  if (peer?.connectionState === 'connected') noteVideoProgress(frameAt);
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
  const pc = new RTCPeerConnection(); peer = pc;
  resetVideoWatchdog();
  pc.addTransceiver('video', {direction:'recvonly'});
  pc.ontrack = event => { video.srcObject = event.streams[0]; video.play().catch(()=>{}); };
  pc.onconnectionstatechange = () => {
    if (pc !== peer) return;
    status.textContent = `WebRTC ${pc.connectionState}`;
    transportStatus.textContent = `WebRTC ${pc.connectionState} | RTP waiting`;
    if (pc.connectionState === 'connected' && videoConnectedAt === null)
      videoConnectedAt = performance.now();
    if (['failed','closed'].includes(pc.connectionState)) reconnect(pc.connectionState);
  };
  try {
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') await Promise.race([
      new Promise(resolve => pc.addEventListener('icegatheringstatechange', function check() {
        if (pc.iceGatheringState === 'complete') {
          pc.removeEventListener('icegatheringstatechange', check); resolve();
        }
      })),
      new Promise((_, reject) => setTimeout(()=>reject(Error('ICE gathering timeout')),10000))
    ]);
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(),15000);
    let response;
    try { response = await fetch('/offer', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(pc.localDescription), signal:controller.signal}); }
    finally { clearTimeout(timeout); }
    if (!response.ok) throw Error(await response.text());
    const answer = await response.json();
    if (serial !== connectionSerial || pc !== peer) return pc.close();
    await pc.setRemoteDescription({sdp:answer.sdp,type:answer.type});
    generation = answer.generation;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//`+
      `${location.host}/events/${answer.peerId}`);
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === 'origin') origin = data.rtpOrigin >>> 0;
      if (data.type === 'detection' && data.generation === generation) {
        detections.push(data);
        if (detections.length > 180) detections.shift();
      }
    };
    socket.onclose = () => { if (pc === peer) reconnect('metadata connection closed'); };
  } catch (error) {
    if (pc === peer) reconnect(error.message);
  }
}
setInterval(async () => {
  const pc = peer;
  if (!pc || pc.connectionState !== 'connected') return;
  // Run before getStats so a slow stats request cannot disable the timeout.
  if (checkVideoTimeout(pc)) return;
  try {
    const stats = await pc.getStats();
    if (pc !== peer) return;
    const inbound = [...stats.values()].find(item =>
      item.type === 'inbound-rtp' && item.kind === 'video');
    if (!video.requestVideoFrameCallback && !document.hidden &&
        Number.isFinite(inbound?.framesDecoded)) {
      const decoded = inbound.framesDecoded;
      if (decoded > (lastDecodedFrames ?? 0)) noteVideoProgress(performance.now());
      lastDecodedFrames = decoded;
    }
    transportStatus.textContent = inbound ?
      `WebRTC ${pc.connectionState} | RTP ${inbound.packetsReceived ?? 0} packets / `+
      `${inbound.framesDecoded ?? 0} decoded frames / `+
      `${inbound.keyFramesDecoded ?? 0} keyframes / ${inbound.packetsLost ?? 0} lost` :
      `WebRTC ${pc.connectionState} | RTP 0 packets / 0 decoded frames`;
  } catch (_) {}
}, 1000);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  resetVideoWatchdog();
  if (peer?.connectionState === 'connected') videoConnectedAt = performance.now();
});
setInterval(async () => {
  try {
    const response = await fetch('/api/health', {cache:'no-store'});
    const health = await response.json();
    if (!health.rtsp.connected && peer) reconnect('RTSP reconnecting');
  } catch (_) {}
}, 2000);
document.getElementById('capture').onclick = async () => {
  const message = document.getElementById('message');
  try {
    const response = await fetch('/api/capture', {method:'POST'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    message.textContent = data.message;
  } catch (error) { message.textContent = error.message; }
};
window.addEventListener('pagehide', () => {
  stopped = true; if (retryTimer) clearTimeout(retryTimer);
  socket?.close(); peer?.close();
});
connect();
</script></body></html>"""
