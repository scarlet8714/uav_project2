// Run: node rtsp_yolo_direct_with_gcp_and_datachannel/test_browser.cjs
// Execute the actual browser script with a fake clock, video, and WebRTC peer.
// Video stalls must wait for recovery; connection failures still reconnect.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const isTurn = true;
const source = fs.readFileSync(path.join(__dirname, 'web.py'), 'utf8');
const script = source.split('<script>')[1].split('</script>')[0]
  .replace('__TURN_ICE_CONFIGURATION__', JSON.stringify({iceServers: [
    {urls: 'turn:example.test:3478?transport=udp', username: 'test', credential: 'dummy'}
  ], iceTransportPolicy: 'relay', bundlePolicy: 'max-bundle'}))
  .replace(/connect\(\);\s*$/, '');

async function browser({frameCallbacks = true, relayCandidate = true, autoOpen = true,
                        channelConstructorFails = false} = {}) {
  let now = 0, frameCallback = null, nextTimerId = 1;
  let rtspConnected = true;
  let healthPeers = [{id: 'test'}], healthResponse = null, offerCount = 0;
  let drawCount = 0;
  const timers = new Map(), intervals = [], listeners = {}, peers = [], channels = [];
  const drawing = new Proxy({}, {get: (_, key) => key === 'measureText'
    ? text => ({width: text.length * 10}) : () => {if (key === 'strokeRect') drawCount++;}});
  const elements = new Map();
  for (const id of ['video', 'overlay', 'status', 'transport', 'metadata']) {
    elements.set(id, {textContent: '', getContext: () => drawing});
  }
  const video = elements.get('video');
  video.videoWidth = 960; video.videoHeight = 544;
  video.play = async () => {};
  if (frameCallbacks) video.requestVideoFrameCallback = fn => {frameCallback = fn;};
  const document = {
    hidden: false,
    getElementById: id => elements.get(id),
    addEventListener: (event, fn) => {listeners[event] = fn;},
  };
  class Channel {
    constructor(pc, label, options) {
      this.pc = pc; this.label = label; this.options = options;
      this.closed = false; this.readyState = 'connecting'; channels.push(this);
    }
    open() {if (!this.closed) {this.readyState = 'open'; this.onopen?.();}}
    close() {this.closed = true; this.readyState = 'closed';}
  }
  class Peer {
    constructor(configuration) {
      this.configuration = configuration;
      this.connectionState = 'new'; this.iceGatheringState = 'complete';
      this.decoded = 0; this.packets = 0; this.channels = []; peers.push(this);
    }
    addTransceiver() {}
    createDataChannel(label, options) {
      if (channelConstructorFails) throw Error('DataChannel construction failed');
      const channel = new Channel(this, label, options); this.channels.push(channel);
      if (autoOpen && this.connectionState === 'connected') Promise.resolve().then(() => channel.open());
      return channel;
    }
    async createOffer() {assert.ok(this.channels.length, 'DataChannel must precede SDP offer'); return {sdp: relayCandidate
      ? 'a=candidate:1 1 udp 1 203.0.113.1 50000 typ relay\r\n' : 'offer', type: 'offer'};}
    async setLocalDescription(description) {this.localDescription = description;}
    async setRemoteDescription() {
      this.connectionState = 'connected'; this.onconnectionstatechange();
      this.ontrack({streams: [{}]});
      if (autoOpen) for (const channel of this.channels) channel.open();
    }
    async getStats() {
      return new Map([['video', {type: 'inbound-rtp', kind: 'video',
        framesDecoded: this.decoded, packetsReceived: this.packets}]]);
    }
    close() {this.connectionState = 'closed';}
  }
  const context = vm.createContext({
    document, window: {addEventListener: (name, fn) => {listeners[name] = fn;}},
    performance: {now: () => now}, RTCPeerConnection: Peer,
    WebSocket: class {constructor() {throw Error('WebSocket must never be used');}}, AbortController,
    location: {protocol: 'http:', host: 'localhost'},
    setInterval: (fn, delay) => {intervals.push({fn, delay});},
    setTimeout: (fn, delay) => {
      const id = nextTimerId++; timers.set(id, {fn, delay}); return id;
    },
    clearTimeout: id => timers.delete(id),
    fetch: async url => {
      if (url === '/offer') {
        offerCount++;
        return {ok: true, json: async () =>
          ({sdp: 'answer', type: 'answer', generation: 1, peerId: 'test'})};
      }
      return healthResponse || {ok: true, json: async () =>
        ({rtsp: {connected: rtspConnected}, peers: healthPeers})};
    },
  });
  vm.runInContext(script, context);
  await vm.runInContext('connect()', context);
  const poll = intervals.find(item => item.delay === 1000).fn;
  const healthPoll = intervals.find(item => item.delay === 2000).fn;
  return {
    peers, channels, timers, context, document, elements,
    offerCount: () => offerCount,
    drawCount: () => drawCount,
    state: () => JSON.parse(vm.runInContext('JSON.stringify({origin, generation, detections, videoPts})', context)),
    message: (ws, data) => ws.onmessage({data: JSON.stringify(data)}),
    setAutoOpen: value => {autoOpen = value;},
    setChannelConstructorFails: value => {channelConstructorFails = value;},
    setHealthPeers: value => {healthPeers = value;},
    setHealthResponse: value => {healthResponse = value;},
    pagehide: () => listeners.pagehide(),
    pollAt: async time => {now = time; await poll();},
    healthAt: async (time, connected) => {
      now = time; rtspConnected = connected; await healthPoll();
    },
    peerState: state => {
      const pc = peers.at(-1); pc.connectionState = state; pc.onconnectionstatechange();
    },
    frameAt: (time, rtpTimestamp = 1) => {now = time; frameCallback(time, {rtpTimestamp});},
    visibleAt: time => {
      now = time; document.hidden = false; listeners.visibilitychange?.();
    },
    retry: async () => {
      const [id, timer] = [...timers][0]; timers.delete(id); timer.fn();
      // Let the real connect() finish its asynchronous negotiation.
      for (let i = 0; i < 20; i++) await Promise.resolve();
    },
    reason: () => elements.get('status').textContent,
  };
}

test('healthy RTSP with no first frame stays connected beyond 10 seconds', async () => {
  const b = await browser();
  for (const time of [9999, 10000, 60000]) {
    await b.pollAt(time); await b.healthAt(time, true);
    assert.equal(b.peers[0].connectionState, 'connected');
    assert.equal(b.timers.size, 0);
  }
  b.frameAt(61000);
  assert.equal(b.peers.length, 1);
});

test('frozen displayed video waits and resumes on the same connection', async () => {
  const b = await browser();
  b.frameAt(1000);
  b.peers[0].packets = 10000; b.peers[0].decoded = 1000;
  for (const time of [5999, 6000, 60000]) {
    await b.pollAt(time);
    assert.equal(b.peers[0].connectionState, 'connected');
    assert.equal(b.timers.size, 0);
  }
  // Even when packets and decoding stop, absence of frames alone must not reconnect.
  await b.pollAt(120000); await b.healthAt(120000, true);
  b.frameAt(121000);
  assert.equal(b.peers.length, 1);
  assert.equal(b.timers.size, 0);
  assert.match(b.elements.get('transport').textContent, /1000 decoded frames/);
});

test('regular displayed frames keep the connection alive', async () => {
  const b = await browser();
  for (let time = 1000; time <= 30000; time += 1000) {
    b.frameAt(time); await b.pollAt(time);
  }
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('background tabs and returning foreground video do not trigger reconnects', async () => {
  const b = await browser();
  b.frameAt(1000); b.document.hidden = true;
  await b.pollAt(60000);
  assert.equal(b.timers.size, 0);
  b.visibleAt(60000);
  await b.pollAt(70000); await b.pollAt(120000);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
  b.frameAt(121000);
  assert.equal(b.timers.size, 0);
});

test('stalled decoded frames do not reconnect when frame callbacks are unavailable', async () => {
  const b = await browser({frameCallbacks: false});
  b.peers[0].decoded = 1; await b.pollAt(1000);
  b.peers[0].decoded = 2; await b.pollAt(5000);
  await b.pollAt(10000); await b.pollAt(60000);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('failed stats calls do not close the connection', async () => {
  const b = await browser();
  b.peers[0].getStats = async () => {throw Error('stats unavailable');};
  await b.pollAt(1000);
  await b.pollAt(60000);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('pending stats calls do not close the connection', async () => {
  const b = await browser();
  let finish;
  b.peers[0].getStats = () => new Promise(resolve => {finish = resolve;});
  const pending = b.pollAt(1000);
  await b.healthAt(60000, true);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
  finish(new Map()); await pending;
});

test('WebRTC failures schedule one retry with 1, 2, 4, 8 second backoff', async () => {
  const b = await browser();
  for (const delay of [1000, 2000, 4000, 8000, 8000]) {
    b.peerState('failed');
    b.peers.at(-1).onconnectionstatechange();
    assert.equal(b.peers.at(-1).connectionState, 'closed');
    assert.match(b.reason(), /Reconnecting: failed/);
    assert.equal(b.timers.size, 1);
    assert.equal([...b.timers.values()][0].delay, delay);
    await b.retry();
  }
});

test('closed WebRTC connections still reconnect', async () => {
  const b = await browser();
  b.peerState('closed');
  assert.match(b.reason(), /Reconnecting: closed/);
  assert.equal(b.timers.size, 1);
});

test('metadata closure replaces only the DataChannel and preserves video timing and history', async () => {
  const b = await browser();
  const oldSocket = b.channels[0];
  b.message(oldSocket, {type: 'origin', rtpOrigin: 1000});
  b.message(oldSocket, detection(1));
  b.frameAt(1000, 91000);
  const before = b.state();
  oldSocket.onclose();
  assert.match(b.elements.get('metadata').textContent, /1 秒後重試/);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.deepEqual(b.state(), before);
  assert.equal(b.timers.size, 1);
  b.frameAt(1100, 100000);
  assert.equal(b.drawCount(), 2);
  await b.retry();
  assert.equal(b.channels.length, 2);
  assert.equal(b.channels[1].label, 'metadata');
  assert.equal(b.channels[1].pc, oldSocket.pc);
  assert.equal(b.peers.length, 1);
  assert.equal(b.offerCount(), 1);
  oldSocket.onclose(); oldSocket.onopen();
  b.message(oldSocket, {type: 'origin', rtpOrigin: 9999});
  b.message(oldSocket, detection(99));
  assert.equal(b.state().origin, 1000);
  assert.equal(b.state().detections.length, 1);
  assert.equal(b.timers.size, 0);
  b.message(b.channels[1], detection(1.2));
  b.frameAt(1200, 109000);
  assert.equal(b.drawCount(), 3);
  assert.match(b.elements.get('metadata').textContent, /已連線/);
});

function detection(ptsSeconds, generation = 1) {
  return {type: 'detection', generation, ptsSeconds, width: 960, height: 544,
    boxes: [{label: 'car', x1: 10, y1: 10, x2: 50, y2: 50}]};
}

test('metadata retries use independent 1, 2, 4, 8 second backoff without video offers', async () => {
  const b = await browser();
  b.setAutoOpen(false);
  for (const delay of [1000, 2000, 4000, 8000, 8000]) {
    const ws = b.channels.at(-1);
    ws.onerror(); ws.onclose();
    assert.equal(b.timers.size, 1);
    assert.equal([...b.timers.values()][0].delay, delay);
    await b.retry();
    assert.equal(b.peers.length, 1);
    assert.equal(b.peers[0].connectionState, 'connected');
  }
  b.channels.at(-1).onopen(); b.channels.at(-1).onclose();
  assert.equal([...b.timers.values()][0].delay, 1000);
  assert.equal(b.offerCount(), 1);
});

test('hung metadata handshake retries after 10 seconds without closing video', async () => {
  const b = await browser({autoOpen: false});
  assert.equal([...b.timers.values()][0].delay, 10000);
  await b.retry();
  assert.equal(b.channels[0].closed, true);
  assert.equal([...b.timers.values()][0].delay, 1000);
  assert.equal(b.peers[0].connectionState, 'connected');
});

test('DataChannel replacement errors retry on the same video peer', async () => {
  const b = await browser();
  b.setChannelConstructorFails(true);
  b.channels[0].onclose();
  await b.retry();
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.channels.length, 1);
  assert.equal([...b.timers.values()][0].delay, 2000);
  assert.equal(b.offerCount(), 1);
});

test('initial DataChannel creation failure retries negotiation before sending an offer', async () => {
  const b = await browser({channelConstructorFails: true});
  assert.equal(b.peers[0].connectionState, 'closed');
  assert.equal(b.channels.length, 0);
  assert.equal(b.offerCount(), 0);
  assert.equal([...b.timers.values()][0].delay, 1000);
});

test('metadata outage hides expired boxes while new frames continue on the same peer', async () => {
  const b = await browser();
  b.message(b.channels[0], {type: 'origin', rtpOrigin: 1000});
  b.message(b.channels[0], detection(1));
  b.frameAt(1000, 91000);
  assert.equal(b.drawCount(), 1);
  b.channels[0].onclose();
  b.frameAt(2100, 190000);
  assert.equal(b.drawCount(), 1);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.state().detections.length, 1);
});

test('video failure cancels metadata retries and ignores late old messages', async () => {
  const b = await browser();
  const oldSocket = b.channels[0];
  oldSocket.onclose();
  b.peerState('failed');
  assert.equal(b.timers.size, 1);
  await b.retry();
  assert.equal(b.peers.length, 2);
  oldSocket.onclose(); oldSocket.onerror();
  b.message(oldSocket, {type: 'origin', rtpOrigin: 1000});
  b.message(oldSocket, detection(10));
  assert.equal(b.state().origin, null);
  assert.deepEqual(b.state().detections, []);
  assert.equal(b.timers.size, 0);
});

test('leaving the page cancels metadata and video retries and ignores late channel events', async () => {
  for (const autoOpen of [true, false]) {
    const b = await browser({autoOpen});
    if (autoOpen) b.channels[0].onclose();
    const lateTimer = [...b.timers.values()][0].fn;
    b.pagehide();
    assert.equal(b.timers.size, 0);
    lateTimer();
    b.channels[0].onclose(); b.channels[0].onopen();
    assert.equal(b.channels.length, 1);
    assert.equal(b.timers.size, 0);
    assert.equal(b.peers[0].connectionState, 'closed');
  }
});

test('confirmed missing backend peer rebuilds video after a server restart', async () => {
  const b = await browser();
  b.channels[0].onclose();
  b.setHealthPeers([]);
  await b.healthAt(2000, true);
  assert.match(b.reason(), /viewer session no longer exists/);
  assert.equal(b.peers[0].connectionState, 'closed');
  assert.equal(b.timers.size, 1);
  await b.retry();
  assert.equal(b.offerCount(), 2);
});

test('health request failures and unknown peer lists do not rebuild video', async () => {
  const b = await browser();
  b.setHealthResponse({ok: false});
  await b.healthAt(2000, true);
  b.setHealthResponse(null); b.setHealthPeers(undefined);
  await b.healthAt(4000, true);
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('late health results from an old peer cannot close the new video peer', async () => {
  const b = await browser();
  let finish;
  b.setHealthResponse({ok: true, json: () => new Promise(resolve => {finish = resolve;})});
  const pending = b.healthAt(1000, true);
  for (let i = 0; i < 5; i++) await Promise.resolve();
  b.peerState('failed'); await b.retry();
  finish({rtsp: {connected: true}, peers: []}); await pending;
  assert.equal(b.peers[1].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('invalid metadata and other generations do not corrupt video timing or overlays', async () => {
  const b = await browser();
  b.message(b.channels[0], {type: 'origin', rtpOrigin: 1000});
  b.channels[0].onmessage({data: 'invalid json'});
  b.message(b.channels[0], null);
  b.message(b.channels[0], {type: 'origin', rtpOrigin: 'not a timestamp'});
  b.message(b.channels[0], detection(1, 2));
  assert.equal(b.state().origin, 1000);
  assert.deepEqual(b.state().detections, []);
  assert.equal(b.peers[0].connectionState, 'connected');
});

test('unhealthy RTSP still reconnects without waiting for a video timeout', async () => {
  const b = await browser();
  await b.healthAt(2000, false);
  assert.match(b.reason(), /RTSP reconnecting/);
  assert.equal(b.peers[0].connectionState, 'closed');
  assert.equal(b.timers.size, 1);
});

test('a real frame after retry resets backoff', async () => {
  const b = await browser();
  b.peerState('failed'); await b.retry();
  b.peerState('failed'); await b.retry();
  b.frameAt(11000); b.peerState('failed');
  assert.equal([...b.timers.values()][0].delay, 1000);
});

test('decoded frame progress after retry resets backoff without frame callbacks', async () => {
  const b = await browser({frameCallbacks: false});
  b.peerState('failed'); await b.retry();
  b.peers[1].decoded = 1; await b.pollAt(1000);
  b.peerState('failed');
  assert.equal([...b.timers.values()][0].delay, 1000);
});

test('late stats results from an old peer cannot update the new connection', async () => {
  const b = await browser({frameCallbacks: false});
  let finish;
  b.peers[0].getStats = () => new Promise(resolve => {finish = resolve;});
  const oldPoll = b.pollAt(1000);
  b.peerState('failed'); await b.retry();
  finish(new Map([['video', {type: 'inbound-rtp', kind: 'video', framesDecoded: 100}]]));
  await oldPoll;
  assert.doesNotMatch(b.elements.get('transport').textContent, /100 decoded frames/);
  b.peers[1].decoded = 1; await b.pollAt(20000);
  assert.match(b.elements.get('transport').textContent, /1 decoded frames/);
  b.peerState('failed');
  assert.equal([...b.timers.values()][0].delay, 1000);
});

if (isTurn) {
  test('browser offers relay-only ICE with the configured TURN credentials', async () => {
    const b = await browser();
    const config = b.peers[0].configuration;
    assert.equal(config.iceTransportPolicy, 'relay');
    assert.equal(config.iceServers.length, 1);
    assert.equal(config.iceServers[0].urls, 'turn:example.test:3478?transport=udp');
    assert.equal(config.iceServers[0].credential, 'dummy');
  });
  test('missing TURN candidates fail clearly and retry instead of connecting directly', async () => {
    const b = await browser({relayCandidate: false});
    assert.equal(b.peers[0].connectionState, 'closed');
    assert.equal(b.channels.length, 1);
    assert.equal(b.channels[0].closed, true);
    assert.match(b.reason(), /TURN allocation failed/);
    assert.equal(b.timers.size, 1);
  });
}

test('metadata uses a reliable ordered channel bundled with video', async () => {
  const b = await browser();
  const channel = b.channels[0];
  assert.equal(channel.label, 'metadata');
  assert.equal(channel.options.ordered, true);
  assert.equal(channel.options.protocol, 'uav-metadata-v1');
  assert.equal(channel.pc, b.peers[0]);
  assert.equal(b.peers[0].configuration.bundlePolicy, 'max-bundle');
  assert.equal(b.peers[0].configuration.iceTransportPolicy, 'relay');
});

test('malformed detections are ignored and history remains capped at 180 results', async () => {
  const b = await browser();
  const channel = b.channels[0];
  for (const data of [{...detection(1), boxes: null}, {...detection(1), width: 0},
                      {...detection(1), ptsSeconds: 'invalid'}]) b.message(channel, data);
  assert.equal(b.state().detections.length, 0);
  for (let i = 0; i < 190; i++) b.message(channel, detection(i));
  assert.equal(b.state().detections.length, 180);
  assert.equal(b.state().detections[0].ptsSeconds, 10);
});
