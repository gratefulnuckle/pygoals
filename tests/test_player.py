import threading
import time

import pytest

import player as player_mod
from brightcove import PolicyKeyError, set_policy_key
from fakes import FakeCast, fake_resolve, listing, make_discover
from player import NHLVideoPlayer, PlayerOptions


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


def make_player(payloads, cast=None, resolve=fake_resolve, **opts):
    feed = list(payloads)

    def fetch():
        return feed.pop(0) if len(feed) > 1 else feed[0]

    cast = cast or FakeCast()
    options = PlayerOptions(show_cards=False, card_seconds=0, poll_seconds=3600, **opts)
    p = NHLVideoPlayer(options, fetch_listing=fetch, discover=make_discover(cast), resolve=resolve)
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

    def resolve(clip, pk=None):
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
    def resolve(clip, pk=None):
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
        def __init__(self, directory, port=0):
            self.directory = directory

        def start(self):
            return self

        def set_client_target(self, host):
            return "192.168.1.10"

        def url_for(self, path):
            return "http://192.168.1.10:1/" + path.name

        def stop(self):
            pass

    p = NHLVideoPlayer(PlayerOptions(show_cards=True, card_seconds=0, overlay_path=str(tmp_path)),
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
