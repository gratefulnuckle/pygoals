"""Fake Chromecast pieces for player tests (no network, no pychromecast)."""

import threading
from types import SimpleNamespace

from nhl_ingest import GoalClip
from player import DeviceInfo


class FakeMediaController:
    def __init__(self):
        self.played = []
        self.listeners = []
        self.session_active_event = threading.Event()
        self.session_active_event.set()
        self.fail_urls = set()
        self.silent_urls = set()  # accepted but never reported (receiver ignores it)
        self.kwargs = []
        self.lock = threading.Lock()
        self.update_calls = 0

    def play_media(self, url, mime, **kwargs):
        if url in self.fail_urls:
            raise RuntimeError("load failed")
        with self.lock:
            self.played.append((url, mime))
            self.kwargs.append(kwargs)
        if url not in self.silent_urls:
            self.emit(player_state="PLAYING", content_id=url, current_time=0.0)

    def emit(self, **fields):
        status = SimpleNamespace(player_state=None, idle_reason=None, content_id=None, current_time=None,
                                 duration=None, stream_type="BUFFERED")
        for key, value in fields.items():
            setattr(status, key, value)
        for listener in list(self.listeners):
            listener.new_media_status(status)

    def update_status(self, *args, **kwargs):
        self.update_calls += 1

    def block_until_active(self, timeout=None):
        return None

    def register_status_listener(self, listener):
        self.listeners.append(listener)

    def videos(self):
        with self.lock:
            return [url for url, mime in self.played if mime != "image/png"]

    def finish(self, reason="FINISHED", content_id=None):
        if content_id is None:
            videos = self.videos()
            content_id = videos[-1] if videos else None
        self.emit(player_state="IDLE", idle_reason=reason, content_id=content_id)


class FakeCast:
    def __init__(self, name="Living Room", host="192.168.1.50", uuid="uuid-1", model="Chromecast"):
        self.cast_info = SimpleNamespace(friendly_name=name, host=host, uuid=uuid, model_name=model)
        self.name = name
        self.media_controller = FakeMediaController()
        self.quit_calls = 0
        self.disconnect_calls = 0
        self.wait_error = None

    def wait(self, timeout=None):
        if self.wait_error:
            raise self.wait_error

    def quit_app(self, timeout=None):
        self.quit_calls += 1

    def disconnect(self, timeout=None):
        self.disconnect_calls += 1


class FakeBrowser:
    def __init__(self):
        self.stopped = 0

    def stop_discovery(self):
        self.stopped += 1


def make_discover(*casts):
    browsers = []

    def discover(_known_hosts):
        browser = FakeBrowser()
        browsers.append(browser)
        return sorted((DeviceInfo.from_cast(c) for c in casts), key=lambda d: d.name.lower()), browser

    discover.browsers = browsers
    return discover


def clip(n, team="TOR", player="8479318", url=True):
    return GoalClip(
        event_id=str(n), brightcove_id="bc{}".format(n), player_id=player, team=team,
        title="Goal {}".format(n), duration_ms=20000,
        playback_url="https://cdn.example/{}.mp4".format(n) if url else None,
    )


def listing(*numbers):
    items = []
    for n in numbers:
        items.append({
            "title": "Goal {}".format(n),
            "fields": {"brightcoveId": "bc{}".format(n), "statsEventId": str(n), "duration": 20000},
            "tags": [{"extraData": {"playerId": "84{}".format(n)}}, {"extraData": {"abbreviation": "TOR"}}],
        })
    return {"items": items}


def fake_resolve(clip, pk=None, **_kw):
    clip.playback_url = "https://cdn.example/{}.mp4".format(clip.brightcove_id)
    clip.mime = "video/mp4"
    return clip
