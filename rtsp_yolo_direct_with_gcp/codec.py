"""Negotiate the camera's H.264 profile without invoking a video encoder."""

from aiortc import RTCRtpSender, sdp
from aiortc.codecs import CODECS
from aiortc.rtcrtpparameters import RTCRtpCodecParameters


def profile_from_sps(extradata):
    marker = b"\x00\x00\x00\x01\x67"
    index = extradata.find(marker)
    if index < 0 or len(extradata) < index + 8:
        raise RuntimeError("RTSP stream has no readable H.264 SPS")
    return extradata[index + 5:index + 8].hex()


def register_profile(profile_id):
    profile = sdp.parse_h264_profile_level_id(profile_id)[0]
    for codec in CODECS["video"]:
        existing = codec.parameters.get("profile-level-id")
        if existing and sdp.parse_h264_profile_level_id(existing)[0] == profile:
            return
    used = {codec.payloadType for codec in CODECS["video"]}
    payload = next(value for value in range(103, 127, 2)
                   if value not in used and value + 1 not in used)
    CODECS["video"].extend((
        RTCRtpCodecParameters(
            mimeType="video/H264", clockRate=90000, payloadType=payload,
            parameters={"level-asymmetry-allowed": "1", "packetization-mode": "1",
                        "profile-level-id": profile_id}),
        RTCRtpCodecParameters(
            mimeType="video/rtx", clockRate=90000, payloadType=payload + 1,
            parameters={"apt": payload}),
    ))


def preferences(profile_id):
    profile = sdp.parse_h264_profile_level_id(profile_id)[0]
    codecs = [codec for codec in RTCRtpSender.getCapabilities("video").codecs
              if codec.mimeType.lower() == "video/h264"
              and sdp.parse_h264_profile_level_id(
                  codec.parameters["profile-level-id"])[0] == profile]
    if not codecs:
        raise RuntimeError(f"No H.264 sender codec for {profile_id}")
    return codecs
