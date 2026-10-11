import json
from pathlib import Path

from nhl_ingest import _duration_ms, _tags_player_team, clips_from_listing, skip_reason

FIXTURES = Path(__file__).parent / "fixtures"


def test_skips_compilations_and_incomplete_tags():
    payload = json.loads((FIXTURES / "videos.json").read_text(encoding="utf-8"))
    clips, skips = clips_from_listing(payload)
    assert [c.brightcove_id for c in clips] == ["bc123"]
    assert clips[0].player_id == "8483515"
    assert clips[0].team == "MTL"
    assert clips[0].event_id == "1281"
    reasons = {s["title"]: s["reason"] for s in skips}
    assert reasons == {
        "Every Batted-in Goal from the 2025-26 NHL Season": "compilation",
        "Missing player tags": "no_player",
    }
    assert {s["id"] for s in skips} == {"comp1", "bc999"}


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


def test_string_durations_still_filter_compilations():
    assert _duration_ms({"duration": "600000"}) == 600000
    assert _duration_ms({"duration": "abc"}) == 0
    item = {"title": "Top 10", "fields": {"brightcoveId": "x", "duration": "600000"},
            "tags": [{"extraData": {"playerId": "1"}}, {"extraData": {"abbreviation": "TOR"}}]}
    assert skip_reason(item) == "compilation"


def test_player_named_in_title_wins_over_tag_order():
    tags = [
        {"title": "Mitch Marner", "extraData": {"playerId": "1"}},
        {"title": "Auston Matthews", "extraData": {"playerId": "2"}},
        {"extraData": {"abbreviation": "TOR"}},
    ]
    assert _tags_player_team(tags, "Matthews snipes from the slot") == ("2", "TOR")
    assert _tags_player_team(tags, "Leafs goal") == ("1", "TOR")


def test_bad_payload_shapes_do_not_raise():
    assert clips_from_listing({}) == ([], [])
    assert clips_from_listing(None) == ([], [])
    assert clips_from_listing({"items": ["junk", None]}) == ([], [])
