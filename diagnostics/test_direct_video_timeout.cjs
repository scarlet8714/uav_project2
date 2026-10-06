// Run: node --test diagnostics/test_direct_video_timeout.cjs
// Execute the actual browser script with a fake clock, video, and WebRTC peer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../rtsp_yolo_direct/web.py'), 'utf8');
const script = source.split('<script>')[1].split('</script>')[0].replace(/connect\(\);\s*$/, '');

async function browser({frameCallbacks = true} = {}) {
  let now = 0, frameCallback = null, nextTimerId = 1;
  const timers = new Map(), intervals = [], listeners = {}, peers = [];
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
    WebSocket: class {close() {}}, AbortController,
    location: {protocol: 'http:', host: 'localhost'},
    setInterval: (fn, delay) => {intervals.push({fn, delay});},
    setTimeout: (fn, delay) => {
      const id = nextTimerId++; timers.set(id, {fn, delay}); return id;
    },
    clearTimeout: id => timers.delete(id),
    fetch: async url => ({ok: true, json: async () => url === '/offer'
      ? {sdp: 'answer', type: 'answer', generation: 1, peerId: 'test'}
      : {rtsp: {connected: true}}}),
  });
  vm.runInContext(script, context);
  await vm.runInContext('connect()', context);
  const poll = intervals.find(item => item.delay === 1000).fn;
  return {
    peers, timers, context, document, elements,
    pollAt: async time => {now = time; await poll();},
    frameAt: time => {now = time; frameCallback(time, {rtpTimestamp: 1});},
    visibleAt: time => {
      now = time; document.hidden = false; listeners.visibilitychange();
    },
    retry: async () => {
      const [id, timer] = [...timers][0]; timers.delete(id); timer.fn();
      // Let the real connect() finish its asynchronous negotiation.
      for (let i = 0; i < 20; i++) await Promise.resolve();
    },
    reason: () => elements.get('status').textContent,
  };
}

test('healthy RTSP with no first frame reconnects after 10 seconds', async () => {
  const b = await browser();
  await b.pollAt(9999);
  assert.equal(b.peers[0].connectionState, 'connected');
  await b.pollAt(10000);
  assert.equal(b.peers[0].connectionState, 'closed');
  assert.match(b.reason(), /first video frame timeout/);
  assert.equal(b.timers.size, 1);
});

test('frozen displayed video reconnects even when RTP and decoding keep advancing', async () => {
  const b = await browser();
  b.frameAt(1000);
  b.peers[0].packets = 10000; b.peers[0].decoded = 1000;
  await b.pollAt(5999);
  assert.equal(b.peers[0].connectionState, 'connected');
  await b.pollAt(6000);
  assert.match(b.reason(), /video stalled/);
  assert.equal(b.timers.size, 1);
});

test('regular displayed frames keep the connection alive', async () => {
  const b = await browser();
  for (let time = 1000; time <= 30000; time += 1000) {
    b.frameAt(time); await b.pollAt(time);
  }
  assert.equal(b.peers[0].connectionState, 'connected');
  assert.equal(b.timers.size, 0);
});

test('background tabs do not timeout and get a new grace period on return', async () => {
  const b = await browser();
  b.frameAt(1000); b.document.hidden = true;
  await b.pollAt(60000);
  assert.equal(b.timers.size, 0);
  b.visibleAt(60000);
  await b.pollAt(69999);
  assert.equal(b.timers.size, 0);
  await b.pollAt(70000);
  assert.match(b.reason(), /first video frame timeout/);
});

test('returning foreground video resets the grace period', async () => {
  const b = await browser();
  b.document.hidden = true; await b.pollAt(60000);
  b.visibleAt(60000); b.frameAt(61000); await b.pollAt(65000);
  assert.equal(b.timers.size, 0);
});

test('stats fallback tracks decoded frames when frame callbacks are unavailable', async () => {
  const b = await browser({frameCallbacks: false});
  b.peers[0].decoded = 1; await b.pollAt(1000);
  b.peers[0].decoded = 2; await b.pollAt(5000);
  await b.pollAt(9999);
  assert.equal(b.timers.size, 0);
  await b.pollAt(10000);
  assert.match(b.reason(), /video stalled/);
});

test('a failed stats call does not disable frame timeout', async () => {
  const b = await browser();
  b.peers[0].getStats = async () => {throw Error('stats unavailable');};
  await b.pollAt(1000);
  await b.pollAt(10000);
  assert.match(b.reason(), /first video frame timeout/);
});

test('a pending stats call does not disable the next timeout check', async () => {
  const b = await browser();
  b.peers[0].getStats = () => new Promise(() => {});
  b.pollAt(1000);
  await b.pollAt(10000);
  assert.match(b.reason(), /first video frame timeout/);
});

test('timeout schedules one retry and consecutive black screens use backoff', async () => {
  const b = await browser();
  await b.pollAt(10000); await b.pollAt(20000);
  assert.equal(b.timers.size, 1);
  assert.equal([...b.timers.values()][0].delay, 1000);
  await b.retry();
  assert.equal(b.peers.length, 2);
  await b.pollAt(30000);
  assert.equal([...b.timers.values()][0].delay, 2000);
});

test('a real frame after retry resets backoff', async () => {
  const b = await browser();
  await b.pollAt(10000); await b.retry();
  b.frameAt(11000); await b.pollAt(16000);
  assert.equal([...b.timers.values()][0].delay, 1000);
});

test('late stats results from an old peer cannot update the new connection', async () => {
  const b = await browser({frameCallbacks: false});
  let finish;
  b.peers[0].getStats = () => new Promise(resolve => {finish = resolve;});
  const oldPoll = b.pollAt(1000);
  await b.pollAt(10000); await b.retry();
  finish(new Map([['video', {type: 'inbound-rtp', kind: 'video', framesDecoded: 100}]]));
  await oldPoll;
  await b.pollAt(20000);
  assert.match(b.reason(), /first video frame timeout/);
});
