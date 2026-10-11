import json
from pathlib import Path

from brightcove import pick_mp4_source

FIXTURES = Path(__file__).parent / "fixtures"


def test_pick_highest_mp4_not_last_source():
    payload = json.loads((FIXTURES / "brightcove_sources.json").read_text(encoding="utf-8"))
    src, mime = pick_mp4_source(payload["sources"])
    assert src.endswith("high.mp4")
    assert mime == "video/mp4"


def test_empty_sources_returns_none():
    assert pick_mp4_source([]) == (None, None)
    assert pick_mp4_source(None) == (None, None)
