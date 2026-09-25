"""Receive RTSP once and split H.264 packets from Jetson-decoded frames."""

import asyncio
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import threading
import time

import av
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
import numpy as np

from .codec import profile_from_sps, register_profile


def load_gst():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    for name in ("appsrc", "h264parse", "nvv4l2decoder", "nvvidconv", "appsink"):
        if Gst.ElementFactory.find(name) is None:
            raise RuntimeError(f"Missing GStreamer element {name}")
    return Gst


@dataclass
class DecodedFrame:
    image: np.ndarray
    pts90k: int
    receive_mono_ns: int
    generation: int


class EncodedTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.queue = asyncio.Queue(maxsize=120)
        self.wait_keyframe = True
        self.last_pts = None
        self.playout_origin = None
        source.tracks.add(self)

    def feed(self, packet):
        if self.readyState != "live":
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            self.wait_keyframe = True
            self.playout_origin = None
            self.source.on_event("video_queue_overflow")
        if self.wait_keyframe:
            if not packet.is_keyframe:
                return
            self.wait_keyframe = False
        self.queue.put_nowait(packet)

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        packet = await self.queue.get()
        if packet is None:
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        pts_seconds = int(packet.pts) / 90000
        if self.playout_origin is None:
            self.playout_origin = (loop.time() +
                                   self.source.config.playout_delay_ms / 1000 -
                                   pts_seconds)
        wait = self.playout_origin + pts_seconds - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_pts = int(packet.pts)
        return packet

    def stop(self):
        if self.readyState == "ended":
            return
        super().stop()
        self.source.tracks.discard(self)
        while self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(None)


class RtspSource:
    def __init__(self, config, loop, on_frame, on_event):
        self.config = config
        self.loop = loop
        self.on_frame = on_frame
        self.on_event = on_event
        self.Gst = load_gst()
        self.tracks = set()
        self.running = True
        self.ready = False
        self.profile_id = None
        self.generation = 0
        self.packets = 0
        self.reconnects = 0
        self.last_packet_at = None
        self.error = None
        self._container = None
        self._pipeline = None
        self._arrival_lock = threading.Lock()
        self._arrival_times = deque(maxlen=512)
        self.thread = threading.Thread(target=self._run, name="rtsp-direct-input",
                                       daemon=True)
        self.thread.start()

    def new_track(self):
        if not self.ready:
            raise RuntimeError("RTSP source is reconnecting")
        return EncodedTrack(self)

    def _emit_tracks(self, packet):
        for track in tuple(self.tracks):
            track.feed(packet)

    def _end_tracks(self):
        for track in tuple(self.tracks):
            track.stop()

    def _arrival_for_pts(self, pts):
        with self._arrival_lock:
            for candidate_pts, received_ns in reversed(self._arrival_times):
                if candidate_pts <= pts:
                    return received_ns
        return time.monotonic_ns()

    def _decoder_loop(self, sink, generation, stop):
        Gst = self.Gst
        while not stop.is_set():
            sample = sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                continue
            buffer = sample.get_buffer()
            if buffer.pts == Gst.CLOCK_TIME_NONE:
                continue
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value("width"), caps.get_value("height")
            mapped, info = buffer.map(Gst.MapFlags.READ)
            if not mapped:
                continue
            try:
                stride = info.size // height
                image = np.ndarray((height, width, 4), dtype=np.uint8,
                                   buffer=info.data, strides=(stride, 4, 1))
                bgr = image[:, :, :3].copy()
            finally:
                buffer.unmap(info)
            pts = int(buffer.pts * 90000 // Gst.SECOND)
            self.on_frame(DecodedFrame(bgr, pts, self._arrival_for_pts(pts),
                                       generation))

    def _send_packet(self, packet, base, appsrc, received_ns=None):
        if received_ns is None:
            received_ns = time.monotonic_ns()
        pts = max(0, int((packet.pts - base) * packet.time_base * 90000))
        packet.pts = pts
        packet.time_base = Fraction(1, 90000)
        with self._arrival_lock:
            self._arrival_times.append((pts, received_ns))
        data = bytes(packet)
        buffer = self.Gst.Buffer.new_allocate(None, len(data), None)
        buffer.fill(0, data)
        buffer.pts = pts * self.Gst.SECOND // 90000
        result = appsrc.emit("push-buffer", buffer)
        if result != self.Gst.FlowReturn.OK:
            raise RuntimeError(f"Jetson decoder rejected H.264 packet: {result.value_nick}")
        self.packets += 1
        self.last_packet_at = time.monotonic()
        self.loop.call_soon_threadsafe(self._emit_tracks, packet)

    def _run_once(self):
        Gst = self.Gst
        container = av.open(self.config.rtsp_url, format="rtsp",
                            options={"rtsp_transport": self.config.transport},
                            timeout=self.config.rtsp_timeout)
        self._container = container
        stream = container.streams.video[0]
        if stream.codec_context.name != "h264":
            raise RuntimeError("RTSP source must supply H.264")
        self.profile_id = profile_from_sps(stream.codec_context.extradata)
        register_profile(self.profile_id)
        # Wait for actual media before opening a decoder. Some cameras continue
        # answering RTSP DESCRIBE while temporarily sending no RTP packets.
        iterator = iter(container.demux(stream))
        first = next(iterator)
        while not first.size:
            first = next(iterator)
        first_received_ns = time.monotonic_ns()
        pending = [(first, first_received_ns)]
        if first.pts is None:
            following = next(iterator)
            while not following.size or following.pts is None:
                following = next(iterator)
            following_received_ns = time.monotonic_ns()
            step = int(Fraction(1, stream.average_rate or 30) / stream.time_base)
            base = following.pts - step
            first.pts = base
            pending.append((following, following_received_ns))
        else:
            base = first.pts
        pipeline = Gst.parse_launch(
            "appsrc name=source is-live=true block=false format=time "
            "caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
            "h264parse ! nvv4l2decoder ! nvvidconv ! "
            "video/x-raw,format=BGRx ! "
            "appsink name=sink max-buffers=1 drop=true sync=false")
        self._pipeline = pipeline
        appsrc, sink = pipeline.get_by_name("source"), pipeline.get_by_name("sink")
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Cannot start Jetson H.264 decoder")
        self.generation += 1
        generation = self.generation
        decoder_stop = threading.Event()
        decoder_thread = threading.Thread(
            target=self._decoder_loop, args=(sink, generation, decoder_stop),
            name="jetson-h264-decoder", daemon=True)
        decoder_thread.start()
        self.ready = True
        self.error = None
        self.on_event("rtsp_connected", generation=generation,
                      profile_id=self.profile_id)
        try:
            for packet, received_ns in pending:
                self._send_packet(packet, base, appsrc, received_ns)
            for packet in iterator:
                if not self.running:
                    break
                if packet.size and packet.pts is not None:
                    self._send_packet(packet, base, appsrc)
            if self.running:
                raise RuntimeError("RTSP stream ended")
        finally:
            self.ready = False
            self.loop.call_soon_threadsafe(self._end_tracks)
            decoder_stop.set()
            pipeline.set_state(Gst.State.NULL)
            decoder_thread.join(timeout=2)
            container.close()
            self._pipeline = None
            self._container = None
            with self._arrival_lock:
                self._arrival_times.clear()

    def _run(self):
        while self.running:
            try:
                self._run_once()
            except Exception as exc:
                if self.running:
                    self.ready = False
                    self.error = repr(exc)
                    self.reconnects += 1
                    self.on_event("rtsp_error", error=self.error,
                                  reconnects=self.reconnects)
                    self.loop.call_soon_threadsafe(self._end_tracks)
                    if self._pipeline is not None:
                        self._pipeline.set_state(self.Gst.State.NULL)
                        self._pipeline = None
                    if self._container is not None:
                        self._container.close()
                        self._container = None
            if self.running:
                time.sleep(1)

    def status(self):
        age = None if self.last_packet_at is None else time.monotonic() - self.last_packet_at
        return {"connected": self.ready and age is not None and age < self.config.rtsp_timeout,
                "transport": self.config.transport, "profile_id": self.profile_id,
                "generation": self.generation, "packets": self.packets,
                "last_packet_age_s": None if age is None else round(age, 3),
                "reconnects": self.reconnects, "error": self.error}

    def close(self):
        self.running = False
        if self._pipeline is not None:
            self._pipeline.send_event(self.Gst.Event.new_eos())
        self.thread.join(timeout=self.config.rtsp_timeout + 3)
        if self.thread.is_alive():
            self.on_event("rtsp_stop_timeout")
