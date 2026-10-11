from clip_queue import ClipQueue, SeenStore
from fakes import clip


def test_add_dedupes_within_and_across_batches():
    q = ClipQueue()
    assert [c.brightcove_id for c in q.add([clip(1), clip(1), clip(2)])] == ["bc1", "bc2"]
    assert q.add([clip(1), clip(2)]) == []
    assert q.pending_count() == 2


def test_only_one_clip_current_at_a_time():
    q = ClipQueue()
    q.add([clip(1), clip(2)])
    first = q.begin_next()
    assert first.brightcove_id == "bc1"
    assert q.begin_next() is None  # no overlap while one is current
    q.mark_started(first)
    assert q.finish_current() is first
    assert q.finish_current() is None  # duplicate FINISHED is a no-op
    assert q.begin_next().brightcove_id == "bc2"


def test_finish_before_start_is_ignored_and_abort_releases():
    q = ClipQueue()
    q.add([clip(1)])
    current = q.begin_next()
    assert q.finish_current() is None  # card still showing, not started
    assert q.busy
    assert q.abort_current() is current
    assert q.drained()


def test_seen_is_bounded_and_blocks_requeue():
    q = ClipQueue(seen_limit=2)
    for n in (1, 2, 3):
        q.add([clip(n)])
        c = q.begin_next()
        q.mark_started(c)
        q.finish_current()
    assert q.seen_ids() == ["bc2", "bc3"]
    assert q.add([clip(3)]) == []
    assert [c.brightcove_id for c in q.add([clip(1)])] == ["bc1"]


def test_failed_ids_retry_after_ttl():
    now = [0.0]
    q = ClipQueue(failed_ttl=60, clock=lambda: now[0])
    q.mark_failed("bc1")
    assert q.is_known("bc1")
    assert q.add([clip(1)]) == []
    now[0] = 61
    assert not q.is_known("bc1")
    assert len(q.add([clip(1)])) == 1


def test_reset_forgets_everything():
    q = ClipQueue()
    q.add([clip(1)])
    c = q.begin_next()
    q.mark_started(c)
    q.finish_current()
    q.reset()
    assert len(q.add([clip(1)])) == 1


def test_seen_store_roundtrip(tmp_path):
    store = SeenStore(tmp_path / "state.json", limit=3)
    assert store.load() == []
    store.save(["a", "b", "c", "d"])
    assert store.load() == ["b", "c", "d"]
    (tmp_path / "state.json").write_text("not json", encoding="utf-8")
    assert store.load() == []
