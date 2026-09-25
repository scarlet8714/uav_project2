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
let detections = [], videoPts = null, lastFrameAt = 0, videoFps = null;
let retrySeconds = 1, retryTimer = null, connectionSerial = 0, stopped = false;

function reconnect(reason) {
  if (stopped || retryTimer) return;
  status.textContent = `Reconnecting: ${reason}`;
  socket?.close(); socket = null;
  peer?.close(); peer = null;
  origin = null; generation = null; detections = []; videoPts = null;
  videoFps = null; lastFrameAt = 0;
  transportStatus.textContent = 'RTP waiting';
  const delay = retrySeconds * 1000;
  retrySeconds = Math.min(retrySeconds * 2, 8);
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, delay);
}

function draw(now, frame) {
  const frameAt = performance.now();
  if (lastFrameAt && frameAt > lastFrameAt) {
    const fps = 1000 / (frameAt-lastFrameAt);
    videoFps = videoFps === null ? fps : videoFps*0.8+fps*0.2;
  }
  lastFrameAt = frameAt;
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
    ctx.lineWidth = Math.max(2, canvas.width/600);
    ctx.font = `${Math.max(14, canvas.width/67)}px sans-serif`;
    for (const box of selected.boxes) {
      ctx.strokeStyle = box.confirmed ? '#00ff66' : '#ffdc4a';
      ctx.fillStyle = ctx.strokeStyle;
      ctx.strokeRect(box.x1*sx, box.y1*sy,
        (box.x2-box.x1)*sx, (box.y2-box.y1)*sy);
      let label = `${box.label} ${box.confidence.toFixed(2)} @ ${selected.ptsSeconds.toFixed(3)}s`;
      if (!box.confirmed) label += ` confirm ${box.confirm_count}/3`;
      if (box.target_lat !== undefined)
        label += `  ${box.target_lat.toFixed(7)}, ${box.target_lon.toFixed(7)}`;
      ctx.fillText(label, box.x1*sx+3, Math.max(18, box.y1*sy-5));
    }
  }
  ctx.fillStyle = 'rgba(0,0,0,.72)';
  ctx.fillRect(0, 0, Math.min(canvas.width, 830), 82);
  ctx.fillStyle = '#fff'; ctx.font = '18px monospace';
  const v = videoPts === null ? '--' : videoPts.toFixed(3)+' s';
  const y = selected ? selected.ptsSeconds.toFixed(3)+' s' : '--';
  const gap = selected ? ((videoPts-selected.ptsSeconds)*1000).toFixed(0)+' ms' : '--';
  const gps = selected ? `${selected.gpsStatus} / age ${selected.gpsAgeMs ?? '--'} ms` : '--';
  ctx.fillText(`Video PTS ${v}   YOLO PTS ${y}   gap ${gap}`, 10, 26);
  const fpsText = `video ${videoFps?.toFixed(1) ?? '--'} fps / YOLO ${selected?.yoloFps?.toFixed(1) ?? '--'} fps`;
  ctx.fillText(`GPS ${gps}   ${fpsText}`, 10, 53);
  status.textContent = `WebRTC ${peer?.connectionState ?? 'disconnected'}`+
    ` | RTSP source time ${v} | YOLO ${y} | gap ${gap} | GPS ${gps}`;
  video.requestVideoFrameCallback(draw);
}
if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw);
else status.textContent = 'This browser requires requestVideoFrameCallback.';

async function connect() {
  const serial = ++connectionSerial;
  const pc = new RTCPeerConnection(); peer = pc;
  pc.addTransceiver('video', {direction:'recvonly'});
  pc.ontrack = event => { video.srcObject = event.streams[0]; video.play().catch(()=>{}); };
  pc.onconnectionstatechange = () => {
    if (pc !== peer) return;
    transportStatus.textContent = `WebRTC ${pc.connectionState} | RTP waiting`;
    if (pc.connectionState === 'connected') retrySeconds = 1;
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
  try {
    const stats = await pc.getStats();
    if (pc !== peer) return;
    const inbound = [...stats.values()].find(item =>
      item.type === 'inbound-rtp' && item.kind === 'video');
    transportStatus.textContent = inbound ?
      `WebRTC ${pc.connectionState} | RTP ${inbound.packetsReceived ?? 0} packets / `+
      `${inbound.framesDecoded ?? 0} decoded frames / `+
      `${inbound.keyFramesDecoded ?? 0} keyframes / ${inbound.packetsLost ?? 0} lost` :
      `WebRTC ${pc.connectionState} | RTP 0 packets / 0 decoded frames`;
  } catch (_) {}
}, 1000);
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
