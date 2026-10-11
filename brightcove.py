"""Brightcove Playback API: pick a playable source. The policy key comes from
the environment (BRIGHTCOVE_PK / .env) or settings.ini, never from source."""

import logging
import os
import re
from urllib.parse import urljoin, urlsplit

import http_util

log = logging.getLogger(__name__)

ACCOUNT_URL = "https://edge.api.brightcove.com/playback/v1/accounts/6415718365001/videos/{}"
HTTP_TIMEOUT = 10
HLS_MIME = "application/x-mpegURL"
DEFAULT_MAX_HEIGHT = 1080
# Video codecs every Chromecast decodes. HEVC/AV1/VP9/Dolby Vision are skipped.
_H264_PREFIXES = ("avc1", "avc3")
_OTHER_VIDEO = ("hvc1", "hev1", "dvh1", "dvhe", "av01", "vp09", "vp9", "vp8")
AUTO = "auto"
ADAPTIVE = "hls:adaptive"
_QUALITY_RE = re.compile(r"^(auto|hls:adaptive|(hls|mp4):[0-9]{3,4})$")
_H264_PROFILES = {"42": "Baseline", "4d": "Main", "58": "Extended", "64": "High"}
# Shown when the live source list can't be fetched (typical NHL ladder).
STATIC_OPTIONS = [
    ("auto", "Auto (best compatible)"),
    ("hls:1080", "HLS 1080p \u00b7 1920x1080 \u00b7 H.264 High \u00b7 ~4.1 Mbps"),
    ("hls:720", "HLS 720p \u00b7 1280x720 \u00b7 H.264 Main \u00b7 ~2.4 Mbps"),
    ("mp4:720", "MP4 720p \u00b7 1280x720 \u00b7 H.264 \u00b7 ~2.1 Mbps"),
    ("hls:540", "HLS 540p \u00b7 960x540 \u00b7 H.264 Main \u00b7 ~2.1 Mbps"),
    ("hls:360", "HLS 360p \u00b7 640x360 \u00b7 H.264 Main \u00b7 ~1.1 Mbps"),
    ("hls:270", "HLS 270p \u00b7 480x270 \u00b7 H.264 Baseline \u00b7 ~0.6 Mbps"),
    ("hls:adaptive", "HLS adaptive (receiver chooses)"),
]
_ATTR_RE = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')

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


def _is_h264_codec(codec):
    """Brightcove MP4 ``codec`` field: H264 or missing counts as H.264."""
    return not codec or str(codec).upper() in ("H264", "AVC", "AVC1")


def _hls_codecs_ok(codecs):
    if not codecs:
        return True
    parts = [c.strip().lower() for c in codecs.split(",") if c.strip()]
    if any(p.startswith(_OTHER_VIDEO) for p in parts):
        return False
    return any(p.startswith(_H264_PREFIXES) for p in parts) or not parts


def parse_hls_master(text, base_url):
    """Variants of an HLS master playlist: dicts with url/width/height/bandwidth/codecs."""
    variants = []
    lines = [line.strip() for line in str(text or "").splitlines()]
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = {k: v.strip('"') for k, v in _ATTR_RE.findall(line.split(":", 1)[1])}
        uri = next((l for l in lines[index + 1:] if l and not l.startswith("#")), None)
        if not uri:
            continue
        width = height = 0
        if "x" in attrs.get("RESOLUTION", ""):
            try:
                width, height = (int(v) for v in attrs["RESOLUTION"].lower().split("x", 1))
            except ValueError:
                width = height = 0
        try:
            bandwidth = int(attrs.get("BANDWIDTH") or 0)
        except ValueError:
            bandwidth = 0
        variants.append({"url": urljoin(base_url, uri), "width": width, "height": height,
                         "bandwidth": bandwidth, "codecs": attrs.get("CODECS", "")})
    return variants


def _mbps(bits):
    return "{:.1f} Mbps".format((bits or 0) / 1e6)


def is_quality(value):
    return bool(_QUALITY_RE.match(str(value or "").strip().lower()))


def _h264_profile(codecs):
    for part in str(codecs or "").lower().split(","):
        part = part.strip()
        if part.startswith(_H264_PREFIXES) and "." in part:
            return _H264_PROFILES.get(part.split(".", 1)[1][:2], "")
    return ""


def _mp4_candidates(sources):
    return [
        s for s in sources
        if (str(s.get("container") or "").upper() == "MP4" or _path_endswith(s, ".mp4"))
        and _is_h264_codec(s.get("codec"))
    ]


def _hls_master(sources):
    masters = [s for s in sources if "m3u8" in _src(s).lower() or "mpegurl" in str(s.get("type") or "").lower()]
    return max(masters, key=_is_https, default=None)


def _hls_variants(master, http_get=None):
    if master is None:
        return []
    getter = http_get or http_util.get
    try:
        response = getter(_src(master), timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return [v for v in parse_hls_master(response.text, _src(master))
                if _hls_codecs_ok(v["codecs"]) and v["height"] > 0]
    except Exception as exc:  # noqa: BLE001 - callers fall back
        log.debug("HLS master unreadable: %s", exc)
        return []


def _usable(sources):
    return [s for s in sources or [] if isinstance(s, dict) and _src(s)]


def rendition_options(sources, http_get=None):
    """``[(key, label)]`` for every H.264 rendition Brightcove offers, tallest first."""
    usable = _usable(sources)
    best = {}
    for v in _hls_variants(_hls_master(usable), http_get):
        key = "hls:{}".format(v["height"])
        if key not in best or v["bandwidth"] > best[key][0]:
            profile = _h264_profile(v["codecs"])
            label = "HLS {}p \u00b7 {}x{} \u00b7 H.264{} \u00b7 {}".format(
                v["height"], v["width"], v["height"], " " + profile if profile else "", _mbps(v["bandwidth"]))
            best[key] = (v["bandwidth"], v["height"], label)
    for s in _mp4_candidates(usable):
        height = s.get("height") or 0
        if not height:
            continue
        key = "mp4:{}".format(height)
        rate = s.get("avg_bitrate") or 0
        if key not in best or rate > best[key][0]:
            label = "MP4 {}p \u00b7 {}x{} \u00b7 H.264 \u00b7 {}".format(height, s.get("width") or "?", height, _mbps(rate))
            best[key] = (rate, height, label)
    ordered = sorted(best.items(), key=lambda kv: (-kv[1][1], kv[0]))
    options = [(AUTO, "Auto (best compatible)")] + [(key, value[2]) for key, value in ordered]
    if _hls_master(usable) is not None:
        options.append((ADAPTIVE, "HLS adaptive (receiver chooses)"))
    return options


def _pick_specific(quality, usable, http_get):
    """Honour an explicit dropdown choice; nearest lower rung if missing."""
    kind, _, size = quality.partition(":")
    master = _hls_master(usable)
    if quality == ADAPTIVE:
        return (_src(master), HLS_MIME, "HLS adaptive") if master is not None else None
    target = int(size)
    if kind == "hls":
        variants = [v for v in _hls_variants(master, http_get) if v["height"] <= target]
        v = max(variants, key=lambda v: (v["height"], v["bandwidth"]), default=None)
        if v is not None:
            return v["url"], HLS_MIME, "HLS {}x{} {} {}".format(v["width"], v["height"], _mbps(v["bandwidth"]),
                                                                  v["codecs"] or "?")
        return None
    mp4s = [s for s in _mp4_candidates(usable) if (s.get("height") or 0) <= target]
    s = max(mp4s, key=lambda s: (s.get("height") or 0, s.get("avg_bitrate") or 0, _is_https(s)), default=None)
    if s is not None:
        return _src(s), "video/mp4", "MP4 {}x{} {} {}".format(s.get("width") or "?", s.get("height") or "?",
                                                              _mbps(s.get("avg_bitrate")), s.get("codec") or "H264")
    return None


def choose_rendition(sources, max_height=DEFAULT_MAX_HEIGHT, http_get=None, quality=AUTO):
    """Best H.264 rendition no taller than ``max_height``.

    Returns ``(url, mime, description)``. Brightcove's progressive MP4 is often
    only 720p while its HLS ladder goes to 1080p, so the HLS master is read and
    its tallest H.264 variant is cast directly (a fixed variant playlist, so the
    receiver can't drop to a low rung). Falls back to the MP4, then the master.
    """
    max_height = int(max_height or DEFAULT_MAX_HEIGHT)
    usable = _usable(sources)
    quality = str(quality or AUTO).strip().lower()
    if quality != AUTO and is_quality(quality):
        picked = _pick_specific(quality, usable, http_get)
        if picked is not None:
            return picked
        log.info("quality %s not offered for this clip; using auto", quality)
    mp4s = [
        s for s in usable
        if (str(s.get("container") or "").upper() == "MP4" or _path_endswith(s, ".mp4"))
        and _is_h264_codec(s.get("codec"))
    ]
    fitting = [s for s in mp4s if (s.get("height") or 0) <= max_height] or [
        min(mp4s, key=lambda s: s.get("height") or 0)] if mp4s else []
    best_mp4 = max(fitting, key=lambda s: (s.get("height") or 0, s.get("avg_bitrate") or 0, _is_https(s)),
                   default=None)
    masters = [s for s in usable if "m3u8" in _src(s).lower() or "mpegurl" in str(s.get("type") or "").lower()]
    master = max(masters, key=_is_https, default=None)
    variant = None
    if master is not None:
        getter = http_get or http_util.get
        try:
            response = getter(_src(master), timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            candidates = [v for v in parse_hls_master(response.text, _src(master))
                          if _hls_codecs_ok(v["codecs"]) and 0 < v["height"] <= max_height]
            variant = max(candidates, key=lambda v: (v["height"], v["bandwidth"]), default=None)
        except Exception as exc:  # noqa: BLE001 - fall back to the MP4
            log.debug("HLS master unreadable: %s", exc)
    mp4_height = (best_mp4.get("height") or 0) if best_mp4 else -1
    if variant is not None and variant["height"] > mp4_height:
        desc = "HLS {}x{} {} {}".format(variant["width"], variant["height"], _mbps(variant["bandwidth"]),
                                         variant["codecs"] or "?")
        return variant["url"], HLS_MIME, desc
    if best_mp4 is not None:
        desc = "MP4 {}x{} {} {}".format(best_mp4.get("width") or "?", best_mp4.get("height") or "?",
                                         _mbps(best_mp4.get("avg_bitrate")), best_mp4.get("codec") or "H264")
        return _src(best_mp4), "video/mp4", desc
    if master is not None:
        return _src(master), HLS_MIME, "HLS master (adaptive)"
    return None, None, ""


def resolve_clip(clip, http_get=None, pk=None, max_height=DEFAULT_MAX_HEIGHT, quality=AUTO):
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
    clip.sources = payload.get("sources") or []
    src, mime, desc = choose_rendition(payload.get("sources") or [], max_height=max_height, http_get=getter,
                                       quality=quality)
    clip.playback_url = src
    clip.mime = mime or "video/mp4"
    try:
        clip.rendition = desc
    except AttributeError:
        pass
    if src:
        log.info("rendition for %s: %s", getattr(clip, "title", clip.brightcove_id), desc)
    if payload.get("duration"):
        try:
            clip.duration_ms = int(payload["duration"])
        except (TypeError, ValueError):
            pass
    return clip


__all__ = ["AUTO", "PolicyKeyError", "STATIC_OPTIONS", "choose_rendition", "is_quality", "rendition_options", "parse_hls_master", "pick_mp4_source", "policy_key", "resolve_clip", "set_policy_key"]
