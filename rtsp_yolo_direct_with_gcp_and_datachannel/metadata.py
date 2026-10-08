"""Bounded YOLO/GPS delivery over a peer's reliable, ordered DataChannel."""

import json

LABEL = "metadata"
PROTOCOL = "uav-metadata-v1"
MAX_BUFFERED_BYTES = 64 * 1024
MAX_MESSAGE_BYTES = 60 * 1024


class MetadataSender:
    def __init__(self, app, peer_id, peer):
        self.app, self.peer_id, self.peer = app, peer_id, peer
        self.channel = None
        self.pending = None
        self.origin_pending = False
        self.stopped = False
        self.opened = False
        self.sent_messages = 0
        self.dropped_detections = 0
        self.last_error = None

    def active(self):
        return (not self.stopped and not self.peer.get("closing")
                and self.app["peers"].get(self.peer_id) is self.peer)

    def log(self, kind, **fields):
        self.app["log"].write(kind, peer_id=self.peer_id,
                              connection_state=self.peer["pc"].connectionState, **fields)

    def attach(self, channel):
        if (not self.active() or channel.label != LABEL or channel.protocol != PROTOCOL
                or not channel.ordered or channel.maxRetransmits is not None
                or channel.maxPacketLifeTime is not None):
            channel.close()
            return
        old = self.channel
        self.channel = channel
        self.opened = False
        self.origin_pending = self.peer["origin"] is not None
        # A zero threshold always wakes us when a message near the size limit
        # can fit, even if the last queued message drains with no new detection.
        channel.bufferedAmountLowThreshold = 0

        def current():
            return self.active() and self.channel is channel

        @channel.on("open")
        def on_open():
            if not current() or self.opened:
                return
            self.opened = True
            self.log("metadata_connected", transport="webrtc-datachannel")
            self.flush()

        @channel.on("close")
        def on_close():
            if not current():
                return
            self.channel = None
            self.opened = False
            self.pending = None
            self.log("metadata_disconnected", transport="webrtc-datachannel")

        @channel.on("bufferedamountlow")
        def on_buffered_amount_low():
            if current():
                self.flush()

        if old is not None:
            old.close()
        # aiortc emits the remote "datachannel" event after setting it open.
        if channel.readyState == "open":
            on_open()

    def publish(self, message):
        if not self.active() or message.get("generation") != self.peer["generation"]:
            return
        if self.pending is not None:
            self.dropped_detections += 1
        self.pending = message
        self.flush()

    def origin_available(self):
        self.origin_pending = True
        self.flush()

    def send(self, message):
        channel = self.channel
        if channel is None or channel.readyState != "open":
            return False
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        size = len(payload.encode("utf-8"))
        if size > MAX_MESSAGE_BYTES:
            self.dropped_detections += 1
            self.log("metadata_message_too_large", size_bytes=size)
            return True  # Consume this result; it cannot fit in one message.
        if channel.bufferedAmount + size > MAX_BUFFERED_BYTES:
            return False
        try:
            channel.send(payload)
        except Exception as error:
            self.last_error = repr(error)
            self.log("metadata_send_error", error=self.last_error)
            # Closing a data channel lets the browser replace it on the same
            # SCTP association, without touching the RTP/video peer.
            channel.close()
            return False
        self.sent_messages += 1
        return True

    def flush(self):
        if not self.active() or self.channel is None or self.channel.readyState != "open":
            return
        if self.origin_pending and self.peer["origin"] is not None:
            if not self.send({"type": "origin", "rtpOrigin": self.peer["origin"]}):
                return
            self.origin_pending = False
        if self.pending is not None and self.send(self.pending):
            self.pending = None

    def snapshot(self):
        channel = self.channel
        return {"transport": "webrtc-datachannel",
                "state": "closed" if channel is None else channel.readyState,
                "connected": channel is not None and channel.readyState == "open",
                "buffered_amount": 0 if channel is None else channel.bufferedAmount,
                "pending_results": int(self.pending is not None),
                "sent_messages": self.sent_messages,
                "dropped_detections": self.dropped_detections,
                "last_error": self.last_error}

    def stop(self):
        self.stopped = True
        old, self.channel = self.channel, None
        self.pending = None
        self.opened = False
        if old is not None:
            old.close()
