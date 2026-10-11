import json
from pathlib import Path

import pytest
import requests

import brightcove
from brightcove import HLS_MIME, PolicyKeyError, pick_mp4_source, resolve_clip
from fakes import clip

FIXTURES = Path(__file__).parent / "fixtures"


def test_pick_highest_mp4_not_last_source():
    payload = json.loads((FIXTURES / "brightcove_sources.json").read_text(encoding="utf-8"))
    src, mime = pick_mp4_source(payload["sources"])
    assert src.endswith("high.mp4")
    assert mime == "video/mp4"


def test_empty_sources_returns_none():
    assert pick_mp4_source([]) == (None, None)
    assert pick_mp4_source(None) == (None, None)


def test_prefers_https_mp4():
    sources = [
        {"src": "http://cdn.example/a.mp4", "container": "MP4", "height": 1080},
        {"src": "https://cdn.example/b.mp4", "container": "MP4", "height": 1080},
        {"src": "https://cdn.example/c.mp4?sig=1", "height": 720},
    ]
    assert pick_mp4_source(sources) == ("https://cdn.example/b.mp4", "video/mp4")


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP {}".format(self.status_code))

    def json(self):
        return self._payload


def getter(response, seen=None):
    def get(url, headers=None, timeout=None):
        if seen is not None:
            seen.append((url, headers, timeout))
        return response
    return get


def test_resolve_401_raises_policy_key_error_without_key():
    with pytest.raises(PolicyKeyError) as info:
        resolve_clip(clip(1, url=False), http_get=getter(FakeResponse(401)), pk="secret-key")
    assert "secret-key" not in str(info.value)


def test_resolve_empty_sources_leaves_no_url():
    c = resolve_clip(clip(1, url=False), http_get=getter(FakeResponse(200, {"sources": []})), pk="k")
    assert c.playback_url is None


def test_resolve_hls_only_uses_hls_mime():
    payload = {"sources": [{"src": "https://cdn.example/master.m3u8", "type": "application/x-mpegURL"}],
               "duration": 21000}
    seen = []
    c = resolve_clip(clip(1, url=False), http_get=getter(FakeResponse(200, payload), seen), pk="k")
    assert c.playback_url.endswith("master.m3u8")
    assert c.mime == HLS_MIME
    assert c.duration_ms == 21000
    assert seen[0][1]["accept"] == "application/json;pk=k"
    assert seen[0][2] == 10


def test_resolve_5xx_raises_http_error():
    with pytest.raises(requests.HTTPError):
        resolve_clip(clip(1, url=False), http_get=getter(FakeResponse(503)), pk="k")


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=865700,RESOLUTION=640x360,CODECS="mp4a.40.2,avc1.42c01f"
v360/index.m3u8?token=a
#EXT-X-STREAM-INF:BANDWIDTH=2414500,RESOLUTION=1280x720,CODECS="mp4a.40.2,avc1.4d4020"
v720/index.m3u8?token=b
#EXT-X-STREAM-INF:BANDWIDTH=4087600,RESOLUTION=1920x1080,CODECS="mp4a.40.2,avc1.64002a"
v1080/index.m3u8?token=c
#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=3840x2160,CODECS="mp4a.40.2,hvc1.2.4.L153"
v2160/index.m3u8?token=d
"""

NHL_SOURCES = [
    {"type": "application/x-mpegURL", "src": "http://manifest.example/master.m3u8"},
    {"type": "application/x-mpegURL", "src": "https://manifest.example/master.m3u8"},
    {"type": "application/dash+xml", "src": "https://manifest.example/manifest.mpd"},
    {"container": "MP4", "codec": "H264", "width": 1280, "height": 720, "avg_bitrate": 2132000,
     "src": "https://cdn.example/main.mp4"},
]


class _Text:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _getter(text, calls=None):
    def get(url, **kw):
        if calls is not None:
            calls.append(url)
        return _Text(text)
    return get


def test_parse_hls_master_resolves_relative_urls():
    variants = brightcove.parse_hls_master(MASTER, "https://manifest.example/a/master.m3u8?x=1")
    assert [v["height"] for v in variants] == [360, 720, 1080, 2160]
    assert variants[2]["url"] == "https://manifest.example/a/v1080/index.m3u8?token=c"
    assert variants[2]["codecs"] == "mp4a.40.2,avc1.64002a"


def test_choose_rendition_prefers_1080p_h264_hls_over_720p_mp4():
    calls = []
    url, mime, desc = brightcove.choose_rendition(NHL_SOURCES, 1080, http_get=_getter(MASTER, calls))
    assert url == "https://manifest.example/v1080/index.m3u8?token=c"
    assert mime == brightcove.HLS_MIME
    assert desc == "HLS 1920x1080 4.1 Mbps mp4a.40.2,avc1.64002a"
    assert calls == ["https://manifest.example/master.m3u8"]  # the HTTPS master


def test_choose_rendition_respects_max_height_and_skips_hevc():
    url, mime, desc = brightcove.choose_rendition(NHL_SOURCES, 2160, http_get=_getter(MASTER))
    assert "v1080" in url  # 2160p rung is HEVC
    url, mime, desc = brightcove.choose_rendition(NHL_SOURCES, 720, http_get=_getter(MASTER))
    assert (url, mime) == ("https://cdn.example/main.mp4", "video/mp4")  # MP4 wins a tie
    assert desc.startswith("MP4 1280x720 2.1 Mbps")


def test_choose_rendition_falls_back_to_mp4_when_master_fails():
    def broken(url, **kw):
        raise OSError("network")
    url, mime, _desc = brightcove.choose_rendition(NHL_SOURCES, 1080, http_get=broken)
    assert (url, mime) == ("https://cdn.example/main.mp4", "video/mp4")


def test_choose_rendition_skips_hevc_mp4():
    sources = [{"container": "MP4", "codec": "HEVC", "height": 1080, "src": "https://cdn.example/hevc.mp4"},
               {"container": "MP4", "codec": "H264", "height": 540, "src": "https://cdn.example/avc.mp4"}]
    assert brightcove.choose_rendition(sources, 1080)[0] == "https://cdn.example/avc.mp4"


def test_rendition_options_list_what_is_offered():
    options = brightcove.rendition_options(NHL_SOURCES, http_get=_getter(MASTER))
    keys = [key for key, _label in options]
    assert keys == ["auto", "hls:1080", "hls:720", "mp4:720", "hls:360", "hls:adaptive"]  # HEVC 2160 dropped
    labels = dict(options)
    assert labels["hls:1080"] == "HLS 1080p \u00b7 1920x1080 \u00b7 H.264 High \u00b7 4.1 Mbps"
    assert labels["mp4:720"].startswith("MP4 720p")


def test_explicit_quality_choices():
    get = _getter(MASTER)
    assert "v720" in brightcove.choose_rendition(NHL_SOURCES, quality="hls:720", http_get=get)[0]
    assert brightcove.choose_rendition(NHL_SOURCES, quality="mp4:720", http_get=get)[0] == "https://cdn.example/main.mp4"
    assert brightcove.choose_rendition(NHL_SOURCES, quality="hls:adaptive", http_get=get)[0] == \
        "https://manifest.example/master.m3u8"
    # 540 isn't offered here: nearest lower rung
    assert "v360" in brightcove.choose_rendition(NHL_SOURCES, quality="hls:540", http_get=get)[0]
    # no MP4 that small: fall back to auto (1080 HLS)
    assert "v1080" in brightcove.choose_rendition(NHL_SOURCES, quality="mp4:360", http_get=get)[0]
