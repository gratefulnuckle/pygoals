"""Brightcove Playback API: pick an MP4, never embed the policy key in source."""

import logging
import os

import requests

log = logging.getLogger(__name__)

ACCOUNT_URL = "https://edge.api.brightcove.com/playback/v1/accounts/6415718365001/videos/{}"
HTTP_TIMEOUT = 10


def policy_key():
    return os.environ.get("BRIGHTCOVE_PK", "").strip()


def pick_mp4_source(sources):
    if not sources:
        return None, None
    mp4s = []
    for source in sources:
        src = source.get("src") or ""
        container = str(source.get("container") or "").upper()
        if container == "MP4" or src.lower().endswith(".mp4"):
            mp4s.append(source)
    if not mp4s:
        hls = [s for s in sources if "m3u8" in str(s.get("src") or "").lower()]
        if hls:
            return hls[0].get("src"), "application/x-mpegURL"
        return None, None
    best = max(mp4s, key=lambda s: s.get("height") or 0)
    return best.get("src"), "video/mp4"


def resolve_clip(clip, http_get=None, pk=None):
    key = pk if pk is not None else policy_key()
    if not key:
        raise RuntimeError("BRIGHTCOVE_PK is not set")
    getter = http_get or requests.get
    url = ACCOUNT_URL.format(clip.brightcove_id)
    headers = {
        "accept": "application/json;pk={}".format(key),
        "origin": "https://players.brightcove.net",
        "user-agent": "pygoals/1.1",
    }
    response = getter(url, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    src, mime = pick_mp4_source(payload.get("sources") or [])
    clip.playback_url = src
    clip.mime = mime or "video/mp4"
    if payload.get("duration"):
        try:
            clip.duration_ms = int(payload["duration"])
        except (TypeError, ValueError):
            pass
    return clip
