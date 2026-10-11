"""Parse NHL Forge goal listings into GoalClip rows. No Brightcove key here."""

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
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw.strip()))
        except ValueError:
            return 0
    return 0


def _tag_label(tag):
    return str(tag.get("title") or tag.get("slug") or "").lower()


def _tags_player_team(tags, title=""):
    """First team tag; for players, prefer the one named in the clip title.

    A goal clip can carry several player tags (scorer, assists, goalie). If
    more than one distinct player id is present, pick the tag whose label
    appears in the title, else the first one, and log the ambiguity.
    """
    players = []
    team = None
    for tag in tags or []:
        if not isinstance(tag, dict):
            continue
        extra = tag.get("extraData") or {}
        if extra.get("playerId"):
            player_id = str(extra["playerId"])
            if player_id not in [p for p, _ in players]:
                players.append((player_id, _tag_label(tag)))
        if extra.get("abbreviation") and team is None:
            team = str(extra["abbreviation"])
    if not players:
        return None, team
    if len(players) > 1:
        lowered = (title or "").lower()
        for player_id, label in players:
            surname = label.split()[-1] if label.split() else ""
            if surname and surname in lowered:
                return player_id, team
        log.debug("ambiguous player tags for %r: %s", title, [p for p, _ in players])
    return players[0][0], team


def _is_compilation_title(lowered):
    return lowered.startswith("every ") or (" from the " in lowered and "season" in lowered)


def skip_reason(item):
    fields = item.get("fields") or {}
    if not fields.get("brightcoveId"):
        return "no_brightcove"
    title = item.get("title") or ""
    player_id, team = _tags_player_team(item.get("tags"), title)
    if _duration_ms(fields) > MAX_LIVE_DURATION_MS:
        return "compilation"
    if _is_compilation_title(title.lower()):
        return "compilation"
    if not player_id:
        return "no_player"
    if not team:
        return "no_team"
    return None


def clips_from_listing(payload):
    clips = []
    skips = []
    for item in (payload or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        reason = skip_reason(item)
        if reason:
            fields = item.get("fields") or {}
            skips.append({
                "id": str(fields.get("brightcoveId") or item.get("title") or ""),
                "title": item.get("title"),
                "reason": reason,
            })
            continue
        fields = item["fields"]
        brightcove_id = str(fields["brightcoveId"])
        event_id = str(fields.get("statsEventId") or brightcove_id)
        if event_id in ("0", "None"):
            event_id = brightcove_id
        title = str(item.get("title") or "")
        player_id, team = _tags_player_team(item.get("tags"), title)
        clips.append(
            GoalClip(
                event_id=event_id,
                brightcove_id=brightcove_id,
                player_id=player_id,
                team=team,
                title=title,
                duration_ms=_duration_ms(fields),
            )
        )
    return clips, skips
