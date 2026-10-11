# nhl-video-ingest

## Purpose

Discover single-goal highlight clips and resolve a Chromecast-playable URL
without crashing the poll loop or hammering Brightcove.

## Requirements

### Requirement: Listing does not crash on poor metadata

A playable item MUST have a Brightcove id. Items without player or team tags
SHALL be skipped or queued as metadata-poor. Ingest SHALL NOT raise
`UnboundLocalError` / `KeyError` on missing `playerId`, team abbreviation,
or `statsEventId`.

#### Scenario: Compilation tagged `goal`

- GIVEN a Forge item with `tags.slug=goal` and no player/team extraData
- WHEN the poll runs
- THEN the item is skipped (or marked compilation)
- AND the poll continues
- AND a skip reason is logged (`no_player`, `compilation`, …)

### Requirement: Stable identity

Playback identity SHALL be the Brightcove video id. Goal identity SHALL be
`(gameId, statsEventId)` when both exist. The app MUST NOT use a default
numeric `0` as an event id. Duplicate Brightcove ids SHALL not be queued twice.

#### Scenario: Two games share in-game event number 1281

- GIVEN two clips with `statsEventId` `"1281"` in different games
- WHEN both are ingested
- THEN both MAY enter the catalog if Brightcove ids differ
- AND neither is dropped because of a global event-number set

#### Scenario: Missing statsEventId

- GIVEN a clip with Brightcove id but no `statsEventId`
- WHEN ingest keys the item
- THEN the Brightcove id (or another unique CMS id) is used
- AND other missing-id clips are not collapsed onto `0`

### Requirement: Filter to single goals

The live play queue SHALL prefer real-time single-goal highlights (short
duration, goal + player metadata). Compilations MUST NOT enter the live
queue. Pagination MAY follow `nextUrl` only for backfill, with a cap.

#### Scenario: Season compilation on page 1

- GIVEN “Every batted-in goal this season” on the first page
- WHEN building the live queue
- THEN it is not played
- AND a real-time goal later on the page still can be

### Requirement: Brightcove resolve

Resolve SHALL use the Playback API with a policy key from configuration,
not source. The app SHALL select the highest HTTPS MP4 by container/type.
If only HLS exists, the Cast MIME SHALL be HLS, not a lie of `video/mp4`.
Already-resolved ids SHALL NOT be re-requested every poll.

#### Scenario: Mixed sources

- GIVEN `sources` containing HLS then several MP4 heights
- WHEN picking a playable URL
- THEN an MP4 source is chosen (prefer highest height)
- AND `sources[-1]` is not used unless it matches that filter

#### Scenario: Empty sources

- GIVEN `sources == []` or a 4xx
- WHEN resolve runs
- THEN the clip is failed/skipped with a reason
- AND it is not marked permanently seen until the failure is classified
- AND the poll thread survives

### Requirement: HTTP hygiene

All HTTP calls SHALL use a timeout, bounded retry on 5xx/timeout, and
non-2xx handling. Exceptions SHALL NOT kill the periodic scheduler.

#### Scenario: Brightcove 401 after key rotation

- GIVEN a 401 from Playback API
- WHEN the poll runs
- THEN the error is logged without the policy key
- AND the next poll still happens
- AND the process stays up

### Requirement: Mark seen after success

A clip SHALL NOT be marked consumed until playback has been successfully
started (or the user explicitly discards it). Failed resolve MUST remain
retryable unless the skip reason is permanent (`compilation`, `no_brightcove`).

#### Scenario: Transient 503

- GIVEN resolve 503s
- WHEN the next poll runs
- THEN the clip may be retried
- AND it was not added to the played set on the first failure

### Requirement: Team catalog

Store the NHL abbreviation. Map to display assets in config (ESPN slug
LAK→LA, SJS→SJ, TBL→TB, UTA→utah/UTAH; NJD→nj). ARI is historical; UTA is
current. Unknown teams SHALL use a fallback theme, not `KeyError`.

#### Scenario: Unknown abbreviation

- GIVEN team code `XYZ`
- WHEN a card or logo is requested
- THEN default colors are used
- AND ingest does not crash
