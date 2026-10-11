"""Parse NHL Forge goal listings into GoalClip rows. No Brightcove PK here."""

from dataclasses import dataclass
import logging

log = logging.getLogger(__name__)

MAX_LIVE_DURATION_MS = 90_000


@dataclass
class GoalClip:
    event_id: str
    brightcove_id: str
    player_id: str | None
    team: str | None
    title: str
    duration_ms: int
    playback_url: str | None = None
    mime: str = "video/mp4"


def _duration_ms(fields):
    raw = fields.get("duration")
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def _tags_player_team(tags):
    player_id = None
    team = None
    for tag in tags or []:
        extra = tag.get("extraData") or {}
        if extra.get("playerId"):
            player_id = str(extra["playerId"])
        if extra.get("abbreviation"):
            team = str(extra["abbreviation"])
    return player_id, team


def skip_reason(item):
    fields = item.get("fields") or {}
    if not fields.get("brightcoveId"):
        return "no_brightcove"
    player_id, team = _tags_player_team(item.get("tags"))
    duration = _duration_ms(fields)
    title = item.get("title") or ""
    if duration > MAX_LIVE_DURATION_MS:
        return "compilation"
    lowered = title.lower()
    if lowered.startswith("every ") or " from the " in lowered and "season" in lowered:
        return "compilation"
    if not player_id:
        return "no_player"
    if not team:
        return "no_team"
    return None


def clips_from_listing(payload):
    clips = []
    skips = []
    for item in payload.get("items") or []:
        reason = skip_reason(item)
        if reason:
            skips.append({"title": item.get("title"), "reason": reason})
            continue
        fields = item["fields"]
        brightcove_id = str(fields["brightcoveId"])
        event_id = str(fields.get("statsEventId") or brightcove_id)
        if event_id in ("0", "None"):
            event_id = brightcove_id
        player_id, team = _tags_player_team(item.get("tags"))
        clips.append(
            GoalClip(
                event_id=event_id,
                brightcove_id=brightcove_id,
                player_id=player_id,
                team=team,
                title=str(item.get("title") or ""),
                duration_ms=_duration_ms(fields),
            )
        )
    return clips, skips
