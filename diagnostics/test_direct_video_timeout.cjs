// Run: node --test diagnostics/test_direct_video_timeout.cjs
// Execute the actual browser script with a fake clock, video, and WebRTC peer.
// Video stalls must wait for recovery; connection failures still reconnect.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../rtsp_yolo_direct/web.py'), 'utf8');
const script = source.split('<script>')[1].split('</script>')[0].replace(/connect\(\);\s*$/, '');

async function browser({frameCallbacks = true} = {}) {
  let now = 0, frameCallback = null, nextTimerId = 1;
  let rtspConnected = true;
  const timers = new Map(), intervals = [], listeners = {}, peers = [], sockets = [];
  const drawing = new Proxy({}, {get: () => () => {}});
  const elements = new Map();
  for (const id of ['video', 'overlay', 'status', 'transport', 'capture', 'message']) {
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
  class Peer {
    constructor() {
      this.connectionState = 'new'; this.iceGatheringState = 'complete';
      this.decoded = 0; this.packets = 0; peers.push(this);
    }
    addTransceiver() {}
    async createOffer() {return {sdp: 'offer', type: 'offer'};}
    async setLocalDescription(description) {this.localDescription = description;}
    async setRemoteDescription() {
      this.connectionState = 'connected'; this.onconnectionstatechange();
      this.ontrack({streams: [{}]});
    }
    async getStats() {
      return new Map([['video', {type: 'inbound-rtp', kind: 'video',
        framesDecoded: this.decoded, packetsReceived: this.packets}]]);
    }
    close() {this.connectionState = 'closed';}
  }
  const context = vm.createContext({
    document, window: {addEventListener: () => {}},
    performance: {now: () => now}, RTCPeerConnection: Peer,
    WebSocket: class {
      constructor() {sockets.push(this);}
      close() {}
    }, AbortController,
    location: {protocol: 'http:', host: 'localhost'},
    setInterval: (fn, delay) => {intervals.push({fn, delay});},
    setTimeout: (fn, delay) => {
      const id = nextTimerId++; timers.set(id, {fn, delay}); return id;
    },
    clearTimeout: id => timers.delete(id),
    fetch: async url => ({ok: true, json: async () => url === '/offer'
      ? {sdp: 'answer', type: 'answer', generation: 1, peerId: 'test'}
      : {rtsp: {connected: rtspConnected}}}),
  });
  vm.runInContext(script, context);
  await vm.runInContext('connect()', context);
  const poll = intervals.find(item => item.delay === 1000).fn;
  const healthPoll = intervals.find(item => item.delay === 2000).fn;
  return {
    peers, sockets, timers, context, document, elements,
    pollAt: async time => {now = time; await poll();},
    healthAt: async (time, connected) => {
      now = time; rtspConnected = connected; await healthPoll();
    },
    peerState: state => {
      const pc = peers.at(-1); pc.connectionState = state; pc.onconnectionstatechange();
    },
    frameAt: time => {now = time; frameCallback(time, {rtpTimestamp: 1});},
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

test('metadata closure still reconnects and late old socket events are ignored', async () => {
  const b = await browser();
  const oldSocket = b.sockets[0];
  oldSocket.onclose();
  assert.match(b.reason(), /metadata connection closed/);
  assert.equal(b.peers[0].connectionState, 'closed');
  assert.equal(b.timers.size, 1);
  await b.retry(); oldSocket.onclose();
  assert.equal(b.peers[1].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
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
