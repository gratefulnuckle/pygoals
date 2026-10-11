import threading
import time
from pathlib import Path

import pytest

import player as player_mod
from brightcove import PolicyKeyError, set_policy_key
from fakes import FakeCast, fake_resolve, listing, make_discover
from player import NHLVideoPlayer, PlayerOptions


@pytest.fixture(autouse=True)
def _fast_receiver_restart(monkeypatch):
    monkeypatch.setattr(player_mod, "RECEIVER_RESTART_PAUSE", 0)


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def key():
    set_policy_key("test-key")


def make_player(payloads, cast=None, resolve=fake_resolve, card_server_factory=None, **opts):
    feed = list(payloads)

    def fetch():
        return feed.pop(0) if len(feed) > 1 else feed[0]

    cast = cast or FakeCast()
    settings = dict(show_cards=False, card_seconds=0, poll_seconds=3600)
    settings.update(opts)
    options = PlayerOptions(**settings)
    p = NHLVideoPlayer(options, fetch_listing=fetch, discover=make_discover(cast), resolve=resolve,
                       card_server_factory=card_server_factory)
    return p, cast


def connect(p):
    devices = p.discover()
    assert p.connect(devices[0])
    return devices[0]


def test_poll_dedupes_across_polls(key):
    p, _cast = make_player([listing(1, 2), listing(1, 2, 3)])
    try:
        assert [c.brightcove_id for c in p.poll_listing()] == ["bc1", "bc2"]
        assert [c.brightcove_id for c in p.poll_listing()] == ["bc3"]
        assert p.poll_listing() == []
    finally:
        p.shutdown()


def test_without_key_nothing_is_queued():
    p, _cast = make_player([listing(1)])
    try:
        assert p.poll_listing() == []
        assert p.queue.pending_count() == 0
    finally:
        p.shutdown()


def test_advances_only_on_finished(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        mc = cast.media_controller
        assert mc.videos() == ["https://cdn.example/bc1.mp4"]
        mc.finish("INTERRUPTED")  # not a finish
        time.sleep(0.05)
        assert len(mc.videos()) == 1
        mc.finish("FINISHED")
        assert wait_for(lambda: len(mc.videos()) == 2)
    finally:
        p.shutdown()


def test_duplicate_finished_does_not_double_advance(key):
    p, cast = make_player([listing(1, 2, 3)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        first = mc.videos()[-1]
        mc.finish(content_id=first)
        assert wait_for(lambda: len(mc.videos()) == 2)
        mc.finish(content_id=first)  # late duplicates for bc1
        mc.finish(content_id=first)
        time.sleep(0.1)
        assert len(mc.videos()) == 2  # bc3 waits for bc2 to finish
    finally:
        p.shutdown()


def test_concurrent_advances_never_overlap(key):
    p, cast = make_player([listing(1, 2, 3, 4)])
    try:
        p.poll_listing()
        connect(p)
        threads = [threading.Thread(target=p.advance) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(2)
        assert len(cast.media_controller.videos()) == 1
    finally:
        p.shutdown()


def test_new_clips_after_queue_drained_start_playing(key):
    """Regression: the original never restarted playback after the queue emptied."""
    p, cast = make_player([listing(1), listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        mc.finish()
        assert wait_for(lambda: p.queue.drained())
        assert p._poll_once()  # the poll loop path: adds bc2 and kicks playback
        assert wait_for(lambda: len(mc.videos()) == 2)
    finally:
        p.shutdown()


def test_failed_load_skips_to_next_clip(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        cast.media_controller.fail_urls.add("https://cdn.example/bc1.mp4")
        errors = []
        p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(kind))
        assert p.advance() is True
        assert cast.media_controller.videos() == ["https://cdn.example/bc2.mp4"]
        assert errors == [player_mod.ERR_PLAYBACK]
        assert p.queue.is_known("bc1")  # cached as failed, not retried every poll
    finally:
        p.shutdown()


def test_no_mp4_is_cached_not_re_resolved(key):
    calls = []

    def resolve(clip, pk=None, **_kw):
        calls.append(clip.brightcove_id)
        clip.playback_url = None
        return clip

    p, _cast = make_player([listing(1)], resolve=resolve)
    try:
        assert p.poll_listing() == []
        assert p.poll_listing() == []
        assert calls == ["bc1"]
    finally:
        p.shutdown()


def test_auth_error_reported_once(key):
    def resolve(clip, pk=None, **_kw):
        raise PolicyKeyError("Brightcove rejected the policy key (HTTP 401)")

    p, _cast = make_player([listing(1, 2)], resolve=resolve)
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append((kind, message)))
    try:
        p.poll_listing()
        p.poll_listing()
        assert [k for k, _ in errors] == [player_mod.ERR_AUTH]
        assert "test-key" not in errors[0][1]
    finally:
        p.shutdown()


def test_once_semantics_wait_for_whole_queue(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        assert not p.wait_until_drained(0.2)  # still playing bc1
        mc.finish()
        assert wait_for(lambda: len(mc.videos()) == 2)
        assert not p.queue.drained()
        mc.finish()
        assert p.wait_until_drained(3)
    finally:
        p.shutdown()


def test_skip_moves_to_next(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        p.skip().join(2)
        assert len(cast.media_controller.videos()) == 2
    finally:
        p.shutdown()


def test_shutdown_is_idempotent_and_cleans_up(key):
    p, cast = make_player([listing(1)])
    connect(p)
    stopped = []
    p.events.subscribe(player_mod.STOPPED, lambda: stopped.append(1))
    overlay = p.overlay_dir
    p.shutdown()
    p.shutdown()
    assert stopped == [1]
    assert cast.quit_calls == 1
    assert not overlay.exists()
    assert all(b.stopped == 1 for b in p._discover.browsers)


def test_connect_failure_reports_no_device(key):
    cast = FakeCast()
    cast.wait_error = TimeoutError("wait")
    p, _ = make_player([listing(1)], cast=cast)
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(kind))
    try:
        devices = p.discover()
        assert p.connect(devices[0]) is False
        assert errors == [player_mod.ERR_NO_DEVICE]
        assert p.cast is None
    finally:
        p.shutdown()


def test_switching_device_releases_old_cast(key):
    a, b = FakeCast("A", uuid="a"), FakeCast("B", uuid="b", host="192.168.1.51")
    p = NHLVideoPlayer(PlayerOptions(show_cards=False), fetch_listing=lambda: listing(),
                       discover=make_discover(a, b), resolve=fake_resolve)
    try:
        devices = p.discover()
        assert p.connect(devices[0])
        assert p.connect(devices[1])
        assert p.cast is b
        assert a.quit_calls == 1 and a.disconnect_calls == 1
    finally:
        p.shutdown()


def test_cards_are_served_and_old_ones_cleaned(key, tmp_path, monkeypatch):
    rendered = []

    def fake_render(player_id, team, title, out_dir=None):
        path = out_dir / "card-{}-{}.png".format(player_id, len(rendered))
        path.write_bytes(b"png")
        rendered.append(path)
        return path

    monkeypatch.setattr(player_mod, "render_card", fake_render)

    class FakeServer:
        host_for_clients = "192.168.1.10"
        port = 8765

        def __init__(self, directory, port=0):
            self.directory = directory

        def start(self):
            return self

        def wait_for_fetch(self, name, timeout, stop=None):
            return True

        def set_client_target(self, host):
            return "192.168.1.10"

        def url_for(self, path):
            return "http://192.168.1.10:1/" + path.name

        def stop(self):
            pass

    p = NHLVideoPlayer(PlayerOptions(show_cards=True, card_mode="image", card_seconds=0, overlay_path=str(tmp_path)),
                       fetch_listing=lambda: listing(1, 2), discover=make_discover(FakeCast()),
                       resolve=fake_resolve, card_server_factory=FakeServer)
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        p.cast.media_controller.finish()
        assert wait_for(lambda: len(p.cast.media_controller.videos()) == 2)
        cards = sorted(x.name for x in tmp_path.glob("card-*.png"))
        assert cards == [rendered[-1].name]  # previous card deleted
    finally:
        p.shutdown()
    assert list(tmp_path.glob("card-*.png")) == []


class _UnreachableServer:
    host_for_clients = "192.168.1.10"
    port = 8765

    def __init__(self, directory, port=0):
        self.waits = []

    def start(self):
        return self

    def set_client_target(self, host):
        return "192.168.1.10"

    def url_for(self, path):
        return "http://192.168.1.10:8765/" + path.name

    def wait_for_fetch(self, name, timeout, stop=None):
        self.waits.append(name)
        return False  # the TV never GETs the card (firewall)

    def stop(self):
        pass


def test_clip_plays_when_card_is_unreachable(key, tmp_path, monkeypatch):
    monkeypatch.setattr(player_mod, "render_card",
                        lambda pid, team, title, out_dir=None: (out_dir / "card-{}-x.png".format(pid)))
    monkeypatch.setattr(player_mod, "CARD_FETCH_TIMEOUT", 0.05)
    p = NHLVideoPlayer(PlayerOptions(show_cards=True, card_mode="image", card_seconds=30, overlay_path=str(tmp_path)),
                       fetch_listing=lambda: listing(1, 2), discover=make_discover(FakeCast()),
                       resolve=fake_resolve, card_server_factory=_UnreachableServer)
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append((kind, message)))
    try:
        p.poll_listing()
        connect(p)
        started = time.monotonic()
        assert p.advance() is True
        assert time.monotonic() - started < 5  # did not sit through card_seconds=30
        mc = p.cast.media_controller
        assert mc.videos() == ["https://cdn.example/bc1.mp4"]
        mc.finish()
        assert wait_for(lambda: len(mc.videos()) == 2)
        kinds = [k for k, _ in errors]
        assert kinds == [player_mod.ERR_CARD_UNREACHABLE]  # toast once, not per clip
        assert "firewall" in errors[0][1].lower() and "8765" in errors[0][1]
    finally:
        p.shutdown()


def test_loads_use_buffered_stream_type(key):
    p, cast = make_player([listing(1)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        assert cast.media_controller.kwargs[-1]["stream_type"] == "BUFFERED"
    finally:
        p.shutdown()


def test_video_load_never_confirmed_skips_to_next(key, monkeypatch):
    monkeypatch.setattr(player_mod, "ACTIVE_TIMEOUT", 0.3)
    p, cast = make_player([listing(1, 2)])
    cast.media_controller.silent_urls.add("https://cdn.example/bc1.mp4")
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(kind))
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        assert cast.media_controller.videos()[-1] == "https://cdn.example/bc2.mp4"
        assert errors == [player_mod.ERR_PLAYBACK]
    finally:
        p.shutdown()


def test_watchdog_skips_clip_stuck_buffering(key):
    p, cast = make_player([listing(1, 2)])
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(message))
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        url = "https://cdn.example/bc1.mp4"
        mc.emit(player_state="BUFFERING", content_id=url, current_time=4.176)
        t0 = p._started_at
        p.check_playback(now=t0 + 1)
        p.check_playback(now=t0 + 10)
        assert len(mc.videos()) == 1  # still within the stall window
        p.check_playback(now=t0 + 1 + player_mod.STALL_SECONDS + 1)
        assert wait_for(lambda: len(mc.videos()) == 2)
        assert "stuck BUFFERING" in errors[0]
        assert mc.update_calls >= 1  # watchdog asks the receiver for fresh status
    finally:
        p.shutdown()


def test_watchdog_leaves_progressing_clip_alone(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        url = "https://cdn.example/bc1.mp4"
        t0 = p._started_at
        for step in range(1, 6):
            mc.emit(player_state="PLAYING", content_id=url, current_time=float(step))
            p.check_playback(now=t0 + step * 10)
        assert len(mc.videos()) == 1
    finally:
        p.shutdown()


def test_media_status_transitions_are_logged(key, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="pygoals.player")
    p, cast = make_player([listing(1)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        cast.media_controller.emit(player_state="BUFFERING", content_id="https://cdn.example/bc1.mp4?token=SECRET",
                                   current_time=4.2, duration=53.5)
        text = caplog.text
        assert "LOAD video/mp4 cdn.example/\u2026/bc1.mp4" in text
        assert "Chromecast media: BUFFERING" in text and "t=4.2/53.5" in text
        assert "SECRET" not in text
    finally:
        p.shutdown()


def test_receiver_restarted_between_card_image_and_video(key, tmp_path, monkeypatch):
    monkeypatch.setattr(player_mod, "RECEIVER_RESTART_PAUSE", 0)
    monkeypatch.setattr(player_mod, "render_card",
                        lambda pid, team, title, out_dir=None: (out_dir / "card-{}-x.png".format(pid)))
    cast = FakeCast()
    order = []
    real_quit = cast.quit_app

    def quit_app(timeout=None):
        order.append("quit")
        real_quit(timeout)

    cast.quit_app = quit_app
    real_play = cast.media_controller.play_media

    def play_media(url, mime, **kw):
        order.append(mime)
        real_play(url, mime, **kw)

    cast.media_controller.play_media = play_media

    class Server(_UnreachableServer):
        def wait_for_fetch(self, name, timeout, stop=None):
            return True

    p = NHLVideoPlayer(PlayerOptions(show_cards=True, card_mode="image", card_seconds=0, overlay_path=str(tmp_path)),
                       fetch_listing=lambda: listing(1), discover=make_discover(cast),
                       resolve=fake_resolve, card_server_factory=Server)
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        assert order == ["image/png", "quit", "video/mp4"]
    finally:
        p.shutdown()


def test_no_receiver_restart_without_image(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        cast.media_controller.finish()
        assert wait_for(lambda: len(cast.media_controller.videos()) == 2)
        assert cast.quit_calls == 0
    finally:
        p.shutdown()


def test_watchdog_skips_clip_frozen_while_playing(key):
    p, cast = make_player([listing(1, 2)])
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        mc = cast.media_controller
        mc.emit(player_state="PLAYING", content_id="https://cdn.example/bc1.mp4", current_time=4.2)
        t0 = p._started_at
        p.check_playback(now=t0 + 1)
        p.check_playback(now=t0 + 2 + player_mod.STALL_SECONDS)
        assert wait_for(lambda: len(mc.videos()) == 2)
    finally:
        p.shutdown()


def test_max_height_passed_to_resolver(key):
    seen = []

    def resolve(clip, pk=None, **kw):
        seen.append(kw.get("max_height"))
        return fake_resolve(clip, pk=pk)

    p, _cast = make_player([listing(1)], resolve=resolve, max_height=720)
    try:
        p.poll_listing()
        assert seen == [720]
    finally:
        p.shutdown()


def test_queued_clip_re_resolved_after_quality_change(key):
    calls = []

    def resolve(clip, pk=None, **kw):
        calls.append(kw.get("quality"))
        clip.playback_url = "https://cdn.example/{}-{}.mp4".format(clip.brightcove_id, kw.get("quality"))
        clip.mime = "video/mp4"
        return clip

    p, cast = make_player([listing(1)], resolve=resolve)
    try:
        p.poll_listing()
        p.options.quality = "mp4:720"
        connect(p)
        p.advance()
        assert calls == ["auto", "mp4:720"]
        assert cast.media_controller.videos() == ["https://cdn.example/bc1-mp4:720.mp4"]
    finally:
        p.shutdown()


def test_available_renditions_falls_back_and_caches(monkeypatch):
    import brightcove

    monkeypatch.setattr(player_mod, "_rendition_cache", {"options": None, "at": 0.0})
    options, live = player_mod.available_renditions(pk="", fetch_listing=lambda: {})
    assert live is False and options == brightcove.STATIC_OPTIONS

    class P:
        def known_sources(self):
            return [{"container": "MP4", "codec": "H264", "height": 720, "width": 1280,
                     "avg_bitrate": 2000000, "src": "https://cdn.example/a.mp4"}]

    options, live = player_mod.available_renditions(player=P())
    assert live is True and [k for k, _ in options] == ["auto", "mp4:720"]
    again, live = player_mod.available_renditions(player=None, pk="")
    assert live is True and again == options  # cached


class _FetchingServer(_UnreachableServer):
    fetched = True

    def wait_for_fetch(self, name, timeout, stop=None):
        return self.fetched

    def was_fetched(self, name):
        return self.fetched


def _video_card_player(tmp_path, monkeypatch, cast, server=_FetchingServer, n=2, encode=None):
    monkeypatch.setattr(player_mod, "render_card",
                        lambda pid, team, title, out_dir=None: (out_dir / "card-{}-x.png".format(pid)))
    encoded = []

    def fake_encode(png, seconds, out_path=None, **kw):
        encoded.append((Path(png).name, seconds))
        if encode is not None:
            encode()
        out_path.write_bytes(b"mp4")
        return out_path

    monkeypatch.setattr(player_mod, "card_video", fake_encode)
    p = NHLVideoPlayer(PlayerOptions(show_cards=True, card_mode="video", card_seconds=4, poll_seconds=3600,
                                     overlay_path=str(tmp_path)),
                       fetch_listing=lambda: listing(*range(1, n + 1)), discover=make_discover(cast),
                       resolve=fake_resolve, card_server_factory=server)
    return p, encoded


def test_video_card_queued_with_clip_no_receiver_restart(key, tmp_path, monkeypatch):
    cast = FakeCast()
    p, encoded = _video_card_player(tmp_path, monkeypatch, cast)
    mc = cast.media_controller
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        load = mc.queue_loads[-1]
        assert load[0] == ("http://192.168.1.10:8765/card-841-x.mp4", "video/mp4")
        assert load[1] == ("https://cdn.example/bc1.mp4", "video/mp4")
        assert cast.quit_calls == 0  # no restart between card and clip
        assert encoded[0] == ("card-841-x.png", 4.0)
        # the card's FINISHED (reported with the clip's id) must not end the clip
        mc.queue_advance()
        assert p.queue.current is not None and p.queue.current.brightcove_id == "bc1"
        # the next card is encoded in the background while this clip plays
        assert wait_for(lambda: ("card-842-x.png", 4.0) in encoded)
        mc.finish(content_id="https://cdn.example/bc1.mp4")
        assert wait_for(lambda: len(mc.queue_loads) == 2)
        assert encoded.count(("card-842-x.png", 4.0)) == 1  # prefetched, not encoded twice
    finally:
        p.shutdown()


def test_video_card_falls_back_to_direct_load_when_not_fetched(key, tmp_path, monkeypatch):
    monkeypatch.setattr(player_mod, "CARD_FETCH_TIMEOUT", 0.05)

    class Blocked(_FetchingServer):
        fetched = False

    cast = FakeCast()
    cast.media_controller.silent_urls.add("http://192.168.1.10:8765/card-841-x.mp4")
    p, _encoded = _video_card_player(tmp_path, monkeypatch, cast, server=Blocked, n=1)
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(kind))
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        assert cast.media_controller.videos() == ["https://cdn.example/bc1.mp4"]  # plain LOAD
        assert errors == [player_mod.ERR_CARD_UNREACHABLE]
    finally:
        p.shutdown()


def test_missing_ffmpeg_falls_back_to_image_cards(key, tmp_path, monkeypatch):
    from cards import CardVideoUnavailable

    def no_ffmpeg():
        raise CardVideoUnavailable("ffmpeg not found")

    cast = FakeCast()
    p, _encoded = _video_card_player(tmp_path, monkeypatch, cast, n=1, encode=no_ffmpeg)
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        played = cast.media_controller.played
        assert played[0][1] == "image/png" and played[-1] == ("https://cdn.example/bc1.mp4", "video/mp4")
        assert cast.quit_calls == 1  # image mode restarts the receiver
        assert p._video_cards_ok is False
    finally:
        p.shutdown()


def _custom_player(mode="auto", app="7B4ABD0E", launch_error=None, n=2, **opts):
    cast = FakeCast()
    cast.launch_error = launch_error
    p, cast = make_player([listing(*range(1, n + 1))], cast=cast, receiver_mode=mode, receiver_app_id=app,
                          show_cards=True, card_server_factory=_FetchingServer, **opts)
    return p, cast


def test_custom_receiver_launched_and_loads_carry_card_data(key, monkeypatch):
    monkeypatch.setattr(player_mod, "receiver_card", lambda clip, secs, **kw: {
        "title": clip.title, "player": "Auston Matthews", "headshot": "https://img/h.png", "cardSeconds": secs,
        "lowerSeconds": kw.get("lower_seconds")})
    p, cast = _custom_player(card_seconds=3, video_overlay=True)
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        assert cast.started_apps == ["7B4ABD0E"]
        mc = cast.media_controller
        assert mc.played == [("https://cdn.example/bc1.mp4", "video/mp4")]  # no card image/video
        kw = mc.kwargs[-1]
        assert kw["media_info"]["customData"]["pygoals"]["player"] == "Auston Matthews"
        assert kw["metadata"]["subtitle"] == "Auston Matthews"
        assert kw["metadata"]["images"] == [{"url": "https://img/h.png"}]
        mc.finish()
        assert wait_for(lambda: len(mc.videos()) == 2)
        assert cast.started_apps == ["7B4ABD0E"]  # already running: not relaunched
        assert not mc.queue_loads and cast.quit_calls == 0
    finally:
        p.shutdown()


def test_auto_falls_back_to_default_receiver_once(key, monkeypatch):
    monkeypatch.setattr(player_mod, "receiver_card", lambda clip, secs, **kw: {"title": clip.title})
    monkeypatch.setattr(player_mod, "card_video", lambda png, secs, out_path=None, **kw: out_path)
    p, cast = _custom_player(launch_error=RuntimeError("Failed to execute start app 7B4ABD0E"), card_mode="off")
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append((kind, message)))
    try:
        p.poll_listing()
        connect(p)
        assert p.advance() is True
        assert cast.started_apps == ["7B4ABD0E"]
        assert cast.media_controller.videos() == ["https://cdn.example/bc1.mp4"]
        assert "media_info" not in cast.media_controller.kwargs[-1]
        cast.media_controller.finish()
        assert wait_for(lambda: len(cast.media_controller.videos()) == 2)
        assert cast.started_apps == ["7B4ABD0E"]  # auto: not retried for every goal
        assert errors == []  # auto falls back quietly (logged at INFO)
        p.reset_receiver_choice()  # e.g. settings saved
        assert p.wants_custom_receiver() is True
    finally:
        p.shutdown()


def test_custom_mode_retries_each_goal_but_toasts_once(key, monkeypatch):
    p, cast = _custom_player(mode="custom", launch_error=TimeoutError("start app timed out"), card_mode="off")
    errors = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: errors.append(kind))
    messages = []
    p.events.subscribe(player_mod.ERROR, lambda kind, message: messages.append(message))
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        cast.media_controller.finish()
        assert wait_for(lambda: len(cast.media_controller.videos()) == 2)
        assert cast.started_apps == ["7B4ABD0E"] * 3  # connect + each goal
        assert errors == [player_mod.ERR_RECEIVER]
        assert "standard Cast receiver" in messages[0] and "timed out" not in messages[0]
    finally:
        p.shutdown()


@pytest.mark.parametrize("mode,app,expected", [
    ("default", "7B4ABD0E", False),
    ("auto", "", False),
    ("custom", "", False),
    ("auto", "7B4ABD0E", True),
    ("custom", "7B4ABD0E", True),
])
def test_receiver_selection(key, mode, app, expected):
    p, cast = _custom_player(mode=mode, app=app, card_mode="off")
    try:
        assert p.wants_custom_receiver() is expected
    finally:
        p.shutdown()


def test_no_text_over_video_by_default_custom_receiver(key, monkeypatch):
    seen = {}

    def fake_card(clip, secs, **kw):
        seen.update(kw)
        return {"title": clip.title, "player": "Auston Matthews", "headshot": "https://img/h.png",
                "cardSeconds": secs, "lowerSeconds": kw.get("lower_seconds")}

    monkeypatch.setattr(player_mod, "receiver_card", fake_card)
    p, cast = _custom_player(card_seconds=3)
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        kw = cast.media_controller.kwargs[-1]
        assert "title" not in kw and kw["metadata"] == {"metadataType": 0}
        assert seen["lower_seconds"] == 0
        assert kw["media_info"]["customData"]["pygoals"]["player"] == "Auston Matthews"  # card keeps details
        assert p.queue.current.title == "Goal 1"  # tray still has the title
    finally:
        p.shutdown()


def test_no_text_over_video_by_default_queue_items(key, tmp_path, monkeypatch):
    cast = FakeCast()
    p, _encoded = _video_card_player(tmp_path, monkeypatch, cast, n=1)
    sent = []
    real = cast.media_controller.send_message

    def capture(data, **kw):
        sent.append(data)
        return real(data, **kw)

    cast.media_controller.send_message = capture
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        for item in sent[-1]["items"]:
            assert item["media"]["metadata"] == {"metadataType": 0}
    finally:
        p.shutdown()


def test_title_sent_when_video_overlay_on(key):
    p, cast = make_player([listing(1)], video_overlay=True)
    try:
        p.poll_listing()
        connect(p)
        p.advance()
        assert cast.media_controller.kwargs[-1]["title"] == "Goal 1"
    finally:
        p.shutdown()


def test_custom_receiver_launched_on_connect_without_goals(key):
    p, cast = _custom_player(n=0, card_mode="off")
    try:
        connect(p)
        assert cast.started_apps == ["7B4ABD0E"]
        assert p.custom_receiver_running()
        assert p.advance() is False  # nothing queued
        assert cast.media_controller.played == []  # no idle.png on top of the receiver's own idle screen
    finally:
        p.shutdown()


def test_refused_custom_receiver_on_connect_shows_default_idle_card(key, tmp_path, monkeypatch):
    p, cast = _custom_player(n=0, launch_error=RuntimeError("Failed to execute start app 7B4ABD0E"),
                             card_mode="off", overlay_path=str(tmp_path))
    try:
        connect(p)
        assert cast.started_apps == ["7B4ABD0E"]
        assert p.wants_custom_receiver() is False
        p.advance()
        assert cast.media_controller.played[-1][1] == "image/png"  # logo idle card on the default receiver
    finally:
        p.shutdown()
