import json
from pathlib import Path

from nhl_ingest import clips_from_listing, skip_reason

FIXTURES = Path(__file__).parent / "fixtures"


def test_skips_compilations_and_incomplete_tags():
    payload = json.loads((FIXTURES / "videos.json").read_text(encoding="utf-8"))
    clips, skips = clips_from_listing(payload)
    assert [c.brightcove_id for c in clips] == ["bc123"]
    assert clips[0].player_id == "8483515"
    assert clips[0].team == "MTL"
    assert clips[0].event_id == "1281"
    reasons = {s["reason"] for s in skips}
    assert "compilation" in reasons or "no_player" in reasons
    assert "no_player" in reasons


def test_missing_event_id_uses_brightcove_id_not_zero():
    payload = {
        "items": [
            {
                "title": "Goal",
                "fields": {"brightcoveId": "onlybc", "duration": 15000},
                "tags": [
                    {"extraData": {"playerId": "1"}},
                    {"extraData": {"abbreviation": "TOR"}},
                ],
            }
        ]
    }
    clips, _skips = clips_from_listing(payload)
    assert clips[0].event_id == "onlybc"


def test_skip_reason_helpers():
    assert skip_reason({"fields": {}}) == "no_brightcove"
