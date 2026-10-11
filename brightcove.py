"""Brightcove Playback API: pick a playable source. The policy key comes from
the environment (BRIGHTCOVE_PK / .env) or settings.ini, never from source."""

import logging
import os
from urllib.parse import urlsplit

import http_util

log = logging.getLogger(__name__)

ACCOUNT_URL = "https://edge.api.brightcove.com/playback/v1/accounts/6415718365001/videos/{}"
HTTP_TIMEOUT = 10
HLS_MIME = "application/x-mpegURL"

_configured_key = ""


class PolicyKeyError(RuntimeError):
    """Brightcove rejected the policy key (HTTP 401/403)."""


def set_policy_key(key):
    """Key from settings.ini; the environment still wins in ``policy_key``."""
    global _configured_key
    _configured_key = (key or "").strip()


def policy_key():
    return os.environ.get("BRIGHTCOVE_PK", "").strip() or _configured_key


def _src(source):
    return str(source.get("src") or "")


def _is_https(source):
    return _src(source).lower().startswith("https://")


def _path_endswith(source, suffix):
    return urlsplit(_src(source)).path.lower().endswith(suffix)


def pick_mp4_source(sources):
    """Highest MP4, preferring HTTPS; HLS only if no MP4 exists."""
    if not sources:
        return None, None
    usable = [s for s in sources if isinstance(s, dict) and _src(s)]
    mp4s = [
        s for s in usable
        if str(s.get("container") or "").upper() == "MP4" or _path_endswith(s, ".mp4")
    ]
    if mp4s:
        best = max(mp4s, key=lambda s: (_is_https(s), s.get("height") or 0, s.get("avg_bitrate") or 0))
        return _src(best), "video/mp4"
    hls = [
        s for s in usable
        if "m3u8" in _src(s).lower() or "mpegurl" in str(s.get("type") or "").lower()
    ]
    if hls:
        best = max(hls, key=_is_https)
        return _src(best), HLS_MIME
    return None, None


def resolve_clip(clip, http_get=None, pk=None):
    key = pk if pk is not None else policy_key()
    if not key:
        raise RuntimeError("BRIGHTCOVE_PK is not set")
    getter = http_get or http_util.get
    url = ACCOUNT_URL.format(clip.brightcove_id)
    headers = {
        "accept": "application/json;pk={}".format(key),
        "origin": "https://players.brightcove.net",
    }
    response = getter(url, headers=headers, timeout=HTTP_TIMEOUT)
    status = getattr(response, "status_code", 200)
    if status in (401, 403):
        # Never include the key itself in the message.
        raise PolicyKeyError("Brightcove rejected the policy key (HTTP {})".format(status))
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


__all__ = ["PolicyKeyError", "pick_mp4_source", "policy_key", "resolve_clip", "set_policy_key"]
