"""Test RTSP H.264 -> WebRTC without decoding or re-encoding video.

Run: python rtsp_direct_stream.py --rtsp-url rtsp://192.168.144.135/live
Open http://<server-ip>:8081/ in a browser. The camera must supply H.264.
"""

import argparse
import asyncio

from aiohttp import web
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from aiortc import sdp
from aiortc.codecs import CODECS
from aiortc.contrib.media import MediaPlayer
from aiortc.exceptions import OperationError
from aiortc.rtcrtpparameters import RTCRtpCodecParameters


HTML = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTSP H.264 direct WebRTC test</title>
<style>body{background:#111;color:#eee;font-family:sans-serif;text-align:center}
video{width:min(100%,1280px);background:#000}</style></head>
<body><h2>RTSP H.264 direct WebRTC test</h2>
<p id="status">Connecting…</p><video id="video" autoplay playsinline muted controls></video>
<script>
const status = document.getElementById('status');
const pc = new RTCPeerConnection();
pc.addTransceiver('video', {direction: 'recvonly'});
pc.ontrack = e => { document.getElementById('video').srcObject = e.streams[0]; };
pc.onconnectionstatechange = () => { status.textContent = 'WebRTC: ' + pc.connectionState; };
async function start() {
  await pc.setLocalDescription(await pc.createOffer());
  if (pc.iceGatheringState !== 'complete') await new Promise(resolve => {
    pc.addEventListener('icegatheringstatechange', function check() {
      if (pc.iceGatheringState === 'complete') {
        pc.removeEventListener('icegatheringstatechange', check); resolve();
      }
    });
  });
  const response = await fetch('/offer', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(pc.localDescription)});
  if (!response.ok) throw new Error(await response.text());
  await pc.setRemoteDescription(await response.json());
}
start().catch(e => { console.error(e); status.textContent = 'Error: ' + e.message; });
window.addEventListener('beforeunload', () => pc.close());
</script></body></html>"""


def h264_codecs(profile_id):
    profile = sdp.parse_h264_profile_level_id(profile_id)[0]
    codecs = [codec for codec in RTCRtpSender.getCapabilities("video").codecs
              if codec.mimeType.lower() == "video/h264"
              and sdp.parse_h264_profile_level_id(
                  codec.parameters["profile-level-id"])[0] == profile]
    if not codecs:
        raise RuntimeError(f"aiortc has no H.264 sender codec for {profile_id}")
    return codecs


def source_profile_id(extradata):
    # FFmpeg's RTSP demuxer exposes SPS in Annex-B form.
    marker = b"\x00\x00\x00\x01\x67"
    position = extradata.find(marker)
    if position < 0 or len(extradata) < position + 8:
        raise RuntimeError("Cannot read H.264 SPS profile from RTSP source")
    return extradata[position + 5:position + 8].hex()


def register_source_codec(profile_id):
    profile = sdp.parse_h264_profile_level_id(profile_id)[0]
    if any(codec.mimeType.lower() == "video/h264" and
           sdp.parse_h264_profile_level_id(
               codec.parameters["profile-level-id"])[0] == profile
           for codec in CODECS["video"] if "profile-level-id" in codec.parameters):
        return
    CODECS["video"].append(RTCRtpCodecParameters(
        mimeType="video/H264", clockRate=90000, payloadType=103,
        parameters={"level-asymmetry-allowed": "1", "packetization-mode": "1",
                    "profile-level-id": profile_id}))
    CODECS["video"].append(RTCRtpCodecParameters(
        mimeType="video/rtx", clockRate=90000, payloadType=104,
        parameters={"apt": 103}))


async def index(_request):
    return web.Response(text=HTML, content_type="text/html")


async def offer(request):
    app = request.app
    # The test has one viewer. Sharing compressed packets through an
    # unbuffered MediaRelay can overwrite a packet before it is sent.
    for old_pc in tuple(app["pcs"]):
        await old_pc.close()
        app["pcs"].discard(old_pc)
    pc = RTCPeerConnection()
    app["pcs"].add(pc)

    @pc.on("connectionstatechange")
    async def connection_state_changed():
        print(f"WebRTC connection: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            app["pcs"].discard(pc)

    try:
        params = await request.json()
        transceiver = pc.addTransceiver("video", direction="sendonly")
        transceiver.setCodecPreferences(h264_codecs(app["profile_id"]))
        try:
            await pc.setRemoteDescription(RTCSessionDescription(
                sdp=params["sdp"], type=params["type"]))
        except OperationError as exc:
            raise web.HTTPBadRequest(text=(
                f"H.264 profile negotiation failed for source {app['profile_id']}. "
                "Configure camera to use Baseline profile or use a browser "
                "that offers this profile.")) from exc
        if not transceiver._codecs:
            raise web.HTTPBadRequest(text=(
                f"Browser offer does not support source H.264 profile "
                f"{app['profile_id']}; configure camera to use Baseline profile"))
        transceiver.sender.replaceTrack(app["player"].video)
        await pc.setLocalDescription(await pc.createAnswer())
        return web.json_response({"sdp": pc.localDescription.sdp,
                                  "type": pc.localDescription.type})
    except Exception:
        await pc.close()
        app["pcs"].discard(pc)
        raise


async def status(request):
    peers = []
    for pc in tuple(request.app["pcs"]):
        for sender in pc.getSenders():
            if sender.track and sender.track.kind == "video":
                stats = await sender.getStats()
                peers.extend({"state": pc.connectionState,
                              "packetsSent": report.packetsSent,
                              "bytesSent": report.bytesSent}
                             for report in stats.values()
                             if report.type == "outbound-rtp" and report.kind == "video")
    return web.json_response({"sourceCodec": "H.264",
                              "sourceProfileLevelId": request.app["profile_id"],
                              "decode": False,
                              "videoPeers": peers})


async def shutdown(app):
    await asyncio.gather(*(pc.close() for pc in tuple(app["pcs"])),
                         return_exceptions=True)
    app["pcs"].clear()
    app["player"].video.stop()


def build_app(url, transport, timeout):
    player = MediaPlayer(url, format="rtsp",
                         options={"rtsp_transport": transport},
                         timeout=timeout, decode=False)
    if player.video is None:
        raise RuntimeError("RTSP source has no supported H.264 video track")
    codec = player._MediaPlayer__container.streams.video[0].codec_context.name
    if codec != "h264":
        player.video.stop()
        raise RuntimeError(f"RTSP source uses {codec}, expected H.264")
    profile_id = source_profile_id(
        player._MediaPlayer__container.streams.video[0].codec_context.extradata)
    register_source_codec(profile_id)
    app = web.Application()
    app["player"] = player
    app["profile_id"] = profile_id
    app["pcs"] = set()
    app.router.add_get("/", index)
    app.router.add_get("/status", status)
    app.router.add_post("/offer", offer)
    app.on_shutdown.append(shutdown)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.144.135/live")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--timeout", type=int, default=5,
                        help="RTSP open/read timeout in seconds")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    app = build_app(args.rtsp_url, args.transport, args.timeout)
    print("RTSP H.264 -> WebRTC H.264 packet relay (decode=False, no encoder)")
    print(f"Source H.264 profile-level-id: {app['profile_id']}")
    print(f"Open http://<server-ip>:{args.port}/ ; inspect /status for packetsSent")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
