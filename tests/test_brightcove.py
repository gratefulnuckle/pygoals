import json
from pathlib import Path

import pytest
import requests

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
